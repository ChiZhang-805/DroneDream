from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
CAPABILITY_POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
GATE_POLICY_PATH = DISTRIBUTION / "safety" / "edition-execution-gate.v1.json"
AUTHORIZATION_SCHEMA_PATH = (
    DISTRIBUTION / "schemas" / "edition-execution-authorization.schema.json"
)
GATE_SCHEMA_PATH = DISTRIBUTION / "schemas" / "edition-execution-gate-policy.schema.json"
FIXTURE_PATH = DISTRIBUTION / "tests" / "fixtures" / "edition-safety-cases.v1.json"
LAB_MANIFEST_PATH = DISTRIBUTION / "editions" / "lab.v1.json"

SPEC = importlib.util.spec_from_file_location(
    "edition_safety_contract_tests",
    DISTRIBUTION / "tools" / "edition_safety_contract.py",
)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


class EditionSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capability_sha256 = contract.sha256_file(CAPABILITY_POLICY_PATH)
        cls.gate_sha256 = contract.sha256_file(GATE_POLICY_PATH)
        cls.policy = contract.validate_gate_policy(
            contract.load_json(GATE_POLICY_PATH),
            capability_policy_sha256=cls.capability_sha256,
        )
        cls.fixture = contract.load_json(FIXTURE_PATH)

    def validate_request(self, request: dict[str, object]) -> dict[str, object]:
        return contract.validate_authorization_request(
            request,
            policy=self.policy,
            execution_gate_policy_sha256=self.gate_sha256,
            capability_policy_sha256=self.capability_sha256,
            app_env="test",
        )

    def layer_receipt(
        self,
        request: dict[str, object],
        layer: str,
        *,
        decision: str = "allow",
        reason: str = "layer.contract.allow",
    ) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schemaVersion": 1,
            "kind": "dronedream-edition-layer-decision-receipt",
            "authorizationRequestId": request["authorizationRequestId"],
            "authorizationRequestHash": contract.authorization_request_hash(request),
            "contextHash": contract.authorization_context_hash(request),
            "layer": layer,
            "decision": decision,
            "reasonCodes": [reason],
            "canonicalDecisionHash": "",
            "issuedAt": "2026-08-05T00:00:02Z",
            "expiresAt": "2026-08-05T00:04:58Z",
            "nonce": f"nonce:e5-layer-{layer}",
            "sequence": 1,
            "issuer": f"test-fixture:e5-{layer}",
            "testOnly": True,
            "consumptionState": "unconsumed",
        }
        unhashed = dict(receipt)
        unhashed.pop("canonicalDecisionHash")
        receipt["canonicalDecisionHash"] = contract.sha256_canonical(unhashed)
        return receipt

    def quorum_receipt(
        self,
        request: dict[str, object],
        layers: list[dict[str, object]],
        *,
        decision: str,
        reasons: list[str],
    ) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": "dronedream-edition-authorization-quorum-receipt",
            "authorizationRequestId": request["authorizationRequestId"],
            "authorizationRequestHash": contract.authorization_request_hash(request),
            "contextHash": contract.authorization_context_hash(request),
            "layerDecisionHashes": {
                str(receipt["layer"]): receipt["canonicalDecisionHash"]
                for receipt in layers
            },
            "decision": decision,
            "reasonCodes": reasons,
            "issuedAt": "2026-08-05T00:00:03Z",
            "expiresAt": "2026-08-05T00:04:57Z",
            "nonce": "nonce:e5-quorum-001",
            "sequence": 1,
            "oneTime": True,
            "consumptionState": "unconsumed",
            "appendOnlyAudit": True,
        }

    def test_schemas_are_closed_versioned_draft_2020_contracts(self) -> None:
        gate_schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
        auth_schema = json.loads(AUTHORIZATION_SCHEMA_PATH.read_text(encoding="utf-8"))
        for schema in (gate_schema, auth_schema):
            self.assertEqual(
                schema["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )
        self.assertFalse(gate_schema["additionalProperties"])
        for name in (
            "authorizationRequest",
            "structuredEvidenceReceipt",
            "layerDecisionReceipt",
            "quorumReceipt",
        ):
            self.assertFalse(auth_schema["$defs"][name]["additionalProperties"])

    def test_policy_freezes_three_layers_receipt_precedence_and_no_handlers(self) -> None:
        self.assertFalse(self.policy["frontendIsAuthority"])
        self.assertFalse(self.policy["hardwareActionHandlersImplemented"])
        self.assertEqual(
            self.policy["requiredDecisionLayers"],
            ["native", "backend", "runtime"],
        )
        self.assertEqual(
            self.policy["receiptPolicy"]["denyPrecedence"],
            ["failed", "deny", "indeterminate", "missing", "allow"],
        )

    def test_fixture_request_is_fully_bound_and_valid_only_in_test(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        self.assertEqual(request["policy"]["executionGatePolicySha256"], self.gate_sha256)
        self.assertEqual(
            request["evidenceReceipts"][0]["contextHash"],
            contract.authorization_context_hash(request),
        )
        self.validate_request(request)
        with self.assertRaisesRegex(
            contract.EditionSafetyContractError,
            "fake issuer is forbidden",
        ):
            contract.validate_authorization_request(
                request,
                policy=self.policy,
                execution_gate_policy_sha256=self.gate_sha256,
                capability_policy_sha256=self.capability_sha256,
                app_env="production",
            )

    def test_fixture_rebinds_to_exact_active_edition_without_mutating_source(self) -> None:
        original = deepcopy(self.fixture)
        rebound = contract.bind_test_fixture_to_edition_manifest(
            self.fixture,
            LAB_MANIFEST_PATH,
        )
        request = rebound["baseRequest"]
        self.assertEqual(self.fixture, original)
        self.assertEqual(request["editionId"], "lab")
        self.assertEqual(
            request["policy"]["editionManifestSha256"],
            contract.sha256_file(LAB_MANIFEST_PATH),
        )
        expected_context_hash = contract.authorization_context_hash(request)
        self.assertTrue(
            all(
                receipt["contextHash"] == expected_context_hash
                for receipt in request["evidenceReceipts"]
            )
        )
        self.validate_request(request)

    def test_fixture_rebind_rejects_non_test_only_input(self) -> None:
        fixture = deepcopy(self.fixture)
        fixture["baseRequest"]["testOnly"] = False
        with self.assertRaisesRegex(
            contract.EditionSafetyContractError,
            "not test-only",
        ):
            contract.bind_test_fixture_to_edition_manifest(
                fixture,
                LAB_MANIFEST_PATH,
            )

    def test_request_rejects_unknown_or_sensitive_fields(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        request["unexpected"] = True
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "fields drifted"):
            self.validate_request(request)

        request = deepcopy(self.fixture["baseRequest"])
        request["actor"]["password"] = "must-not-exist"
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "forbidden sensitive"):
            self.validate_request(request)

    def test_cross_request_and_cross_parameter_evidence_are_rejected(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        request["evidenceReceipts"][0]["authorizationRequestId"] = "authreq:other"
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "crossed"):
            self.validate_request(request)

        request = deepcopy(self.fixture["baseRequest"])
        request["parameterCandidateHash"] = "0" * 64
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "context hash drifted"):
            self.validate_request(request)

    def test_hardware_request_requires_every_structured_receipt(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        request["evidenceReceipts"] = request["evidenceReceipts"][:-1]
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "incomplete"):
            self.validate_request(request)

    def test_qualification_cannot_cross_candidate_vehicle_or_holdout(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        qualification = request["evidenceReceipts"][0]
        qualification["bindings"] = [
            item
            for item in qualification["bindings"]
            if item["name"] != "holdoutContractHash"
        ]
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "bindings are incomplete"):
            self.validate_request(request)

        request = deepcopy(self.fixture["baseRequest"])
        qualification = request["evidenceReceipts"][0]
        next(
            item
            for item in qualification["bindings"]
            if item["name"] == "payloadConfigHash"
        )["sha256"] = "0" * 64
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "crossed candidate"):
            self.validate_request(request)

    def test_operator_confirmation_is_a_short_lived_challenge_not_boolean(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        operator = next(
            receipt
            for receipt in request["evidenceReceipts"]
            if receipt["receiptType"] == "operator-confirmation"
        )
        operator["expiresAt"] = "2026-08-05T00:04:59Z"
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "hard cap"):
            self.validate_request(request)

    def test_consumed_or_duplicate_evidence_is_rejected(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        request["evidenceReceipts"][0]["consumptionState"] = "consumed"
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "one-time"):
            self.validate_request(request)

        request = deepcopy(self.fixture["baseRequest"])
        request["evidenceReceipts"][1]["receiptType"] = "trusted-qualification"
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "qualification level"):
            self.validate_request(request)

    def test_layer_receipt_is_bound_to_exact_request_and_canonical_hash(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        self.validate_request(request)
        receipt = self.layer_receipt(request, "native")
        contract.validate_layer_decision_receipt(
            receipt,
            request=request,
            policy=self.policy,
            app_env="test",
        )

        receipt["contextHash"] = "0" * 64
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "context hash drifted"):
            contract.validate_layer_decision_receipt(
                receipt,
                request=request,
                policy=self.policy,
                app_env="test",
            )

    def test_three_layer_quorum_allows_only_one_exact_context(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        layers = [
            self.layer_receipt(request, layer)
            for layer in ("native", "backend", "runtime")
        ]
        quorum = self.quorum_receipt(
            request,
            layers,
            decision="allow",
            reasons=["quorum.all-layers-allow"],
        )
        contract.validate_quorum_receipt(
            quorum,
            request=request,
            layer_receipts=layers,
            policy=self.policy,
            app_env="test",
        )

        quorum["layerDecisionHashes"]["runtime"] = "0" * 64
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "stale decisions"):
            contract.validate_quorum_receipt(
                quorum,
                request=request,
                layer_receipts=layers,
                policy=self.policy,
                app_env="test",
            )

    def test_non_allow_has_precedence_and_cannot_be_overwritten_by_allow(self) -> None:
        request = deepcopy(self.fixture["baseRequest"])
        layers = [
            self.layer_receipt(request, "native"),
            self.layer_receipt(
                request,
                "backend",
                decision="deny",
                reason="backend.pack.unvalidated",
            ),
            self.layer_receipt(request, "runtime"),
        ]
        quorum = self.quorum_receipt(
            request,
            layers,
            decision="deny",
            reasons=["backend.pack.unvalidated"],
        )
        contract.validate_quorum_receipt(
            quorum,
            request=request,
            layer_receipts=layers,
            policy=self.policy,
            app_env="test",
        )
        quorum["decision"] = "allow"
        quorum["reasonCodes"] = ["quorum.all-layers-allow"]
        with self.assertRaisesRegex(contract.EditionSafetyContractError, "precedence"):
            contract.validate_quorum_receipt(
                quorum,
                request=request,
                layer_receipts=layers,
                policy=self.policy,
                app_env="test",
            )

    def test_current_registry_has_zero_validated_or_signed_packs(self) -> None:
        registry = contract.load_json(
            DISTRIBUTION / "vehicle-packs" / "registry.v1.json"
        )
        self.assertEqual(
            [pack for pack in registry["packs"] if pack["currentValidationStatus"] == "validated"],
            [],
        )
        for path in sorted((DISTRIBUTION / "vehicle-packs").glob("*.v1.json")):
            if path.name.startswith("registry."):
                continue
            manifest = contract.load_json(path)
            self.assertNotEqual(manifest["integrity"]["signature"]["state"], "verified")

    def test_negative_fixture_catalog_covers_required_attack_classes(self) -> None:
        case_ids = {case["id"] for case in self.fixture["negativeCases"]}
        self.assertTrue(
            {
                "cross-request-receipt",
                "cross-device-layer-splice",
                "cross-parameter-layer-splice",
                "expired-request",
                "duplicate-consumption",
                "fake-issuer-in-production",
                "unknown-field",
                "qualification-holdout-missing",
                "operator-boolean-substitute",
                "layer-deny-precedence",
            }
            <= case_ids
        )


if __name__ == "__main__":
    unittest.main()
