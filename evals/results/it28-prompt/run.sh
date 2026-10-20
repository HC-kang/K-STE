#!/usr/bin/env bash
# 28차 생성과 판정(full만). 저장소 루트에서 `caffeinate -i bash evals/results/it28-prompt/run.sh`로 실행한다.
# dirs.txt(구성과 임시 폴더)는 먼저 만든다: 구성마다 `git archive HEAD | tar -x -C $(mktemp -d)`를 하고,
# 후보(B) 폴더에만 `python3 -I make_fullB1.py <폴더>`를 실행한다. A는 기준 구성(1812a02)이다.
# 확인 실행은 같은 파일을 환경 변수로 부른다: TAG(파일 이름 뒤에 붙음), TWENTY, TWENTY_R, SIX, SIX_R.
#   예: TAG=c1 TWENTY="S5" TWENTY_R="21 40" SIX="" bash evals/results/it28-prompt/run.sh
set -u
REPO=$(pwd); P=$REPO/evals/results/it28-prompt
TAG=${TAG:-}; X=${TAG:+-$TAG}
TWENTY=${TWENTY-"S5 S6 S7"}; TWENTY_R=${TWENTY_R:-"1 20"}
SIX=${SIX-"S1 S2 S3 S4 S8 S9 S10 S11 S12 S13 S14 S15 S16 S17 S18 S19"}; SIX_R=${SIX_R:-"1 6"}
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
blk() { awk "/<!-- $1:start -->/{f=1;next}/<!-- $1:end -->/{f=0}f" prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1; }
hashes() { (cd $1 && shasum -a 256 $F && echo "$(blk short)  short-block" && echo "$(blk full)  full-block"); }
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
beat() { orca orchestration send --from term_94b841a0-5fb4-40ef-9d32-b8b616d8e161 --type heartbeat --subject "alive" \
  --task-id task_f1596da28b5d --dispatch-id ctx_2148c2f3280e --phase "$1" > /dev/null 2>&1; }

# 작업 하나는 (회차, 모델, 시나리오, 구성)이다. 같은 (회차, 모델, 시나리오)의 두 구성은 이어진 작업이다.
# 홀수 회차는 A와 haiku를 먼저 두고, 짝수 회차는 B와 sonnet을 먼저 둔다.
for r in $(seq 1 40); do
  S=""; [ $r -ge ${TWENTY_R% *} ] && [ $r -le ${TWENTY_R#* } ] && S="$TWENTY"
  [ $r -ge ${SIX_R% *} ] && [ $r -le ${SIX_R#* } ] && S="$S $SIX"
  [ -n "${S// /}" ] || continue
  if [ $((r % 2)) = 1 ]; then V="A B"; M="haiku sonnet"; else V="B A"; M="sonnet haiku"; fi
  for m in $M; do for s in $S; do for v in $V; do echo "$r full $m $s $v $(dir $v)"; done; done; done
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
gen() {  # gen <run> full <model> <sid> <A|B> <dir>
  echo "$(date +%T) start r$1 $3 $4 $5" >> $P/order$X.log
  (cd $6 && RUN=it28-r$1 bash evals/run.sh full $3 $4 >> $P/gen.out 2>> $P/gen.err)
  echo "$(date +%T) end r$1 $3 $4 $5" >> $P/order$X.log
}
export -f gen
# 이 워커만 평가를 실행한다. 작업 하나는 claude -p 하나이므로 동시 claude -p는 6개 이하다.
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/jobs$X.txt
# 출력이 없거나 API 오류 문자열로 시작하는 작업을 다시 생성한다(최대 3번).
missing() { while read r c m s v T; do o=$T/evals/results/it28-r$r/$m/full/$s.md; { [ -s $o ] && ! grep -q '^API Error' $o; } || echo "$r $c $m $s $v $T"; done < $P/jobs$X.txt; }
for try in 1 2 3; do
  missing > $P/missing$X-$try.txt; [ -s $P/missing$X-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing$X-$try.txt) jobs" >> $P/order$X.log
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/missing$X-$try.txt
done
missing > $P/missing$X-final.txt
hashes $REPO > $P/worktree-after$X.sha256
for v in A B; do hashes $(dir $v) > $P/$v-after$X.sha256; done

# 출력은 파일 단위로 복사한다(확인 실행이 기존 폴더를 덮지 않게).
while read r c m s v T; do
  dst=$REPO/evals/results/it28-r$r/$m/full-$v; mkdir -p $dst
  [ -f $T/evals/results/it28-r$r/$m/full/$s.md ] && cp $T/evals/results/it28-r$r/$m/full/$s.md $dst/
done < $P/jobs$X.txt

kill $HB; (while sleep 300; do beat "judging$X: $(grep -c ' judged ' $P/order$X.log 2>/dev/null) rounds"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order$X.log
# judge.py는 스레드 6개로 claude -p를 실행한다. bin/claude가 동시 실행을 6개 이하로 막는다.
# --cond와 --sid로 이번 작업의 출력만 판정한다(확인 실행이 본 실행의 판정을 바꾸지 않게).
for r in $(cut -d' ' -f1 $P/jobs$X.txt | sort -un); do
  SIDS=$(awk -v r=$r '$1==r{print $4}' $P/jobs$X.txt | sort -u | paste -sd, -)
  PATH=$P/bin:$PATH KSTE_SLOTS=6 KSTE_SLOT_DIR=${TMPDIR:-/tmp}/kste-it28-slots \
    python3 evals/judge.py evals/results/it28-r$r --cond full-A,full-B --sid $SIDS > /dev/null
  echo "$(date +%T) judged r$r" >> $P/order$X.log
done
echo "$(date +%T) judge end" >> $P/order$X.log
# 판정 오류(error)만 27차 rejudge 방식으로 다시 판정한다.
PATH=$P/bin:$PATH KSTE_SLOTS=6 KSTE_SLOT_DIR=${TMPDIR:-/tmp}/kste-it28-slots python3 $P/rejudge.py >> $P/order$X.log 2>&1
echo "$(date +%T) rejudge end" >> $P/order$X.log
