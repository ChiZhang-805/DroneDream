from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image, ImageChops


VIOLET = "#6847FF"
MAGENTA = "#C33DE2"
ROSE = "#F04B9A"
LAVENDER = "#C9BCFF"
INK = "#1A1423"
WHITE = "#FFFFFF"


def git_bytes(repository: Path, ref_commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{ref_commit}:{path}"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def evidence_bundle(
    repository: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [
        *manifest["software"]["artifacts"],
        *manifest["software"].get("source_references", []),
    ]
    entry = next(
        (
            item
            for item in entries
            if item["id"] == "technical_report_evidence_bundle"
        ),
        None,
    )
    if entry is None:
        raise ValueError("manifest lacks technical_report_evidence_bundle")
    payload = git_bytes(repository, entry["ref_commit"], entry["path"])
    actual_sha256 = sha256_bytes(payload)
    if actual_sha256 != entry["file_sha256"]:
        raise ValueError(
            "frozen evidence bundle SHA-256 drifted: "
            f"expected {entry['file_sha256']}, found {actual_sha256}"
        )
    evidence = json.loads(payload.decode("utf-8"))
    if evidence.get("schema_version") != "dronedream.technical-report-evidence.v7":
        raise ValueError("data figures require the frozen v7 evidence bundle")
    if evidence.get("source_commit") != manifest["software"]["subject_commit"]:
        raise ValueError("data-figure bundle source commit drifted")
    if evidence.get("bundle_sha256") != entry["canonical_sha256"]:
        raise ValueError("data-figure canonical bundle SHA-256 drifted")
    return evidence, entry


def chart_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.labelsize": 11,
            "axes.labelcolor": INK,
            "axes.edgecolor": "#C8C2D0",
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "figure.facecolor": WHITE,
            "axes.facecolor": WHITE,
        }
    )


def pad_top(path: Path, target_height: int) -> None:
    with Image.open(path) as source:
        if source.height > target_height:
            raise ValueError(
                f"cannot pad {path.name} from height {source.height} "
                f"to {target_height}"
            )
        if source.height == target_height:
            return
        canvas = Image.new(source.mode, (source.width, target_height), "white")
        canvas.paste(source, (0, target_height - source.height))
        dpi = source.info.get("dpi", (220, 220))
        canvas.save(path, dpi=dpi)


