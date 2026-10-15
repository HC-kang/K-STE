#!/usr/bin/env bash
# Coding-agent path: install the skill into a throwaway project and check that Claude Code invokes it.
# Usage: RUN=<name> bash evals/agent_path.sh <model> [SID...]
# Output: evals/results/$RUN/<model>/agent/<SID>.md and a trace line per scenario on stdout.
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

out=$repo/evals/results/${RUN:-$(date +%F)}/$model/agent
mkdir -p "$out"
for sid in "${ids[@]}"; do
  (cd "$proj" && claude -p "$(cat "$repo/evals/scenarios/$sid.txt")" --model "$model" \
    --setting-sources project --allowedTools "Skill Read" --output-format stream-json --verbose) |
  python3 -c '
import json, sys
sid, out = sys.argv[1], sys.argv[2]
skill, reads, result = [], [], ""
for line in sys.stdin:
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("type") == "assistant":
        for c in e["message"]["content"]:
            if c.get("type") == "tool_use" and c["name"] == "Skill":
                skill.append(c["input"].get("skill"))
            if c.get("type") == "tool_use" and c["name"] == "Read":
                reads.append(c["input"].get("file_path", "").split("/k-ste/")[-1])
    if e.get("type") == "result":
        result = e.get("result", "")
open(f"{out}/{sid}.md", "w").write(result)
print(f"{sid}\tskill={skill}\treads={reads}")
' "$sid" "$out"
done
