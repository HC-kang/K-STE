#!/usr/bin/env bash
# Coding-agent path: install the skill into a throwaway project and check that Claude Code invokes it.
# Usage: RUN=<name> [WITH_SHORT=1] bash evals/agent_path.sh <model> [SID...]
#   WITH_SHORT=1 also puts the short prompt in the project CLAUDE.md, the setup the README recommends.
# Output: evals/results/$RUN/<model>/<agent|agent+short>/<SID>.md and one trace line per scenario.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
model=$1
shift
ids=("$@")
[ ${#ids[@]} -eq 0 ] && ids=(S5 S6 S7 S9)

proj=$(mktemp -d)
trap 'rm -rf "$proj"' EXIT
mkdir -p "$proj/.claude/skills"
cp -R "$repo/skills/k-ste" "$proj/.claude/skills/"
cond=agent
if [ "${WITH_SHORT:-}" = 1 ]; then
  awk '/<!-- short:start -->/{f=1;next}/<!-- short:end -->/{f=0}f' "$repo/prompts/system-prompt.md" > "$proj/CLAUDE.md"
  cond=agent+short
fi

out=$repo/evals/results/${RUN:-$(date +%F)}/$model/$cond
mkdir -p "$out"
for sid in "${ids[@]}"; do
  (
    (cd "$proj" && claude -p "$(cat "$repo/evals/scenarios/$sid.txt")" --model "$model" \
      --setting-sources project --strict-mcp-config --tools "Skill,Read" --allowedTools "Skill Read" \
      --output-format stream-json --verbose) |
    python3 "$repo/evals/trace.py" "$sid" "$out"
  ) &
done
wait
