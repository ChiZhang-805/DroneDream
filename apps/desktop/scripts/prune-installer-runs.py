"""Remove completed Desktop installer runs superseded by a successful build."""

import argparse
import json
import subprocess


WORKFLOW = ".github/workflows/desktop-installer.yml"


def api(endpoint, *options):
    result = subprocess.run(
        ["gh", "api", endpoint, *options], check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def obsolete_runs(runs, retained):
    return [
        run for run in runs
        if run["workflow_id"] == retained["workflow_id"]
        and run["id"] != retained["id"]
        and run["run_number"] < retained["run_number"]
        and run["status"] == "completed"
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--keep-run-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = f"repos/{args.repository}/actions"
    retained = api(f"{root}/runs/{args.keep_run_id}")
    if retained["path"] != WORKFLOW:
        parser.error("The retained run must belong to Desktop installer.")
    # The workflow calls this in its final job, after build/signing/publication.
    if retained["status"] == "completed" and retained["conclusion"] != "success":
        parser.error("A failed build cannot replace the last successful build.")
    endpoint = f"{root}/workflows/{retained['workflow_id']}/runs?per_page=100"
    pages = api(endpoint, "--paginate", "--slurp")
    runs = [run for page in pages for run in page["workflow_runs"]]
    obsolete = obsolete_runs(runs, retained)
    print(f"Keep run {retained['id']}; obsolete completed runs: {len(obsolete)}", flush=True)
    if not args.apply:
        return
    for index, run in enumerate(obsolete, 1):
        api(f"{root}/runs/{run['id']}", "--method", "DELETE")
        if index % 25 == 0 or index == len(obsolete):
            print(f"Deleted {index}/{len(obsolete)} obsolete runs", flush=True)
    pages = api(endpoint, "--paginate", "--slurp")
    remaining = [run for page in pages for run in page["workflow_runs"]]
    if obsolete_runs(remaining, retained):
        raise RuntimeError("Obsolete completed runs remain after cleanup.")
    if not any(run["id"] == retained["id"] for run in remaining):
        raise RuntimeError("The retained run is missing.")
    print(f"Cleanup complete; remaining runs: {len(remaining)}", flush=True)


if __name__ == "__main__":
    main()
