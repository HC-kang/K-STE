#!/usr/bin/env bash
# 24차 생성과 판정. 저장소 루트에서 `bash evals/results/it24-prompt/run.sh`로 실행한다.
# dirs.txt(가지와 임시 폴더)는 먼저 만든다: 가지마다 `git archive fe56e82 | tar -x -C $(mktemp -d)`를 하고
# `python3 -I make_short.py <폴더>/prompts/system-prompt.md <묶음...>`을 실행한다(v3는 묶음 없음, v4.1은 G1 G2 G3 G4).
set -u
REPO=$(pwd); P=$REPO/evals/results/it24-prompt
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
hashes() { (cd $1 && shasum -a 256 $F && echo "$(awk '/<!-- short:start -->/{f=1;next}/<!-- short:end -->/{f=0}f' prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1)  short-block"); }
B=(v3 v4.1 G1 G2 G3 G4)
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
beat() { orca orchestration send --from term_57c4c471-ad85-44a8-879b-329c888ad4c8 --type heartbeat --subject "alive" \
  --task-id task_dcc465c21583 --dispatch-id ctx_473a48ffb417 --phase "$1" > /dev/null 2>&1; }
(while sleep 300; do beat "generating: $(grep -c ' end ' $P/order.log 2>/dev/null)/240 jobs"; done) & HB=$!
trap 'kill $HB 2>/dev/null' EXIT

for b in "${B[@]}"; do hashes $(dir $b) > $P/$b-before.sha256; done
for m in haiku sonnet opus; do
  echo "$m $(claude -p "1" --model $m --setting-sources "" --strict-mcp-config --tools "" --output-format json | python3 -c 'import json,sys; print(*json.load(sys.stdin).get("modelUsage",{}))')"
done > $P/models.txt; claude --version >> $P/models.txt

export P
gen() {  # gen <run> <model> <branch> <dir>
  echo "$(date +%T) start r$1 $2 $3" >> $P/order.log
  (cd $4 && RUN=it24-r$1 WITH_SHORT=1 bash evals/agent_path.sh $2 S7 > /dev/null 2>> $P/gen.err)
  echo "$(date +%T) end r$1 $2 $3" >> $P/order.log
}
export -f gen
for r in $(seq 1 20); do
  if [ $((r % 2)) = 1 ]; then M="haiku sonnet"; else M="sonnet haiku"; fi
  for m in $M; do for i in 0 1 2 3 4 5; do b=${B[$(( (i + r - 1) % 6 ))]}; echo "$r $m $b $(dir $b)"; done; done
done > $P/jobs.txt
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/jobs.txt
missing() { while read r m b T; do [ -s $T/evals/results/it24-r$r/$m/agent+short/S7.md ] || echo "$r $m $b $T"; done < $P/jobs.txt; }
for try in 1 2 3; do
  missing > $P/missing-$try.txt; [ -s $P/missing-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing-$try.txt) jobs" >> $P/order.log
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/missing-$try.txt
done
missing > $P/missing-final.txt
for b in "${B[@]}"; do hashes $(dir $b) > $P/$b-after.sha256; done

for r in $(seq 1 20); do for m in haiku sonnet; do mkdir -p $REPO/evals/results/it24-r$r/$m
  for b in "${B[@]}"; do cp -R $(dir $b)/evals/results/it24-r$r/$m/agent+short $REPO/evals/results/it24-r$r/$m/agent+short-$b; done
done; done
kill $HB; (while sleep 300; do beat "judging"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order.log
for r in $(seq 1 20); do python3 evals/judge.py evals/results/it24-r$r > /dev/null; done
echo "$(date +%T) judge end" >> $P/order.log
