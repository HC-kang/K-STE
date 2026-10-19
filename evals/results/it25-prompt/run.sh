#!/usr/bin/env bash
# 25차 생성과 판정. 저장소 루트에서 `bash evals/results/it25-prompt/run.sh`로 실행한다.
# dirs.txt(구성과 임시 폴더)는 먼저 만든다: 구성마다 `git archive HEAD | tar -x -C $(mktemp -d)`를 하고,
# 후보 폴더에만 `python3 -I make_bundleA.py <폴더>/skills/k-ste`를 실행한다.
set -u
REPO=$(pwd); P=$REPO/evals/results/it25-prompt
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
hashes() { (cd $1 && shasum -a 256 $F && echo "$(awk '/<!-- short:start -->/{f=1;next}/<!-- short:end -->/{f=0}f' prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1)  short-block"); }
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
beat() { orca orchestration send --from term_562ef0ff-a833-41f1-994b-84e5fe8f1de2 --type heartbeat --subject "alive" \
  --task-id task_dc2856f83407 --dispatch-id ctx_1045c71e4afd --phase "$1" > /dev/null 2>&1; }
(while sleep 300; do beat "generating: $(grep -c ' end ' $P/order.log 2>/dev/null)/424 jobs"; done) & HB=$!
trap 'kill $HB 2>/dev/null' EXIT

SHA=$(git rev-parse --short HEAD)
for f in $F; do echo "$(git show $SHA:$f | shasum -a 256 | cut -d' ' -f1)  $f"; done > $P/$SHA.sha256
hashes $REPO > $P/worktree-before.sha256
for v in v4 cand; do hashes $(dir $v) > $P/$v-before.sha256; done
for m in haiku sonnet opus; do
  echo "$m $(claude -p "1" --model $m --setting-sources "" --strict-mcp-config --tools "" --output-format json | python3 -c 'import json,sys; print(*json.load(sys.stdin).get("modelUsage",{}))')"
done > $P/models.txt; claude --version >> $P/models.txt

export P
gen() {  # gen <run> <model> <sid> <v4|cand> <dir>
  echo "$(date +%T) start r$1 $2 $3 $4" >> $P/order.log
  (cd $5 && RUN=it25-r$1 WITH_SHORT=1 bash evals/agent_path.sh $2 $3 > /dev/null 2>> $P/gen.err)
  echo "$(date +%T) end r$1 $2 $3 $4" >> $P/order.log
}
export -f gen
TEN="S5 S6 S7 S9 S14 S10 S13"; THREE="S1 S2 S3 S4 S8 S11 S12 S15 S16 S17 S18 S19"
for r in $(seq 1 10); do
  if [ $((r % 2)) = 1 ]; then V="v4 cand"; M="haiku sonnet"; else V="cand v4"; M="sonnet haiku"; fi
  S=$TEN; [ $r -le 3 ] && S="$TEN $THREE"
  for m in $M; do for s in $S; do for v in $V; do echo "$r $m $s $v $(dir $v)"; done; done; done
done > $P/jobs.txt
# 다른 워커와 함께 실행하므로 동시 claude -p는 3개 이하다(agent_path.sh는 시나리오 하나에 claude -p 하나).
xargs -P 3 -L 1 bash -c 'gen "$@"' _ < $P/jobs.txt
missing() { while read r m s v T; do [ -s $T/evals/results/it25-r$r/$m/agent+short/$s.md ] || echo "$r $m $s $v $T"; done < $P/jobs.txt; }
for try in 1 2 3; do
  missing > $P/missing-$try.txt; [ -s $P/missing-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing-$try.txt) jobs" >> $P/order.log
  xargs -P 3 -L 1 bash -c 'gen "$@"' _ < $P/missing-$try.txt
done
missing > $P/missing-final.txt
hashes $REPO > $P/worktree-after.sha256
for v in v4 cand; do hashes $(dir $v) > $P/$v-after.sha256; done

for r in $(seq 1 10); do for m in haiku sonnet; do mkdir -p $REPO/evals/results/it25-r$r/$m
  for v in v4 cand; do cp -R $(dir $v)/evals/results/it25-r$r/$m/agent+short $REPO/evals/results/it25-r$r/$m/agent+short-$v; done
done; done
kill $HB; (while sleep 300; do beat "judging: $(cat $REPO/evals/results/it25-r*/judge.jsonl 2>/dev/null | wc -l | tr -d ' ')/348"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order.log
# judge.py는 스레드 6개로 claude -p를 실행한다. bin/claude가 동시 실행을 3개로 막는다.
for r in $(seq 1 10); do PATH=$P/bin:$PATH python3 evals/judge.py evals/results/it25-r$r > /dev/null; done
echo "$(date +%T) judge end" >> $P/order.log
