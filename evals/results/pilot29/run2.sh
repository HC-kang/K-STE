#!/usr/bin/env bash
set -u
P=$(cd "$(dirname "$0")" && pwd); REPO=/Users/ford/projects/personal/K-STE
gen() {
  cond=$1 m=$2 sid=$3 r=$4; out=$P/out2/$cond/$m/r$r; mkdir -p $out
  prompt=$(cat $P/sc/${sid%%-*}.txt); base="You are a helpful assistant."
  case $cond in
    base) sys=$base ;;
    full) sys="$base"$'\n\n'"$(cat $P/full.md)" ;;
  esac
  if [[ $cond == agent* ]]; then
    proj=$(mktemp -d); mkdir -p $proj/.claude/skills $proj/docs; cp -R $REPO/skills/k-ste $proj/.claude/skills/
    cp $P/short.md $proj/CLAUDE.md
    if [[ $cond == agent+short+file* ]]; then
      { echo "# 용어집"; echo; sed 1,2d $P/glossary.md; } > $proj/docs/glossary.md
      [[ $cond == *ptr ]] && printf '\n## 용어\n\n팀 문서와 PR, 메시지의 용어는 `docs/glossary.md`를 따른다.\n' >> $proj/CLAUDE.md
    fi
    (cd $proj && claude -p "$prompt" --model $m --setting-sources project --strict-mcp-config --tools "Skill,Read" \
      --allowedTools "Skill Read" --output-format stream-json --verbose) | python3 $REPO/evals/trace.py ${sid%%-*} $out > $out/${sid%%-*}.trace
    rm -rf $proj
  else
    claude -p "$prompt" --model $m --setting-sources "" --strict-mcp-config --system-prompt "$sys" --tools "" > $out/$sid.md 2> $out/$sid.err
  fi
}
export -f gen; export P REPO
for r in 1 2 3; do for m in haiku sonnet; do
  for s in S20b S20c; do echo "full $m $s $r"; done
  for c in base full agent+short; do echo "$c $m S21b $r"; done
  for c in agent+short+file agent+short+file+ptr; do echo "$c $m S22 $r"; done
done; done > jobs2.txt
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < jobs2.txt
echo done
