"""Typed, bounded execution graph for composable DroneDream Harness workflows."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hashing import sha256_json

HarnessNodeKind = Literal["core", "plugin", "barrier"]
HarnessNodeFailureMode = Literal["fail-closed", "isolate", "fallback"]
HarnessNodeState = Literal["accepted", "failed", "isolated", "fallback", "cached"]


class HarnessGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HarnessNodeSpec(HarnessGraphModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    node_kind: HarnessNodeKind = "plugin"
    handler_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,159}$")
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    required_inputs: list[str] = Field(default_factory=list, max_length=64)
    output_key: str | None = Field(default=None, max_length=120)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    retry_limit: int = Field(default=0, ge=0, le=5)
    failure_mode: HarnessNodeFailureMode = "fail-closed"
    fallback_handler_id: str | None = Field(default=None, max_length=160)
    cacheable: bool = False
    authority: Literal["read", "plan", "simulate"] = "plan"

    @model_validator(mode="after")
    def validate_fallback(self) -> HarnessNodeSpec:
        if self.failure_mode == "fallback" and not self.fallback_handler_id:
            raise ValueError("fallback nodes require fallback_handler_id")
        if self.node_kind in {"core", "barrier"} and self.failure_mode != "fail-closed":
            raise ValueError("core and barrier nodes must fail closed")
        return self


class HarnessTopology(HarnessGraphModel):
    schema_version: Literal["dronedream.harness-topology.v1"] = "dronedream.harness-topology.v1"
    topology_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    name: str = Field(min_length=1, max_length=120)
    nodes: list[HarnessNodeSpec] = Field(min_length=1, max_length=256)
    maximum_parallelism: int = Field(default=4, ge=1, le=16)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> HarnessTopology:
        identifiers = [item.node_id for item in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate Harness node id")
        known = set(identifiers)
        for item in self.nodes:
            unknown = set(item.depends_on) - known
            if unknown:
                raise ValueError(
                    f"Harness node {item.node_id} has unknown dependencies: {sorted(unknown)}"
                )
            if item.node_id in item.depends_on:
                raise ValueError(f"Harness node {item.node_id} depends on itself")
        _topological_layers(self.nodes)
        return self


class HarnessBudget(HarnessGraphModel):
    maximum_nodes: int = Field(default=128, ge=1, le=512)
    maximum_elapsed_seconds: float = Field(default=600.0, gt=0.0, le=7200.0)
    maximum_retries: int = Field(default=32, ge=0, le=256)
    maximum_parallelism: int = Field(default=4, ge=1, le=16)


class HarnessRuntimePolicy(HarnessGraphModel):
    """Core-validated projection of selected Harness policy plugins."""

    topology: HarnessTopology
    budget: HarnessBudget
    maximum_model_calls: int = Field(ge=8, le=256)
    maximum_tool_calls: int = Field(ge=0, le=64)
    provider_attempts: int = Field(ge=1, le=5)
    model_timeout_seconds: float = Field(gt=0.0, le=600.0)
    tool_timeout_seconds: float = Field(gt=0.0, le=300.0)
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def resolve_harness_runtime_policy(
    topology: HarnessTopology,
    policies: Mapping[str, Mapping[str, object]],
    *,
    maximum_model_calls: int,
    maximum_tool_calls: int,
    model_timeout_seconds: float,
) -> HarnessRuntimePolicy:
    """Apply plugin policy values without allowing them to exceed core ceilings."""

    required = {"scheduler", "retry", "timeout", "budget", "fallback", "cache"}
    if set(policies) != required:
        raise ValueError("HARNESS_POLICY_SET_INCOMPLETE")
    scheduler = policies["scheduler"]
    retry = policies["retry"]
    timeout = policies["timeout"]
    budget_value = policies["budget"]
    fallback = policies["fallback"]
    cache = policies["cache"]
    strategy = str(scheduler.get("strategy", ""))
    if strategy not in {"parallel-ready", "sequential"}:
        raise ValueError("HARNESS_SCHEDULER_POLICY_INVALID")
    parallelism = (
        1
        if strategy == "sequential"
        else int(scheduler.get("maximum_parallelism", topology.maximum_parallelism))
    )
    parallelism = max(1, min(16, topology.maximum_parallelism, parallelism))
    local_timeout = max(0.1, min(600.0, float(timeout.get("local_stage_seconds", 30.0))))
    retry_cap = max(0, min(256, int(retry.get("maximum_retries", 0))))
    cache_read_only = cache.get("cache_read_only") is True
    optional_failure = str(fallback.get("optional_failure", "stop"))
    if optional_failure not in {"stop", "isolate"}:
        raise ValueError("HARNESS_FALLBACK_POLICY_INVALID")
    nodes: list[HarnessNodeSpec] = []
    for node in topology.nodes:
        nodes.append(
            node.model_copy(
                update={
                    "timeout_seconds": min(node.timeout_seconds, local_timeout),
                    "retry_limit": min(node.retry_limit, retry_cap, 5),
                    "failure_mode": node.failure_mode,
                    "cacheable": bool(
                        node.cacheable
                        and cache_read_only
                        and node.node_kind == "plugin"
                        and node.authority == "read"
                    ),
                }
            )
        )
    resolved_topology = topology.model_copy(
        update={
            "nodes": nodes,
            "maximum_parallelism": parallelism,
            "metadata": {
                **topology.metadata,
                "scheduler_strategy": strategy,
            },
        }
    )
    resolved_budget = HarnessBudget(
        maximum_nodes=max(1, min(512, int(budget_value.get("maximum_nodes", 128)))),
        maximum_elapsed_seconds=max(
            1.0,
            min(7200.0, float(timeout.get("mission_seconds", 600.0))),
        ),
        maximum_retries=min(
            retry_cap,
            max(0, min(256, int(budget_value.get("maximum_retries", retry_cap)))),
        ),
        maximum_parallelism=min(
            parallelism,
            max(1, min(16, int(budget_value.get("maximum_parallelism", parallelism)))),
        ),
    )
    if len(resolved_topology.nodes) > resolved_budget.maximum_nodes:
        raise ValueError("HARNESS_NODE_BUDGET_EXCEEDED")
    projected = {
        "topology": resolved_topology.model_dump(mode="json"),
        "budget": resolved_budget.model_dump(mode="json"),
        "maximum_model_calls": min(
            maximum_model_calls,
            max(8, int(budget_value.get("maximum_model_calls", maximum_model_calls))),
        ),
        "maximum_tool_calls": min(
            maximum_tool_calls,
            max(0, int(budget_value.get("maximum_tool_calls", maximum_tool_calls))),
        ),
        "provider_attempts": max(1, min(5, int(retry.get("provider_attempts", 1)))),
        "model_timeout_seconds": min(
            model_timeout_seconds,
            max(1.0, float(timeout.get("model_seconds", model_timeout_seconds))),
        ),
        "tool_timeout_seconds": max(
            0.1,
            min(300.0, float(timeout.get("tool_seconds", 60.0))),
        ),
    }
    return HarnessRuntimePolicy(
        **projected,
        policy_sha256=sha256_json({"selected": policies, "projected": projected}),
    )


class HarnessNodeReceipt(HarnessGraphModel):
    invocation_id: str
    topology_id: str
    node_id: str
    handler_id: str
    state: HarnessNodeState
    attempt_count: int = Field(ge=1, le=6)
    elapsed_ms: int = Field(ge=0)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    created_at: datetime


class HarnessGraphResult(HarnessGraphModel):
    run_id: str
    topology_id: str
    outputs: dict[str, Any]
    receipts: list[HarnessNodeReceipt]
    elapsed_ms: int = Field(ge=0)
    created_at: datetime


class HarnessStageReceipt(HarnessGraphModel):
    topology_id: str
    node_id: str
    node_kind: HarnessNodeKind
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime


class HarnessGraphError(RuntimeError):
    """A bounded graph run could not safely complete."""

    def __init__(self, code: str, receipts: list[HarnessNodeReceipt] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.receipts = receipts or []


class HarnessStageRuntime:
    """Enforce a selected topology around protected mission-stage implementations."""

    def __init__(self, topology: HarnessTopology) -> None:
        self.topology = topology
        self._nodes = {item.node_id: item for item in topology.nodes}
        self._completed: dict[str, HarnessStageReceipt] = {}

    def contains(self, node_id: str) -> bool:
        return node_id in self._nodes

    def complete(self, node_id: str, *, inputs: Any, output: Any) -> HarnessStageReceipt:
        node = self._nodes.get(node_id)
        if node is None:
            raise HarnessGraphError(f"HARNESS_STAGE_NOT_IN_TOPOLOGY:{node_id}")
        if node_id in self._completed:
            raise HarnessGraphError(f"HARNESS_STAGE_ALREADY_COMPLETED:{node_id}")
        if not isinstance(inputs, Mapping):
            raise HarnessGraphError(f"HARNESS_STAGE_INPUT_INVALID:{node_id}")
        missing_inputs = [item for item in node.required_inputs if item not in inputs]
        if missing_inputs:
            raise HarnessGraphError(
                f"HARNESS_STAGE_REQUIRED_INPUT_MISSING:{node_id}:" + ",".join(missing_inputs)
            )
        missing = [item for item in node.depends_on if item not in self._completed]
        if missing:
            raise HarnessGraphError(
                f"HARNESS_STAGE_DEPENDENCY_INCOMPLETE:{node_id}:{','.join(missing)}"
            )
        receipt = HarnessStageReceipt(
            topology_id=self.topology.topology_id,
            node_id=node_id,
            node_kind=node.node_kind,
            input_sha256=sha256_json(inputs),
            output_sha256=sha256_json(output),
            completed_at=datetime.now(UTC),
        )
        self._completed[node_id] = receipt
        return receipt

    def finish(self) -> list[HarnessStageReceipt]:
        missing = sorted(set(self._nodes) - set(self._completed))
        if missing:
            raise HarnessGraphError(f"HARNESS_TOPOLOGY_INCOMPLETE:{','.join(missing)}")
        return [
            self._completed[item.node_id]
            for layer in _topological_layers(self.topology.nodes)
            for item in layer
        ]


HarnessHandler = Callable[[dict[str, Any]], Any]
HarnessObserver = Callable[[str, Mapping[str, Any]], None]


@dataclass
class HarnessCircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    _failures: dict[str, int] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, handler_id: str) -> bool:
        with self._lock:
            opened = self._opened_at.get(handler_id)
            if opened is None:
                return True
            if time.monotonic() - opened >= self.recovery_seconds:
                self._opened_at.pop(handler_id, None)
                self._failures[handler_id] = 0
                return True
            return False

    def success(self, handler_id: str) -> None:
        with self._lock:
            self._failures[handler_id] = 0
            self._opened_at.pop(handler_id, None)

    def failure(self, handler_id: str) -> None:
        with self._lock:
            failures = self._failures.get(handler_id, 0) + 1
            self._failures[handler_id] = failures
            if failures >= self.failure_threshold:
                self._opened_at[handler_id] = time.monotonic()


def _topological_layers(nodes: list[HarnessNodeSpec]) -> list[list[HarnessNodeSpec]]:
    by_id = {item.node_id: item for item in nodes}
    indegree = {item.node_id: len(set(item.depends_on)) for item in nodes}
    successors: dict[str, set[str]] = defaultdict(set)
    for item in nodes:
        for dependency in set(item.depends_on):
            successors[dependency].add(item.node_id)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    layers: list[list[HarnessNodeSpec]] = []
    visited = 0
    while ready:
        current_ids = ready
        ready = []
        layer = [by_id[node_id] for node_id in current_ids]
        layers.append(layer)
        visited += len(layer)
        for node_id in current_ids:
            for successor in sorted(successors[node_id]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        ready.sort()
    if visited != len(nodes):
        raise ValueError("Harness topology contains a dependency cycle")
    return layers


class HarnessGraphExecutor:
    """Execute typed Harness nodes with budgets, isolation, fallback, and receipts."""

    def __init__(
        self,
        *,
        handlers: Mapping[str, HarnessHandler],
        fallback_handlers: Mapping[str, HarnessHandler] | None = None,
        budget: HarnessBudget | None = None,
        observers: list[HarnessObserver] | None = None,
        circuit_breaker: HarnessCircuitBreaker | None = None,
    ) -> None:
        self.handlers = dict(handlers)
        self.fallback_handlers = dict(fallback_handlers or {})
        self.budget = budget or HarnessBudget()
        self.observers = list(observers or [])
        self.circuit_breaker = circuit_breaker or HarnessCircuitBreaker()
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    def run(self, topology: HarnessTopology, inputs: dict[str, Any]) -> HarnessGraphResult:
        if len(topology.nodes) > self.budget.maximum_nodes:
            raise HarnessGraphError("HARNESS_NODE_BUDGET_EXCEEDED")
        started = time.monotonic()
        outputs = dict(inputs)
        receipts: list[HarnessNodeReceipt] = []
        retry_count = 0
        layers = _topological_layers(topology.nodes)
        parallelism = min(
            topology.maximum_parallelism,
            self.budget.maximum_parallelism,
        )
        for layer in layers:
            self._check_elapsed(started, receipts)
            with ThreadPoolExecutor(max_workers=min(parallelism, len(layer))) as pool:
                futures = {
                    node.node_id: pool.submit(self._run_node, topology, node, dict(outputs))
                    for node in layer
                }
                layer_results: dict[str, tuple[str | None, Any, HarnessNodeReceipt]] = {}
                for node in layer:
                    try:
                        result = futures[node.node_id].result(
                            timeout=node.timeout_seconds * (node.retry_limit + 1) + 0.25
                        )
                    except FutureTimeoutError as error:
                        raise HarnessGraphError(
                            f"HARNESS_NODE_TIMEOUT:{node.node_id}", receipts
                        ) from error
                    layer_results[node.node_id] = result
            for node in sorted(layer, key=lambda value: value.node_id):
                output_key, value, receipt = layer_results[node.node_id]
                receipts.append(receipt)
                retry_count += receipt.attempt_count - 1
                if retry_count > self.budget.maximum_retries:
                    raise HarnessGraphError("HARNESS_RETRY_BUDGET_EXCEEDED", receipts)
                if output_key is not None and receipt.state not in {"failed", "isolated"}:
                    outputs[output_key] = value
                if receipt.state == "failed":
                    raise HarnessGraphError(
                        receipt.issue_codes[0] if receipt.issue_codes else "HARNESS_NODE_FAILED",
                        receipts,
                    )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        result = HarnessGraphResult(
            run_id=f"harness-run-{uuid4().hex[:24]}",
            topology_id=topology.topology_id,
            outputs=outputs,
            receipts=receipts,
            elapsed_ms=elapsed_ms,
            created_at=datetime.now(UTC),
        )
        self._notify("graph.completed", result.model_dump(mode="json"))
        return result

    def _run_node(
        self,
        topology: HarnessTopology,
        node: HarnessNodeSpec,
        outputs: dict[str, Any],
    ) -> tuple[str | None, Any, HarnessNodeReceipt]:
        missing = [key for key in node.required_inputs if key not in outputs]
        if missing:
            receipt = self._receipt(
                topology,
                node,
                state="failed",
                attempts=1,
                started=time.monotonic(),
                inputs=outputs,
                output={},
                issues=[f"HARNESS_REQUIRED_INPUT_MISSING:{','.join(missing)}"],
            )
            return node.output_key, None, receipt
        handler = self.handlers.get(node.handler_id)
        if handler is None:
            receipt = self._receipt(
                topology,
                node,
                state="failed",
                attempts=1,
                started=time.monotonic(),
                inputs=outputs,
                output={},
                issues=[f"HARNESS_HANDLER_MISSING:{node.handler_id}"],
            )
            return node.output_key, None, receipt
        if not self.circuit_breaker.allow(node.handler_id):
            receipt = self._receipt(
                topology,
                node,
                state="failed",
                attempts=1,
                started=time.monotonic(),
                inputs=outputs,
                output={},
                issues=[f"HARNESS_CIRCUIT_OPEN:{node.handler_id}"],
            )
            return node.output_key, None, receipt
        cache_key = sha256_json(
            {
                "topology_id": topology.topology_id,
                "node_id": node.node_id,
                "handler_id": node.handler_id,
                "inputs": outputs,
            }
        )
        if node.cacheable:
            with self._cache_lock:
                if cache_key in self._cache:
                    cached = self._cache[cache_key]
                    receipt = self._receipt(
                        topology,
                        node,
                        state="cached",
                        attempts=1,
                        started=time.monotonic(),
                        inputs=outputs,
                        output=cached,
                    )
                    return node.output_key, cached, receipt
        started = time.monotonic()
        self._notify(
            "node.started",
            {"topology_id": topology.topology_id, "node_id": node.node_id},
        )
        last_error: BaseException | None = None
        attempts = 0
        value: Any = None
        for attempt in range(1, node.retry_limit + 2):
            attempts = attempt
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    value = pool.submit(handler, dict(outputs)).result(timeout=node.timeout_seconds)
                self.circuit_breaker.success(node.handler_id)
                if node.cacheable:
                    with self._cache_lock:
                        self._cache[cache_key] = value
                receipt = self._receipt(
                    topology,
                    node,
                    state="accepted",
                    attempts=attempts,
                    started=started,
                    inputs=outputs,
                    output=value,
                )
                self._notify("node.completed", receipt.model_dump(mode="json"))
                return node.output_key, value, receipt
            except FutureTimeoutError as error:
                last_error = error
            except Exception as error:  # plugin boundary deliberately catches third-party errors
                last_error = error
        self.circuit_breaker.failure(node.handler_id)
        issue = f"HARNESS_NODE_FAILED:{type(last_error).__name__}"
        if node.failure_mode == "fallback" and node.fallback_handler_id:
            fallback = self.fallback_handlers.get(node.fallback_handler_id)
            if fallback is not None:
                try:
                    value = fallback(dict(outputs))
                    receipt = self._receipt(
                        topology,
                        node,
                        state="fallback",
                        attempts=attempts,
                        started=started,
                        inputs=outputs,
                        output=value,
                        issues=[issue],
                    )
                    self._notify("node.fallback", receipt.model_dump(mode="json"))
                    return node.output_key, value, receipt
                except Exception as error:  # noqa: PERF203 - explicit boundary evidence
                    issue = f"HARNESS_FALLBACK_FAILED:{type(error).__name__}"
        state: HarnessNodeState = "isolated" if node.failure_mode == "isolate" else "failed"
        receipt = self._receipt(
            topology,
            node,
            state=state,
            attempts=attempts,
            started=started,
            inputs=outputs,
            output={},
            issues=[issue],
        )
        self._notify("node.failed", receipt.model_dump(mode="json"))
        return node.output_key, None, receipt

    def _check_elapsed(self, started: float, receipts: list[HarnessNodeReceipt]) -> None:
        if time.monotonic() - started > self.budget.maximum_elapsed_seconds:
            raise HarnessGraphError("HARNESS_ELAPSED_BUDGET_EXCEEDED", receipts)

    def _notify(self, event: str, payload: Mapping[str, Any]) -> None:
        for observer in self.observers:
            try:
                observer(event, payload)
            except Exception:
                continue

    @staticmethod
    def _receipt(
        topology: HarnessTopology,
        node: HarnessNodeSpec,
        *,
        state: HarnessNodeState,
        attempts: int,
        started: float,
        inputs: Any,
        output: Any,
        issues: list[str] | None = None,
    ) -> HarnessNodeReceipt:
        return HarnessNodeReceipt(
            invocation_id=f"harness-node-{uuid4().hex[:24]}",
            topology_id=topology.topology_id,
            node_id=node.node_id,
            handler_id=node.handler_id,
            state=state,
            attempt_count=attempts,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            input_sha256=sha256_json(inputs),
            output_sha256=sha256_json(output),
            issue_codes=issues or [],
            created_at=datetime.now(UTC),
        )
