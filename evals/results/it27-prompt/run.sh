#!/usr/bin/env bash
# 27차 생성과 판정. 저장소 루트에서 `bash evals/results/it27-prompt/run.sh`로 실행한다.
# dirs.txt(구성과 임시 폴더)는 먼저 만든다: 구성마다 `git archive HEAD | tar -x -C $(mktemp -d)`를 하고,
# 후보(B) 폴더에만 `python3 -I make_bundleB.py <폴더>`를 실행한다. A는 기준 구성(3130a1b)이다.
# 확인 실행은 같은 파일을 환경 변수로 부른다: TAG(파일 이름 뒤에 붙음), CONDS, TEN, TEN_R, THREE, THREE_R.
#   예: TAG=c1 CONDS=full TEN="S7" TEN_R="11 20" THREE="" bash evals/results/it27-prompt/run.sh
set -u
REPO=$(pwd); P=$REPO/evals/results/it27-prompt
TAG=${TAG:-}; X=${TAG:+-$TAG}
CONDS=${CONDS:-"full agent+short"}
TEN=${TEN-"S5 S6 S7 S12 S16"}; TEN_R=${TEN_R:-"1 10"}
THREE=${THREE-"S1 S2 S3 S4 S8 S9 S10 S11 S13 S14 S15 S17 S18 S19"}; THREE_R=${THREE_R:-"1 3"}
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
blk() { awk "/<!-- $1:start -->/{f=1;next}/<!-- $1:end -->/{f=0}f" prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1; }
hashes() { (cd $1 && shasum -a 256 $F && echo "$(blk short)  short-block" && echo "$(blk full)  full-block"); }
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
beat() { orca orchestration send --from term_ebe0e3a2-0d7d-4aa3-8d6a-dcfc252f1d10 --type heartbeat --subject "alive" \
  --task-id task_c0ebb6408800 --dispatch-id ctx_15db390190fc --phase "$1" > /dev/null 2>&1; }

# 작업 하나는 (회차, 조건, 모델, 시나리오, 구성)이다. 같은 (회차, 조건, 모델, 시나리오)의 두 구성은 이어진 작업이다.
# 홀수 회차는 A, haiku, full을 먼저 두고, 짝수 회차는 B, sonnet, agent+short를 먼저 둔다.
rev() { local o=""; for x in $1; do o="$x $o"; done; echo $o; }
for r in $(seq 1 20); do
  S=""; [ $r -ge ${TEN_R% *} ] && [ $r -le ${TEN_R#* } ] && S="$TEN"
  [ $r -ge ${THREE_R% *} ] && [ $r -le ${THREE_R#* } ] && S="$S $THREE"
  [ -n "${S// /}" ] || continue
  if [ $((r % 2)) = 1 ]; then V="A B"; M="haiku sonnet"; C="$CONDS"; else V="B A"; M="sonnet haiku"; C=$(rev "$CONDS"); fi
  for c in $C; do for m in $M; do for s in $S; do for v in $V; do echo "$r $c $m $s $v $(dir $v)"; done; done; done; done
done > $P/jobs$X.txt
N=$(wc -l < $P/jobs$X.txt | tr -d ' ')
(while sleep 300; do beat "generating$X: $(grep -c ' end ' $P/order$X.log 2>/dev/null)/$N jobs"; done) & HB=$!
trap 'kill $HB 2>/dev/null' EXIT

if [ -z "$TAG" ]; then
  SHA=$(git rev-parse --short HEAD)
  for f in $F; do echo "$(git show $SHA:$f | shasum -a 256 | cut -d' ' -f1)  $f"; done > $P/$SHA.sha256
  for m in haiku sonnet opus; do
    echo "$m $(claude -p "1" --model $m --setting-sources "" --strict-mcp-config --tools "" --output-format json | python3 -c 'import json,sys; print(*json.load(sys.stdin).get("modelUsage",{}))')"
  done > $P/models.txt; claude --version >> $P/models.txt
fi
hashes $REPO > $P/worktree-before$X.sha256
for v in A B; do hashes $(dir $v) > $P/$v-before$X.sha256; done

export P X
gen() {  # gen <run> <cond> <model> <sid> <A|B> <dir>
  echo "$(date +%T) start r$1 $2 $3 $4 $5" >> $P/order$X.log
  if [ $2 = full ]; then (cd $6 && RUN=it27-r$1 bash evals/run.sh full $3 $4 >> $P/gen.out 2>> $P/gen.err)
  else (cd $6 && RUN=it27-r$1 WITH_SHORT=1 bash evals/agent_path.sh $3 $4 >> $P/gen.out 2>> $P/gen.err); fi
  echo "$(date +%T) end r$1 $2 $3 $4 $5" >> $P/order$X.log
}
export -f gen
# 이 워커만 평가를 실행한다. 작업 하나는 claude -p 하나이므로 동시 claude -p는 6개 이하다.
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/jobs$X.txt
missing() { while read r c m s v T; do [ -s $T/evals/results/it27-r$r/$m/$c/$s.md ] || echo "$r $c $m $s $v $T"; done < $P/jobs$X.txt; }
for try in 1 2 3; do
  missing > $P/missing$X-$try.txt; [ -s $P/missing$X-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing$X-$try.txt) jobs" >> $P/order$X.log
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/missing$X-$try.txt
done
missing > $P/missing$X-final.txt
hashes $REPO > $P/worktree-after$X.sha256
for v in A B; do hashes $(dir $v) > $P/$v-after$X.sha256; done

# 출력은 파일 단위로 복사한다(확인 실행이 기존 폴더를 덮지 않게). trace.txt는 임시 폴더의 것이 모든 줄을 가진다.
while read r c m s v T; do
  src=$T/evals/results/it27-r$r/$m/$c; dst=$REPO/evals/results/it27-r$r/$m/$c-$v; mkdir -p $dst
  [ -f $src/$s.md ] && cp $src/$s.md $dst/; [ -f $src/trace.txt ] && cp $src/trace.txt $dst/
done < $P/jobs$X.txt

kill $HB; (while sleep 300; do beat "judging$X: $(grep -c ' judged ' $P/order$X.log 2>/dev/null) rounds"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order$X.log
# judge.py는 스레드 6개로 claude -p를 실행한다. bin/claude가 동시 실행을 6개 이하로 막는다.
# --cond와 --sid로 이번 작업의 출력만 판정한다(확인 실행이 본 실행의 판정을 바꾸지 않게).
CS=$(for c in $CONDS; do printf '%s-A,%s-B,' $c $c; done); CS=${CS%,}
for r in $(cut -d' ' -f1 $P/jobs$X.txt | sort -un); do
  SIDS=$(awk -v r=$r '$1==r{print $4}' $P/jobs$X.txt | sort -u | paste -sd, -)
  PATH=$P/bin:$PATH KSTE_SLOTS=6 KSTE_SLOT_DIR=${TMPDIR:-/tmp}/kste-it27-slots \
    python3 evals/judge.py evals/results/it27-r$r --cond $CS --sid $SIDS > /dev/null
  echo "$(date +%T) judged r$r" >> $P/order$X.log
done
echo "$(date +%T) judge end" >> $P/order$X.log
