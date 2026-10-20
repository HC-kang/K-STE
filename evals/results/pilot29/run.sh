#!/usr/bin/env bash
# pilot: gen <cond> <model> <sid> <r>
set -u
P=$(cd "$(dirname "$0")" && pwd); REPO=/Users/ford/projects/personal/K-STE
gen() {
  cond=$1 m=$2 sid=$3 r=$4; out=$P/out/$cond/$m/r$r; mkdir -p $out
  prompt=$(cat $P/sc/$sid.txt); base="You are a helpful assistant."
  case $cond in
    base) sys=$base ;;
    full) sys="$base"$'\n\n'"$(cat $P/full.md)" ;;
    base+G) sys="$base"$'\n\n'"$(cat $P/glossary.md)" ;;
    full+G) sys="$base"$'\n\n'"$(cat $P/full.md)"$'\n\n'"$(cat $P/glossary.md)" ;;
  esac
  if [[ $cond == agent* ]]; then
    proj=$(mktemp -d); mkdir -p $proj/.claude/skills; cp -R $REPO/skills/k-ste $proj/.claude/skills/
    cp $P/short.md $proj/CLAUDE.md; [[ $cond == *G ]] && { echo; cat $P/glossary.md; } >> $proj/CLAUDE.md
    (cd $proj && claude -p "$prompt" --model $m --setting-sources project --strict-mcp-config --tools "Skill,Read" \
      --allowedTools "Skill Read" --output-format stream-json --verbose) | python3 $REPO/evals/trace.py $sid $out > $out/$sid.trace
    rm -rf $proj
  else
    claude -p "$prompt" --model $m --setting-sources "" --strict-mcp-config --system-prompt "$sys" --tools "" > $out/$sid.md 2> $out/$sid.err
  fi
}
export -f gen; export P REPO
for r in 1 2 3; do for m in haiku sonnet; do
  for c in full agent+short; do echo "$c $m S20 $r"; done
  for c in base full agent+short; do echo "$c $m S21 $r"; done
  for c in base+G full+G agent+short+G; do echo "$c $m S22 $r"; done
done; done > jobs.txt
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < jobs.txt
echo done
