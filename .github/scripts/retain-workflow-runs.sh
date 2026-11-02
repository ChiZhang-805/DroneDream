#!/usr/bin/env bash
set -Eeuo pipefail

readonly keep_count=4
mapfile -t runs < <(
  gh api --paginate \
    "/repos/${GITHUB_REPOSITORY}/actions/runs?per_page=100" \
    --jq '.workflow_runs[] | [.id, .status] | @tsv'
)

for ((index = keep_count; index < ${#runs[@]}; index++)); do
  IFS=$'\t' read -r run_id status <<<"${runs[$index]}"
  if [[ "$status" == "completed" ]]; then
    gh api --method DELETE "/repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}"
  fi
done
