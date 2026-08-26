from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


def git_bytes(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json_lf(path: Path, value: object) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise TypeError(f"cannot traverse {pointer} through {type(current).__name__}")
    return current


def phase_role_counts(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    tool_roles: dict[str, str] = {}
    phase_roles: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id == "HARNESS_TOOL_DEFINITIONS" and isinstance(node.value, ast.Dict):
            for key, definition in zip(node.value.keys, node.value.values, strict=True):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not isinstance(definition, ast.Call):
                    continue
                role = next(
                    (
                        keyword.value.value
                        for keyword in definition.keywords
                        if keyword.arg == "search_role"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ),
                    None,
                )
                if role is not None:
                    tool_roles[key.value] = role
        if node.target.id == "_PHASE_COMPATIBLE_SEARCH_ROLES" and isinstance(node.value, ast.Dict):
            for key, role_call in zip(node.value.keys, node.value.values, strict=True):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not isinstance(role_call, ast.Call) or not role_call.args:
                    continue
                role_set = role_call.args[0]
                if not isinstance(role_set, ast.Set):
                    continue
                phase_roles[key.value] = {
                    item.value
                    for item in role_set.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
    if len(tool_roles) != 8 or len(phase_roles) != 6:
        raise ValueError(
            "unable to derive the complete frozen tool/phase registry "
            f"(tools={len(tool_roles)}, phases={len(phase_roles)})"
        )
    return {
        phase: sum(role in compatible for role in tool_roles.values())
        for phase, compatible in phase_roles.items()
    }


def source_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = [
        *manifest["software"]["artifacts"],
        *manifest["software"].get("source_references", []),
        *manifest["website"]["artifacts"],
    ]
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        source_id = str(entry["id"])
        if source_id in by_id:
            raise ValueError(f"duplicate evidence source id: {source_id}")
        by_id[source_id] = entry
    return by_id


def verify_latex_row(body: str, label: str, tokens: list[object]) -> None:
    normalized_body = normalize_space(body)
    normalized_label = normalize_space(label)
    normalized_tokens = [normalize_space(str(token)) for token in tokens]
    search_from = 0
    inspected_rows: list[str] = []
    while True:
        start = normalized_body.find(normalized_label, search_from)
        if start < 0:
            break
        end = normalized_body.find(r"\tabularnewline", start)
        if end >= 0 and end - start <= 2000:
            row = normalized_body[start:end]
            inspected_rows.append(row)
            cursor = 0
            for token in normalized_tokens:
                position = row.find(token, cursor)
                if position < 0:
                    break
                cursor = position + len(token)
            else:
                return
        search_from = start + len(normalized_label)
    raise ValueError(
        f"LaTeX row {label!r} lacks ordered tokens {normalized_tokens!r}; "
        f"candidate rows={inspected_rows!r}"
    )


def block_arm_summary(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for block in blocks:
        for arm in block["arms"]:
            arm_name = str(arm["arm"])
            summary = summaries.setdefault(
                arm_name,
                {
                    "runs": 0,
                    "trials": 0,
                    "tool_sequences": set(),
                },
            )
            summary["runs"] += 1
            summary["trials"] += int(json_pointer(arm, "/outcome/budget/trial_count"))
            summary["tool_sequences"].add(
                tuple(str(tool_id) for tool_id in arm.get("tool_sequence", []))
            )
    return summaries


def verify_assertion(
    assertion: dict[str, Any],
    parsed: Any,
    text: str,
    body: str,
    phase_counts: dict[str, int] | None,
    related_sources: dict[str, dict[str, Any]],
) -> None:
    kind = assertion["kind"]
    if kind == "json_equals":
        actual = json_pointer(parsed, assertion["pointer"])
        if actual != assertion["expected"]:
            raise ValueError(
                f"{assertion['pointer']} expected {assertion['expected']!r}, found {actual!r}"
            )
        return
    if kind == "json_approx":
        actual = float(json_pointer(parsed, assertion["pointer"]))
        expected = float(assertion["expected"])
        tolerance = float(assertion["tolerance"])
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            raise ValueError(
                f"{assertion['pointer']} expected {expected} +/- {tolerance}, found {actual}"
            )
        return
    if kind == "json_product_approx":
        values = [float(json_pointer(parsed, pointer)) for pointer in assertion["pointers"]]
        actual = math.prod(values)
        expected = float(assertion["expected"])
        tolerance = float(assertion["tolerance"])
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            raise ValueError(
                f"product {assertion['pointers']} expected {expected} +/- "
                f"{tolerance}, found {actual}"
            )
        return
    if kind == "json_sum_field":
        rows = json_pointer(parsed, assertion["pointer"])
        actual = sum(row[assertion["field"]] for row in rows)
        if actual != assertion["expected"]:
            raise ValueError(
                f"sum {assertion['pointer']}[*].{assertion['field']} expected "
                f"{assertion['expected']!r}, found {actual!r}"
            )
        return
    if kind == "json_len":
        value = json_pointer(parsed, assertion["pointer"])
        actual = len(value)
        if actual != assertion["expected"]:
            raise ValueError(
                f"len({assertion['pointer']}) expected "
                f"{assertion['expected']!r}, found {actual!r}"
            )
        return
    if kind == "routing_prediction_grade":
        corpus_source_id = str(assertion["corpus_source_id"])
        corpus_source = related_sources.get(corpus_source_id)
        if corpus_source is None:
            raise ValueError(
                f"routing grade lacks related corpus source {corpus_source_id!r}"
            )
        corpus_rows = [
            json.loads(line)
            for line in corpus_source["text"].splitlines()
            if line.strip()
        ]
        predictions = json_pointer(parsed, assertion["predictions_pointer"])
        if not isinstance(predictions, dict):
            raise ValueError("routing predictions must be a case-id object")
        expected_case_ids = {str(row["case_id"]) for row in corpus_rows}
        actual_case_ids = {str(case_id) for case_id in predictions}
        if actual_case_ids != expected_case_ids:
            raise ValueError(
                "routing prediction case ids drifted: "
                f"missing={sorted(expected_case_ids - actual_case_ids)}, "
                f"extra={sorted(actual_case_ids - expected_case_ids)}"
            )
        failures: list[str] = []
        for row in corpus_rows:
            case_id = str(row["case_id"])
            selected = str(predictions[case_id]["selected_tool"])
            acceptable = {str(tool_id) for tool_id in row["acceptable_tools"]}
            if selected not in acceptable:
                failures.append(case_id)
        passed = len(corpus_rows) - len(failures)
        if len(corpus_rows) != assertion["expected_cases"]:
            raise ValueError(
                f"routing case count expected {assertion['expected_cases']}, "
                f"found {len(corpus_rows)}"
            )
        if passed != assertion["expected_passed"]:
            raise ValueError(
                f"routing pass count expected {assertion['expected_passed']}, "
                f"found {passed}"
            )
        expected_failures = sorted(
            str(case_id) for case_id in assertion["expected_failed_case_ids"]
        )
        if sorted(failures) != expected_failures:
            raise ValueError(
                f"routing failures expected {expected_failures}, "
                f"found {sorted(failures)}"
            )
        return
    if kind == "text_contains":
        expected = str(assertion["expected"])
        if expected not in text:
            raise ValueError(f"source text lacks {expected!r}")
        return
    if kind == "phase_role_count":
        if phase_counts is None:
            raise ValueError("phase-role assertion requires a Python source")
        phase = str(assertion["phase"])
        actual = phase_counts.get(phase)
        if actual != assertion["expected"]:
            raise ValueError(
                f"phase {phase!r} expected {assertion['expected']} roles, found {actual!r}"
            )
        return
    if kind == "latex_scenario_table":
        rows = json_pointer(parsed, assertion["pointer"])
        if len(rows) != assertion["expected_rows"]:
            raise ValueError(
                f"scenario row count expected {assertion['expected_rows']}, found {len(rows)}"
            )
        missing: list[str] = []
        for row in rows:
            scenario = str(row["scenario"]).replace("_", " ")
            expected_line = (
                f"{scenario} & {float(row['baseline_holdout_loss']):.4f} & "
                f"{float(row['selected_holdout_loss']):.4f} & "
                f"{float(row['relative_improvement_rate']) * 100:.2f}\\%"
            )
            if expected_line not in body:
                missing.append(expected_line)
        if missing:
            raise ValueError(f"LaTeX scenario rows drifted: {missing}")
        return
    if kind == "latex_ablation_rows":
        rows = json_pointer(parsed, assertion["pointer"])
        if len(rows) != assertion["expected_rows"]:
            raise ValueError(
                f"ablation row count expected {assertion['expected_rows']}, "
                f"found {len(rows)}"
            )
        row_labels = assertion["row_labels"]
        components = {str(row["component"]) for row in rows}
        if components != set(row_labels):
            raise ValueError(
                f"ablation components expected {sorted(row_labels)}, "
                f"found {sorted(components)}"
            )
        for row in rows:
            component = str(row["component"])
            probe_count = int(row["probe_count"])
            full_count = int(row["full_contract_correct_count"])
            ablated_count = int(row["ablated_contract_correct_count"])
            verify_latex_row(
                body,
                row_labels[component],
                [
                    probe_count,
                    f"{full_count}/{probe_count}",
                    f"{ablated_count}/{probe_count}",
                ],
            )
        return
    if kind == "latex_fallback_arm_rows":
        blocks = json_pointer(parsed, assertion["blocks_pointer"])
        comparisons = json_pointer(parsed, assertion["comparisons_pointer"])
        summaries = block_arm_summary(blocks)
        arms = assertion["arms"]
        if set(summaries) != set(arms):
            raise ValueError(
                f"fallback arms expected {sorted(arms)}, found {sorted(summaries)}"
            )
        for arm_name, expected in arms.items():
            summary = summaries[arm_name]
            if summary["runs"] != len(blocks):
                raise ValueError(
                    f"fallback arm {arm_name!r} has {summary['runs']} runs "
                    f"across {len(blocks)} blocks"
                )
            if arm_name == "direct_portfolio":
                finding = str(expected["finding"])
            else:
                arm_comparisons = [
                    row for row in comparisons if row["comparison_arm"] == arm_name
                ]
                exact_count = sum(
                    bool(row["exact_outcome_match"]) for row in arm_comparisons
                )
                if len(arm_comparisons) != summary["runs"]:
                    raise ValueError(
                        f"fallback arm {arm_name!r} has {len(arm_comparisons)} "
                        f"comparisons for {summary['runs']} runs"
                    )
                finding = f"{exact_count}/{summary['runs']} exact"
            verify_latex_row(
                body,
                expected["label"],
                [summary["runs"], summary["trials"], finding],
            )
        return
    if kind == "latex_component_arm_rows":
        blocks = json_pointer(parsed, assertion["blocks_pointer"])
        comparisons = json_pointer(parsed, assertion["comparisons_pointer"])
        isolations = json_pointer(parsed, assertion["isolation_pointer"])
        summaries = block_arm_summary(blocks)
        arms = assertion["arms"]
        if set(summaries) != set(arms):
            raise ValueError(
                f"component arms expected {sorted(arms)}, found {sorted(summaries)}"
            )
        for arm_name, expected in arms.items():
            summary = summaries[arm_name]
            expected_sequence = tuple(str(item) for item in expected["tool_sequence"])
            if summary["runs"] != len(blocks):
                raise ValueError(
                    f"component arm {arm_name!r} has {summary['runs']} runs "
                    f"across {len(blocks)} blocks"
                )
            if summary["tool_sequences"] != {expected_sequence}:
                raise ValueError(
                    f"component arm {arm_name!r} expected tool sequence "
                    f"{expected_sequence!r}, found {summary['tool_sequences']!r}"
                )
            expected_status = expected.get("result_status")
            if expected_status is not None:
                arm_comparisons = [
                    row for row in comparisons if row["comparison_arm"] == arm_name
                ]
                statuses = [str(row["result_status"]) for row in arm_comparisons]
                if len(statuses) != summary["runs"] or set(statuses) != {
                    expected_status
                }:
                    raise ValueError(
                        f"component arm {arm_name!r} expected {summary['runs']} "
                        f"{expected_status!r} comparisons, found {statuses!r}"
                    )
            verify_latex_row(
                body,
                expected["label"],
                [
                    summary["runs"],
                    summary["trials"],
                    expected["display_sequence"],
                    expected["finding"],
                ],
            )
        isolation = assertion["isolation"]
        verify_latex_row(
            body,
            isolation["label"],
            [
                f"{len(isolations)} pairs",
                "---",
                isolation["display_sequence"],
                isolation["finding"],
            ],
        )
        return
    raise ValueError(f"unsupported assertion kind: {kind}")


def verified_source(
    repo: Path,
    source_id: str,
    available_sources: dict[str, dict[str, Any]],
    source_cache: dict[str, dict[str, Any]],
    source_results: list[dict[str, Any]],
) -> dict[str, Any]:
    cached = source_cache.get(source_id)
    if cached is not None:
        return cached
    entry = available_sources.get(source_id)
    if entry is None:
        raise ValueError(f"unknown source id: {source_id}")
    payload = git_bytes(
        repo,
        "show",
        f"{entry['ref_commit']}:{entry['path']}",
    )
    actual_sha256 = sha256_bytes(payload)
    if actual_sha256 != entry["file_sha256"]:
        raise ValueError(
            f"source SHA-256 expected {entry['file_sha256']}, found {actual_sha256}"
        )
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = payload.decode("utf-16")
    else:
        text = payload.decode("utf-8")
    parsed: Any = None
    if str(entry["path"]).endswith(".json"):
        parsed = json.loads(text)
    phase_counts = (
        phase_role_counts(text) if source_id == "harness_phase_registry" else None
    )
    source = {
        "payload": payload,
        "text": text,
        "parsed": parsed,
        "phase_counts": phase_counts,
    }
    source_cache[source_id] = source
    source_results.append(
        {
            "id": source_id,
            "ref_commit": entry["ref_commit"],
            "path": entry["path"],
            "sha256": actual_sha256,
        }
    )
    return source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repository.resolve()
    ledger_bytes = args.ledger.read_bytes()
    manifest_bytes = args.manifest.read_bytes()
    body_bytes = args.body.read_bytes()
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    body = body_bytes.decode("utf-8")
    normalized_body = normalize_space(body)
    if ledger.get("schema_version") != "dronedream.technical-report-claim-evidence-ledger.v1":
        raise ValueError("unexpected claim-evidence ledger schema")
    if PurePosixPath(ledger["report_source"]).as_posix() != "technical-report/body.tex":
        raise ValueError("claim ledger report source is not technical-report/body.tex")
    if (
        PurePosixPath(ledger["evidence_reference_manifest"]).as_posix()
        != "technical-report/evidence-reference-manifest.json"
    ):
        raise ValueError("claim ledger evidence manifest path is invalid")
    if manifest.get("ownership", {}).get("raw_evidence_copied") is not False:
        raise ValueError("evidence manifest must preserve raw_evidence_copied=false")

    available_sources = source_entries(manifest)
    source_cache: dict[str, dict[str, Any]] = {}
    source_results: list[dict[str, Any]] = []
    claim_results: list[dict[str, Any]] = []
    failures: list[str] = []
    assertion_total = 0

    for claim in ledger["claims"]:
        claim_id = str(claim["id"])
        source_id = str(claim["source_id"])
        claim_failures: list[str] = []
        entry = available_sources.get(source_id)
        if entry is None:
            claim_failures.append(f"unknown source id: {source_id}")
        else:
            try:
                source = verified_source(
                    repo,
                    source_id,
                    available_sources,
                    source_cache,
                    source_results,
                )
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                subprocess.CalledProcessError,
                ValueError,
            ) as exc:
                source = None
                claim_failures.append(f"source verification failed: {exc}")
            if source is not None:
                for assertion_index, assertion in enumerate(claim["assertions"], 1):
                    assertion_total += 1
                    try:
                        related_sources = {
                            related_source_id: verified_source(
                                repo,
                                related_source_id,
                                available_sources,
                                source_cache,
                                source_results,
                            )
                            for related_source_id in assertion.get(
                                "related_source_ids", []
                            )
                        }
                        verify_assertion(
                            assertion,
                            source["parsed"],
                            source["text"],
                            body,
                            source["phase_counts"],
                            related_sources,
                        )
                    except (
                        KeyError,
                        IndexError,
                        OSError,
                        TypeError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        subprocess.CalledProcessError,
                        ValueError,
                    ) as exc:
                        claim_failures.append(
                            f"assertion {assertion_index} ({assertion['kind']}): {exc}"
                        )
        for literal in claim.get("body_contains", []):
            if normalize_space(literal) not in normalized_body:
                claim_failures.append(f"report source lacks {literal!r}")
        if claim_failures:
            failures.extend(f"{claim_id}: {failure}" for failure in claim_failures)
        claim_results.append(
            {
                "id": claim_id,
                "report_locations": claim["report_locations"],
                "source_id": source_id,
                "assertions": len(claim["assertions"]),
                "body_literals": len(claim.get("body_contains", [])),
                "status": "failed" if claim_failures else "passed",
                "failures": claim_failures,
            }
        )

    claim_ids = [result["id"] for result in claim_results]
    if len(claim_ids) != len(set(claim_ids)):
        failures.append("claim ids are not unique")
    prohibited_literals = ledger.get("prohibited_report_literals", [])
    for entry in prohibited_literals:
        literal = str(entry["literal"])
        if normalize_space(literal) in normalized_body:
            failures.append(
                f"prohibited report literal present: {literal!r} ({entry['reason']})"
            )
    result = {
        "schema_version": "dronedream.technical-report-claim-evidence-audit.v1",
        "status": "failed" if failures else "passed",
        "ledger": {
            "path": "technical-report/claim-evidence-ledger.json",
            "sha256": sha256_bytes(ledger_bytes),
        },
        "evidence_reference_manifest": {
            "path": "technical-report/evidence-reference-manifest.json",
            "sha256": sha256_bytes(manifest_bytes),
        },
        "report_source": {
            "path": "technical-report/body.tex",
            "sha256": sha256_bytes(body_bytes),
        },
        "claim_total": len(claim_results),
        "claim_passed": sum(result["status"] == "passed" for result in claim_results),
        "claim_failed": sum(result["status"] == "failed" for result in claim_results),
        "assertion_total": assertion_total,
        "prohibited_literal_checks": len(prohibited_literals),
        "verified_sources": sorted(source_results, key=lambda item: item["id"]),
        "claims": claim_results,
        "failures": failures,
    }
    write_json_lf(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "claims": result["claim_total"],
                "passed": result["claim_passed"],
                "failed": result["claim_failed"],
                "assertions": result["assertion_total"],
                "verified_sources": len(result["verified_sources"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