def make_routing_bar(evidence: dict[str, Any], path: Path) -> None:
    routing = evidence["routing"]
    if (
        routing.get("evidence_schema_version") != "2.7"
        or routing.get("prompt_template_version") != "1.6"
        or routing.get("qualification_scope") != "current_evidence_2_7_prompt_1_6"
        or routing.get("qualified") is not True
    ):
        raise ValueError("routing figure requires current Evidence 2.7 / Prompt 1.6")
    labels = [
        "Current AURORA\nrouter (2.7 / 1.6)",
        "Best constant\npolicy",
        "Uniform random\nexpectation",
    ]
    values = [
        routing["pass_rate"] * 100,
        routing["best_constant_pass_rate"] * 100,
        routing["uniform_random_expected_pass_rate"] * 100,
    ]
    colors = [VIOLET, MAGENTA, LAVENDER]
    fig, ax = plt.subplots(figsize=(1012 / 220, 596 / 220), dpi=220)
    bars = ax.bar(labels, values, color=colors, width=0.62)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Acceptable tool selection (%)")
    ax.tick_params(axis="both", labelsize=10)
    ax.grid(axis="y", color="#EEEAF2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 2.5,
            f"{value:.2f}%",
            ha="center",
            fontsize=10.5,
            fontweight="bold",
            color=INK,
        )
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def make_ablation_chart(evidence: dict[str, Any], path: Path) -> None:
    rows = evidence["harness_ablations"]["component_rows"]
    label_map = {
        "deterministic_fallback": "Deterministic fallback",
        "provider_trust_filter": "Provider trust",
        "scenario_and_outcome_isolation": "Scenario isolation",
        "scenario_profile_context": "Scenario profile",
        "tool_eligibility_gate": "Eligibility gate",
    }
    if {row["component"] for row in rows} != set(label_map):
        raise ValueError("frozen ablation components do not match the figure contract")
    labels = [label_map[row["component"]] for row in rows]
    full = [row["full_contract_correct_rate"] * 100 for row in rows]
    ablated = [row["ablated_contract_correct_rate"] * 100 for row in rows]
    y = np.arange(len(labels)) * 1.05
    height = 0.32
    fig, ax = plt.subplots(figsize=(1346 / 120, 624 / 120), dpi=120)
    full_bars = ax.barh(
        y - height / 2,
        full,
        height,
        label="Production guard",
        color=VIOLET,
    )
    ablated_bars = ax.barh(
        y + height / 2,
        ablated,
        height,
        label="Weakened guard",
        color=ROSE,
    )
    ax.set_yticks(y, labels, fontsize=14)
    ax.set_ylim(y[-1] + 0.65, -0.85)
    ax.set_xlim(0, 118)
    ax.set_xlabel("Contract expectations satisfied (%)", fontsize=14)
    ax.tick_params(axis="x", labelsize=12)
    fig.legend(
        handles=[full_bars, ablated_bars],
        labels=["Production guard", "Weakened guard"],
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.60, 0.965),
        fontsize=13,
    )
    ax.grid(axis="x", color="#EEEAF2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    for bars in (full_bars, ablated_bars):
        for bar in bars:
            value = bar.get_width()
            ax.text(
                value + 1.2,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.0f}%",
                ha="left",
                va="center",
                fontsize=13,
                fontweight="bold",
                color=INK,
            )
    fig.subplots_adjust(left=0.25, right=0.94, bottom=0.20, top=0.72)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def make_tool_distribution(evidence: dict[str, Any], path: Path) -> None:
    rows = sorted(
        evidence["routing"]["tool_selection_rows"],
        key=lambda row: row["selected_count"],
    )
    label_map = {
        "bipop_cma_es": "BIPOP-CMA-ES",
        "constrained_mobo": "Constrained MOBO",
        "multi_fidelity_mobo": "Multi-fidelity MOBO",
        "optimizer_portfolio": "Optimizer portfolio",
        "saasbo": "SAASBO",
        "surrogate_cma_es": "Surrogate CMA-ES",
        "turbo": "TuRBO",
    }
    if {row["tool"] for row in rows} != set(label_map):
        raise ValueError("frozen routing tools do not match the figure contract")
    labels = [label_map[row["tool"]] for row in rows]
    values = [row["selected_count"] for row in rows]
    gradient = [
        LAVENDER,
        "#B894F6",
        "#A875EE",
        "#9656E4",
        "#8339DB",
        MAGENTA,
        ROSE,
    ]
    fig, ax = plt.subplots(figsize=(5.2, 1.72))
    bars = ax.barh(labels, values, color=gradient[: len(values)])
    ax.set_xlim(0, max(values) + 2)
    ax.set_xlabel("Selected cases")
    ax.tick_params(axis="x", labelsize=10)
    ax.tick_params(axis="y", labelsize=9.6, pad=2)
    ax.grid(axis="x", color="#EEEAF2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value + 0.15,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            fontsize=10.5,
            fontweight="bold",
        )
    fig.subplots_adjust(left=0.265, right=0.975, bottom=0.25, top=0.96)
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


