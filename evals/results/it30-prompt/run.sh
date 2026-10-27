#!/usr/bin/env bash
# 30차: 지금 규칙(bbb5228)의 적용 전후 전체 측정. 저장소 루트에서 `caffeinate -i bash evals/results/it30-prompt/run.sh`로 실행한다.
# 조건 base short full agent+short, 모델 haiku sonnet, 시나리오 S1-S19, 회차 r1-r3. 실행 중에는 prompts/와 skills/를 고치면 안 된다.
set -u
REPO=$(pwd); P=$REPO/evals/results/it30-prompt
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
blk() { awk "/<!-- $1:start -->/{f=1;next}/<!-- $1:end -->/{f=0}f" prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1; }
hashes() { shasum -a 256 $F; echo "$(blk short)  short-block"; echo "$(blk full)  full-block"; }
rot() { local k=$1; shift; local a=("$@"); local n=${#a[@]}; for i in $(seq 0 $((n - 1))); do printf '%s ' ${a[$(((i + k) % n))]}; done; }

# 작업 하나는 (회차, 조건, 모델, 시나리오)다. 같은 (회차, 시나리오, 모델)의 네 조건을 이어서 두고, 조건 순서는 시나리오마다 한 칸씩 돈다.
for r in 1 2 3; do
  i=0
  for s in S1 S2 S3 S4 S5 S6 S7 S8 S9 S10 S11 S12 S13 S14 S15 S16 S17 S18 S19; do
    [ $((r % 2)) = 1 ] && M="haiku sonnet" || M="sonnet haiku"
    for m in $M; do for c in $(rot $(((i + r) % 4)) base short full agent+short); do echo "$r $c $m $s"; done; done
    i=$((i + 1))
  done
done > $P/jobs.txt

git rev-parse HEAD > $P/head.txt
for m in haiku sonnet opus; do
  echo "$m $(claude -p "1" --model $m --setting-sources "" --strict-mcp-config --tools "" --output-format json | python3 -c 'import json,sys; print(*json.load(sys.stdin).get("modelUsage",{}))')"
done > $P/models.txt; claude --version >> $P/models.txt
hashes > $P/before.sha256

gen() {  # gen <run> <cond> <model> <sid>
  echo "$(date +%T) start r$1 $2 $3 $4" >> $P/order.log
  case $2 in
    agent+short) RUN=it30-r$1 WITH_SHORT=1 bash evals/agent_path.sh $3 $4 >> $P/gen.out 2>> $P/gen.err ;;
    *) RUN=it30-r$1 bash evals/run.sh $2 $3 $4 >> $P/gen.out 2>> $P/gen.err ;;
  esac
  echo "$(date +%T) end r$1 $2 $3 $4" >> $P/order.log
}
export -f gen; export P
# 작업 하나가 claude -p 하나이므로 동시 claude -p는 6개 이하다.
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/jobs.txt
# 출력이 없거나 API 오류 문자열로 시작하는 작업을 다시 생성한다(최대 3번).
missing() { while read r c m s; do o=evals/results/it30-r$r/$m/$c/$s.md; { [ -s $o ] && ! grep -q '^API Error' $o; } || echo "$r $c $m $s"; done < $P/jobs.txt; }
for try in 1 2 3; do
  missing > $P/missing-$try.txt; [ -s $P/missing-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing-$try.txt) jobs" >> $P/order.log
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/missing-$try.txt
done
missing > $P/missing-final.txt
hashes > $P/after.sha256

# judge.py는 스레드 6개로 claude -p를 실행한다. 회차를 하나씩 판정하므로 동시 실행은 6개 이하다. S3 S4 S8 S9는 판정이 없다.
echo "$(date +%T) judge start" >> $P/order.log
for r in 1 2 3; do python3 evals/judge.py evals/results/it30-r$r > /dev/null; done
# 판정 오류가 난 (회차, 조건, 시나리오)만 다시 판정한다(최대 2번).
for try in 1 2; do
  python3 - > $P/rejudge-$try.txt <<'EOF'
import glob, json
for f in glob.glob("evals/results/it30-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        if "error" in r["verdict"]:
            p = r["file"].split("/")
            print(p[2][6:], p[4], p[5][:-3])
EOF
  [ -s $P/rejudge-$try.txt ] || break
  sort -u $P/rejudge-$try.txt | while read r c s; do python3 evals/judge.py evals/results/it30-r$r --cond $c --sid $s > /dev/null; done
done
echo "$(date +%T) judge end" >> $P/order.log
