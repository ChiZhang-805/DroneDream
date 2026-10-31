"""Retain useful Actions runs and remove superseded completed history."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time


POLICY = Path(__file__).resolve().parents[3] / "release/distribution/desktop/actions-retention.json"
FAILURES = {"failure", "timed_out", "action_required", "startup_failure"}


def api(endpoint, *options):
    for attempt in range(4):
        result = subprocess.run(
            ["gh", "api", endpoint, *options], capture_output=True, text=True, encoding="utf-8"
        )
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else None
        transient = re.search(r"HTTP (429|500|502|503|504)|connection reset|TLS handshake timeout", result.stderr)
        if not transient or attempt == 3:
            raise RuntimeError(f"GitHub API {endpoint}: {result.stderr.strip()}")
        time.sleep(2 ** (attempt + 1))


def retention_reasons(runs, workflows, releases, policy):
    kept = {}

    def keep(run, reason):
        kept.setdefault(run["id"], []).append(reason)

    for run in runs:
        if run["status"] != "completed":
            keep(run, "queued or running")
        reason = policy.get("review_runs", {}).get(str(run["id"]))
        if reason:
            keep(run, reason)
    for workflow in workflows:
        if workflow["state"] != "active":
            continue
        completed = sorted(
            (r for r in runs if r["workflow_id"] == workflow["id"] and r["status"] == "completed"),
            key=lambda r: r["run_number"], reverse=True,
        )
        success = next((r for r in completed if r["conclusion"] == "success"), None)
        failure = next((r for r in completed if r["conclusion"] in FAILURES), None)
        if success:
            keep(success, "latest successful workflow run")
        if failure and (not success or failure["run_number"] > success["run_number"]):
            keep(failure, "latest unresolved workflow failure")
    for release in releases:
        tag = release["tag_name"]
        if tag.endswith("-channel"):
            continue
        legacy = policy.get("legacy_release_runs", {}).get(tag, [])
        for run in runs:
            if run["status"] != "completed" or run["conclusion"] != "success":
                continue
            named = re.search(r"(?<![\w.-])" + re.escape(tag) + r"(?![\w.-])", run.get("display_title", ""))
            if (run["id"] in legacy or run.get("head_branch") == tag or named
                    or (release.get("commit_sha") and run.get("head_sha") == release["commit_sha"])):
                keep(run, f"retained release {tag}")
    return kept


def unchanged_completed(original, current):
    return current["status"] == "completed" and all(
        original.get(key) == current.get(key) for key in ("run_attempt", "updated_at")
    )


def delete_completed(root, run):
    endpoint = f"{root}/runs/{run['id']}"
    if not unchanged_completed(run, api(endpoint)):
        return 0
    api(endpoint, "--method", "DELETE")
    return 1


def collection(endpoint, key=None):
    pages = api(endpoint, "--paginate", "--slurp")
    return [item for page in pages for item in (page[key] if key else page)]


def release_inventory(repository):
    releases = collection(f"repos/{repository}/releases?per_page=100")
    for release in releases:
        if not release["tag_name"].endswith("-channel"):
            ref = release["target_commitish"] if release["draft"] else release["tag_name"]
            release["commit_sha"] = api(f"repos/{repository}/commits/{ref}")["sha"]
    return releases


def release_identity(releases):
    return sorted((r["id"], r["tag_name"], r.get("commit_sha")) for r in releases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = f"repos/{args.repository}/actions"
    workflows = collection(f"{root}/workflows?per_page=100", "workflows")
    releases = release_inventory(args.repository)
    endpoint = f"{root}/runs?per_page=100"
    runs = collection(endpoint, "workflow_runs")
    kept = retention_reasons(runs, workflows, releases, json.loads(POLICY.read_text(encoding="utf-8")))
    obsolete = [r for r in runs if r["status"] == "completed" and r["id"] not in kept]
    for identity, reasons in kept.items():
        print(f"Keep {identity}: {'; '.join(reasons)}", flush=True)
    print(f"Total {len(runs)}; keep {len(kept)}; obsolete {len(obsolete)}", flush=True)
    if not args.apply:
        return
    deleted = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index in range(0, len(obsolete), 25):
            if release_identity(release_inventory(args.repository)) != release_identity(releases):
                print("Release inventory changed; remaining cleanup will use the next run's fresh inventory.", flush=True)
                break
            deleted += sum(pool.map(lambda run: delete_completed(root, run), obsolete[index:index + 25]))
            print(f"Deleted {deleted}/{len(obsolete)} obsolete runs", flush=True)
    remaining = collection(endpoint, "workflow_runs")
    missing = set(kept) - {r["id"] for r in remaining}
    if missing:
        raise RuntimeError(f"Retained runs are missing: {sorted(missing)}")
    print(f"Cleanup complete; deleted {deleted}; remaining {len(remaining)}", flush=True)


if __name__ == "__main__":
    main()
