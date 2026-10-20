#!/usr/bin/env bash
# 29차 묶음 2: S23 하나를 용어집 배치 하나로 생성한다. 구성 폴더(git archive를 푼 폴더) 안에서 실행한다.
# 사용법: RUN=<name> bash glossary.sh <G-sys-base|G-sys-full|G-inline|G-ptr|G-file> <model>
# 출력: evals/results/$RUN/<model>/<배치>/S23.md. agent 배치는 trace.txt에 스킬 실행과 읽은 파일을 한 줄로 더한다.
# sys 배치는 evals/run.sh와 같은 claude -p 인자로, agent 배치는 evals/agent_path.sh와 같은 claude -p 인자로 실행한다.
# 용어집 본문은 evals/scenarios/S23.glossary.md다. 시스템 프롬프트에 넣을 때는 run.sh의 블록처럼 $(...)로 읽어서 끝 줄바꿈만 빠진다.
set -euo pipefail
batch=$1 model=$2 sid=S23
here=$(pwd); G=$here/evals/scenarios/S23.glossary.md
out=$here/evals/results/${RUN:?}/$model/$batch
mkdir -p "$out"
block() { awk "/<!-- $1:start -->/{f=1;next}/<!-- $1:end -->/{f=0}f" "$here/prompts/system-prompt.md"; }

case $batch in
  G-sys-base|G-sys-full)
    sys="You are a helpful assistant."
    [ $batch = G-sys-full ] && sys="$sys"$'\n\n'"$(block full)"
    sys="$sys"$'\n\n'"$(cat "$G")"
    claude -p "$(cat "$here/evals/scenarios/$sid.txt")" --model "$model" --setting-sources "" --strict-mcp-config \
      --system-prompt "$sys" --tools "" > "$out/$sid.md" 2> "$out/$sid.err" || echo "FAIL $sid (see $out/$sid.err)"
    [ -s "$out/$sid.err" ] || rm -f "$out/$sid.err" ;;
  G-inline|G-ptr|G-file)
    proj=$(mktemp -d)
    trap 'rm -rf "$proj"' EXIT
    mkdir -p "$proj/.claude/skills"
    cp -R "$here/skills/k-ste" "$proj/.claude/skills/"
    block short > "$proj/CLAUDE.md"
    case $batch in
      G-inline) printf '\n' >> "$proj/CLAUDE.md"; cat "$G" >> "$proj/CLAUDE.md" ;;
      G-ptr) mkdir -p "$proj/docs"; cp "$G" "$proj/docs/glossary.md"
             printf '\n## 용어\n\n팀 문서와 PR, 메시지의 용어는 `docs/glossary.md`를 따른다.\n' >> "$proj/CLAUDE.md" ;;
      G-file) mkdir -p "$proj/docs"; cp "$G" "$proj/docs/glossary.md" ;;
    esac
    (cd "$proj" && claude -p "$(cat "$here/evals/scenarios/$sid.txt")" --model "$model" \
      --setting-sources project --strict-mcp-config --tools "Skill,Read" --allowedTools "Skill Read" \
      --output-format stream-json --verbose) |
    python3 "$here/evals/trace.py" "$sid" "$out" | tee -a "$out/trace.txt" ;;
  *) echo "unknown batch: $batch" >&2; exit 1 ;;
esac
