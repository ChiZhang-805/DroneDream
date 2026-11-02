#!/usr/bin/env bash
set -Eeuo pipefail

mapfile -t runs < <(
  gh api --paginate \
    "/repos/${GITHUB_REPOSITORY}/actions/runs?per_page=100" \
    --jq '.workflow_runs[] | [.id, .workflow_id, .status] | @tsv'
)

declare -A retained_workflows=()
for run in "${runs[@]}"; do
  IFS=$'\t' read -r run_id workflow_id status <<<"$run"
  if [[ -z "${retained_workflows[$workflow_id]+present}" ]]; then
    retained_workflows["$workflow_id"]=1
    continue
  fi
  if [[ "$status" == "completed" ]]; then
    gh api --method DELETE "/repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}"
  fi
done