def scenario_rows(evidence: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = evidence["simulation_coverage"]["scenario_rows"]
    label_map = {
        "nominal": "nominal",
        "noise_perturbed": "noise",
        "wind_perturbed": "wind",
        "combined_perturbed": "combined",
        "turbulence": "turbulence",
        "gps_dropout": "GPS",
        "payload_changed": "payload",
        "battery_degraded": "battery",
        "actuator_delay": "actuator",
        "custom": "custom",
    }
    if {row["scenario"] for row in rows} != set(label_map):
        raise ValueError("frozen scenarios do not match the figure contract")
    return rows, [label_map[row["scenario"]] for row in rows]


def make_scenario_chart(evidence: dict[str, Any], path: Path) -> None:
    rows, labels = scenario_rows(evidence)
    baseline = [row["baseline_holdout_loss"] for row in rows]
    selected = [row["selected_holdout_loss"] for row in rows]
    x = np.arange(len(labels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(6.1, 2.92))
    ax.bar(x - width / 2, baseline, width, label="Baseline", color=LAVENDER)
    ax.bar(x + width / 2, selected, width, label="Selected", color=VIOLET)
    ax.set_xticks(x, labels, fontsize=9.5, rotation=28, ha="right")
    ax.set_ylabel("Holdout loss (lower is better)")
    ax.tick_params(axis="y", labelsize=10)
    ax.legend(frameon=False, ncol=2, fontsize=10)
    ax.grid(axis="y", color="#EEEAF2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    pad_top(path, 635)


def make_scenario_heatmap(evidence: dict[str, Any], path: Path) -> None:
    rows, labels = scenario_rows(evidence)
    values = np.array(
        [[row["relative_improvement_rate"] * 100 for row in rows]]
    )
    cmap = LinearSegmentedColormap.from_list(
        "dreamline",
        ["#F5F0FF", LAVENDER, VIOLET, MAGENTA, ROSE],
    )
    fig, ax = plt.subplots(figsize=(6.5, 1.8))
    image = ax.imshow(values, aspect="auto", cmap=cmap, vmin=15, vmax=35)
    ax.set_yticks([0], ["Relative\nimprovement"], fontsize=10)
    ax.set_xticks(
        range(len(labels)),
        labels,
        fontsize=9,
        rotation=30,
        ha="right",
    )
    for index, value in enumerate(values[0]):
        ax.text(
            index,
            0,
            f"{value:.1f}%",
            ha="center",
            va="center",
            color=WHITE if value > 29 else INK,
            fontweight="bold",
            fontsize=9.5,
        )
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    colorbar = fig.colorbar(
        image,
        ax=ax,
        orientation="horizontal",
        pad=0.48,
        fraction=0.14,
        label="Relative loss reduction (%)",
    )
    colorbar.ax.tick_params(labelsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--compare-directory", type=Path)
    args = parser.parse_args()

    repository = args.repository.resolve()
    output_directory = args.output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    evidence, entry = evidence_bundle(repository, args.manifest.resolve())
    chart_style()
    outputs = {
        "image4.png": make_routing_bar,
        "image5.png": make_ablation_chart,
        "image6.png": make_tool_distribution,
        "image7.png": make_scenario_chart,
        "image8.png": make_scenario_heatmap,
    }
    result: dict[str, str] = {}
    for filename, generator in outputs.items():
        path = output_directory / filename
        generator(evidence, path)
        result[filename] = sha256_bytes(path.read_bytes())
    comparison: dict[str, str] | None = None
    if args.compare_directory is not None:
        compare_directory = args.compare_directory.resolve()
        comparison = {}
        for filename in outputs:
            generated_path = output_directory / filename
            expected_path = compare_directory / filename
            with (
                Image.open(generated_path) as generated,
                Image.open(expected_path) as expected,
            ):
                if generated.size != expected.size:
                    raise ValueError(
                        f"{filename} size drifted: generated={generated.size}, "
                        f"tracked={expected.size}"
                    )
                difference = ImageChops.difference(
                    generated.convert("RGB"),
                    expected.convert("RGB"),
                )
                if difference.getbbox() is not None:
                    raise ValueError(f"{filename} rendered pixels drifted")
            comparison[filename] = "pixel-identical"
    print(
        json.dumps(
            {
                "source": {
                    "ref_commit": entry["ref_commit"],
                    "path": entry["path"],
                    "sha256": entry["file_sha256"],
                },
                "outputs": result,
                "comparison": comparison,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
