#!/usr/bin/env bash
# 26차 가지 준비, 생성, 판정. 저장소 루트에서 `bash evals/results/it26-prompt/run.sh`로 실행한다.
# 동시에 실행하는 claude -p는 3개 이하다(생성 xargs -P 3, 판정 judge3.py).
set -u
REPO=$(pwd); P=$REPO/evals/results/it26-prompt; SHA=f8c7962
X10=$REPO/evals/reader/exp/X10-dates-v4/out/prompts/short-v4.txt
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
block() { awk "/<!-- $2:start -->/{f=1;next}/<!-- $2:end -->/{f=0}f" $1/prompts/system-prompt.md; }
hashes() { (cd $1 && shasum -a 256 $F && echo "$(block . short | shasum -a 256 | cut -d' ' -f1)  short-block" \
  && echo "$(block . full | shasum -a 256 | cut -d' ' -f1)  full-block"); }
B=(v3 v4.1)
SENS="S5 S6 S7 S10 S13 S15 S18"
ALL="S1 S2 S3 S4 S5 S6 S7 S8 S9 S10 S11 S12 S13 S14 S15 S16 S17 S18 S19"
beat() { orca orchestration send --from term_01100448-726a-4a56-99cc-ca4058a849c6 --type heartbeat --subject "alive" \
  --task-id task_c3173eb52fdc --dispatch-id ctx_560be08db731 --phase "$1" > /dev/null 2>&1; }

# 1. 가지 준비: 두 가지 모두 f8c7962를 저장소 밖에 풀고, v4.1은 짧은판 블록만 X10 파일로 바꾼다.
if [ ! -s $P/dirs.txt ]; then
  for b in "${B[@]}"; do
    T=$(mktemp -d); git archive $SHA | tar -x -C $T
    if [ $b = v4.1 ]; then
      python3 -I - $T/prompts/system-prompt.md $X10 <<'PY' || exit 1
import sys
p, b = sys.argv[1], open(sys.argv[2], encoding="utf-8").read()
t = open(p, encoding="utf-8").read()
s, e = "<!-- short:start -->\n", "<!-- short:end -->"
assert t.count(s) == 1 and t.count(e) == 1 and not b.startswith("You are")
head, rest = t.split(s)
tail = rest.split(e)[1]
open(p, "w", encoding="utf-8").write(head + s + b + e + tail)
PY
    fi
    echo "$b $T" >> $P/dirs.txt
  done
fi
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
for f in $F; do echo "$(git show $SHA:$f | shasum -a 256 | cut -d' ' -f1)  $f"; done > $P/$SHA.sha256
for b in "${B[@]}"; do hashes $(dir $b) > $P/$b-before.sha256; block $(dir $b) short > $P/short-$b.txt; done
diff $(dir v3)/prompts/system-prompt.md $(dir v4.1)/prompts/system-prompt.md > $P/v4.1.diff
# 확인: v3 = f8c7962, 두 가지의 짧은판 블록 해시, v4.1은 짧은판 블록만 다르다.
cmp <(head -5 $P/v3-before.sha256) $P/$SHA.sha256 || { echo "v3 != $SHA"; exit 1; }
grep -q '^ffe3fb4c9b6c2183313716848205c857e2d24a95668326f6a488bbfcc44f1818  short-block' $P/v3-before.sha256 || { echo "v3 short"; exit 1; }
grep -q '^74ef1680498e8e5b7739f177dc0f0752dcb0961a76ff56871fabe67f57d47b3d  short-block' $P/v4.1-before.sha256 || { echo "v4.1 short"; exit 1; }
cmp $P/short-v4.1.txt $X10 || exit 1
diff <(sed -n '2,5p;7p' $P/v3-before.sha256) <(sed -n '2,5p;7p' $P/v4.1-before.sha256) || { echo "skill/full differ"; exit 1; }
[ "${SETUP_ONLY:-}" = 1 ] && { echo "setup ok"; exit 0; }

(while sleep 300; do beat "generating: $(grep -c ' end ' $P/order.log 2>/dev/null)/848 jobs"; done) & HB=$!
trap 'kill $HB 2>/dev/null' EXIT
for m in haiku sonnet opus; do
  echo "$m $(claude -p "1" --model $m --setting-sources "" --strict-mcp-config --tools "" --output-format json | python3 -c 'import json,sys; print(*json.load(sys.stdin).get("modelUsage",{}))')"
done > $P/models.txt; claude --version >> $P/models.txt

# 2. 생성: 작업 하나 = (회차, 모델, 조건, 시나리오, 가지). 같은 (회차, 모델, 조건, 시나리오)의 두 가지는 이어진 작업이다.
# 홀수 회차는 v3를, 짝수 회차는 v4.1을 먼저 둔다. 모델 순서도 회차마다 바꾼다. r1-r3은 19개 시나리오, r4-r10은 민감한 7개다.
export P
gen() {  # gen <run> <model> <cond> <sid> <branch> <dir>
  echo "$(date +%T) start r$1 $2 $3 $4 $5" >> $P/order.log
  if [ $3 = short ]; then (cd $6 && RUN=it26-r$1 bash evals/run.sh short $2 $4 > /dev/null 2>> $P/gen.err)
  else (cd $6 && RUN=it26-r$1 WITH_SHORT=1 bash evals/agent_path.sh $2 $4 > /dev/null 2>> $P/gen.err); fi
  echo "$(date +%T) end r$1 $2 $3 $4 $5" >> $P/order.log
}
export -f gen
if [ ! -s $P/jobs.txt ]; then
  for r in $(seq 1 10); do
    if [ $((r % 2)) = 1 ]; then V="v3 v4.1"; M="haiku sonnet"; else V="v4.1 v3"; M="sonnet haiku"; fi
    S=$SENS; [ $r -le 3 ] && S=$ALL
    for m in $M; do for c in short agent+short; do for s in $S; do for b in $V; do echo "$r $m $c $s $b $(dir $b)"; done; done; done; done
  done > $P/jobs.txt
fi
xargs -P 3 -L 1 bash -c 'gen "$@"' _ < $P/jobs.txt
missing() { while read r m c s b T; do [ -s $T/evals/results/it26-r$r/$m/$c/$s.md ] || echo "$r $m $c $s $b $T"; done < $P/jobs.txt; }
for try in 1 2 3; do
  missing > $P/missing-$try.txt; [ -s $P/missing-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing-$try.txt) jobs" >> $P/order.log
  xargs -P 3 -L 1 bash -c 'gen "$@"' _ < $P/missing-$try.txt
done
missing > $P/missing-final.txt
for b in "${B[@]}"; do hashes $(dir $b) > $P/$b-after.sha256; done
hashes $REPO > $P/worktree-after.sha256

# 3. 복사와 판정: it26-rN/<모델>/<조건>-<가지>/
for r in $(seq 1 10); do for m in haiku sonnet; do mkdir -p $REPO/evals/results/it26-r$r/$m
  for c in short agent+short; do for b in "${B[@]}"; do
    cp -R $(dir $b)/evals/results/it26-r$r/$m/$c $REPO/evals/results/it26-r$r/$m/$c-$b; done; done
done; done
kill $HB; (while sleep 300; do beat "judging: $(cat $REPO/evals/results/it26-r*/judge.jsonl 2>/dev/null | wc -l | tr -d ' ')/752"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order.log
for r in $(seq 1 10); do python3 $P/judge3.py evals/results/it26-r$r > /dev/null; done
echo "$(date +%T) judge end" >> $P/order.log
