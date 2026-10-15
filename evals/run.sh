#!/usr/bin/env bash
# Run scenarios in an isolated `claude -p` session (no user CLAUDE.md, no tools).
# Usage: RUN=<name> bash evals/run.sh <base|short|full> <model> [SID...]
# Output: evals/results/$RUN/<model>/<condition>/<SID>.md
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 2 ] || { echo "usage: RUN=<name> bash evals/run.sh <base|short|full> <model> [SID...]" >&2; exit 2; }

cond=$1 model=$2
shift 2
ids=("$@")
[ ${#ids[@]} -eq 0 ] && ids=(S1 S2 S3 S4 S5 S6 S7 S8 S9 S10)

base="You are a helpful assistant."
case $cond in
  base) sys=$base ;;
  short|full)
    block=$(awk "/<!-- $cond:start -->/{f=1;next}/<!-- $cond:end -->/{f=0}f" prompts/system-prompt.md)
    [ -n "$block" ] || { echo "no <!-- $cond:start --> block in prompts/system-prompt.md" >&2; exit 1; }
    sys="$base"$'\n\n'"$block" ;;
  *) echo "unknown condition: $cond" >&2; exit 1 ;;
esac

out=evals/results/${RUN:-$(date +%F)}/$model/$cond
mkdir -p "$out"
export sys model out
printf '%s\n' "${ids[@]}" | xargs -P 6 -I{} bash -c '
  sid=$1
  claude -p "$(cat "evals/scenarios/$sid.txt")" --model "$model" --setting-sources "" --strict-mcp-config \
    --system-prompt "$sys" --tools "" > "$out/$sid.md" 2> "$out/$sid.err" || echo "FAIL $sid (see $out/$sid.err)"
  [ -s "$out/$sid.err" ] || rm -f "$out/$sid.err"' _ {}
echo "done: $out"
