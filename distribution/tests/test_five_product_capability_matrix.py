from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "distribution" / "repository" / "five-product-capability-matrix.v1.json"
TOPOLOGY = ROOT / "distribution" / "repository" / "branch-topology.v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_matrix_covers_exactly_five_distinct_products_and_branches() -> None:
    matrix = _load(MATRIX)
    products = matrix["products"]
    assert isinstance(products, list)
    by_product = {product["productId"]: product for product in products}
    assert set(by_product) == {"universal", "sim", "lab", "field", "autonomy"}

    topology = _load(TOPOLOGY)
    product_branches = {
        branch["productId"]: branch["name"]
        for branch in topology["branches"]
        if branch["role"] == "long-lived-product"
    }
    assert {product_id: product["branch"] for product_id, product in by_product.items()} == product_branches


def test_every_product_keeps_autonomy_without_erasing_its_product_boundary() -> None:
    matrix = _load(MATRIX)
    shared = matrix["sharedEngineeringPatterns"]
    assert shared["autonomyPageInEveryProduct"] is True
    assert shared["llmDirectActuationAllowed"] is False

    products = matrix["products"]
    assert all("autonomous-tasks" in product["navigationSections"] for product in products)
    assert all(product["conversationRole"] for product in products)
    assert all(product["experimentRole"] for product in products)
    assert len({product["primaryPurpose"] for product in products}) == 5


def test_execution_authority_is_fail_closed_at_product_boundaries() -> None:
    matrix = _load(MATRIX)
    products = {product["productId"]: product for product in matrix["products"]}
    assert products["sim"]["hardwareAuthority"] == "none"
    assert "operator-approval" in products["field"]["hardwareAuthority"]
    assert products["autonomy"]["hardwareAuthority"].startswith("simulation-first")
    assert "qualified-hardware-orchestration" in products["universal"]["executionDomains"]
