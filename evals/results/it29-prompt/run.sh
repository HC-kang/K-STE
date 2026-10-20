#!/usr/bin/env bash
# 29차 생성과 판정. 저장소 루트에서 `caffeinate -i bash evals/results/it29-prompt/run.sh`로 실행한다.
# dirs.txt(구성과 임시 폴더)는 먼저 만든다: 구성마다 `git archive HEAD | tar -x -C $(mktemp -d)`를 하고,
# C1, C2 폴더에만 `python3 -I make_cand.py <폴더> <C1|C2>`를 실행한다. A는 기준 구성(eb19968, 다섯 파일은 1812a02와 같음)이다.
# 묶음 1: 구성 A C1 C2, 조건 full과 agent+short. 묶음 2: S23 용어집 배치 다섯 개(구성 A). 묶음 3: S21 S22, 조건 base full agent+short(구성 A).
# 확인 실행은 같은 파일을 환경 변수로 부른다: TAG(파일 이름 뒤에 붙음), CONDS, TWENTY, TWENTY_R, THREE_FULL, THREE_AS, THREE_R, B23=0.
#   예: TAG=c1 CONDS=agent+short TWENTY="S7" TWENTY_R="21 40" THREE_FULL="" THREE_AS="" B23=0 bash evals/results/it29-prompt/run.sh
set -u
REPO=$(pwd); P=$REPO/evals/results/it29-prompt
TAG=${TAG:-}; X=${TAG:+-$TAG}
CONDS=${CONDS:-"full agent+short"}
TWENTY=${TWENTY-"S5 S6 S7 S20"}; TWENTY_R=${TWENTY_R:-"1 20"}
THREE_FULL=${THREE_FULL-"S1 S2 S3 S4 S8 S9 S10 S11 S12 S13 S14 S15 S16 S17 S18 S19"}
THREE_AS=${THREE_AS-"S9 S14"}; THREE_R=${THREE_R:-"1 3"}
B23=${B23:-1}; B23_R="1 10"
F="prompts/system-prompt.md skills/k-ste/SKILL.md skills/k-ste/references/genres.md skills/k-ste/references/rewrite.md skills/k-ste/references/word-swaps.md"
blk() { awk "/<!-- $1:start -->/{f=1;next}/<!-- $1:end -->/{f=0}f" prompts/system-prompt.md | shasum -a 256 | cut -d' ' -f1; }
hashes() { (cd $1 && shasum -a 256 $F && echo "$(blk short)  short-block" && echo "$(blk full)  full-block"); }
dir() { awk -v b=$1 '$1==b{print $2}' $P/dirs.txt; }
beat() { orca orchestration send --from term_fd55a0c9-b440-429c-bfa9-5c142876cb6d --type heartbeat --subject "alive" \
  --task-id task_d9e85186d152 --dispatch-id ctx_9f0f168a2d1a --phase "$1" > /dev/null 2>&1; }
in_r() { [ $1 -ge ${2% *} ] && [ $1 -le ${2#* } ]; }
rot() { local k=$1; shift; local a=("$@"); local n=${#a[@]}; for i in $(seq 0 $((n - 1))); do printf '%s ' ${a[$(((i + k) % n))]}; done; }

# 작업 하나는 (회차, 조건, 모델, 시나리오, 구성)이다. 같은 (회차, 조건, 모델, 시나리오)의 세 구성은 이어진 작업이다.
# 구성 순서는 회차마다 A C1 C2, C1 C2 A, C2 A C1을 돈다. 홀수 회차는 haiku와 full을, 짝수 회차는 sonnet과 agent+short를 먼저 둔다.
# 묶음 2는 (회차, 모델)마다 다섯 배치를 이어서 두고 배치 순서를 회차마다 돌린다. 묶음 3은 (회차, 모델, 시나리오)마다 세 조건을 이어서 두고 조건 순서를 회차마다 돌린다.
for r in $(seq 1 40); do
  if [ $((r % 2)) = 1 ]; then M="haiku sonnet"; C="$CONDS"; else M="sonnet haiku"; C=$(rot 1 $CONDS); fi
  V=$(rot $(((r - 1) % 3)) A C1 C2)
  for c in $C; do
    S=""; in_r $r "$TWENTY_R" && S="$TWENTY"
    if in_r $r "$THREE_R"; then [ $c = full ] && S="$S $THREE_FULL" || S="$S $THREE_AS"; fi
    for m in $M; do for s in $S; do for v in $V; do echo "$r $c $m $s $v $(dir $v)"; done; done; done
  done
  if [ $B23 = 1 ] && in_r $r "$B23_R"; then
    for m in $M; do for b in $(rot $(((r - 1) % 5)) G-sys-base G-sys-full G-inline G-ptr G-file); do echo "$r $b $m S23 A $(dir A)"; done; done
    for m in $M; do for s in S21 S22; do for c in $(rot $(((r - 1) % 3)) base full agent+short); do echo "$r $c $m $s A $(dir A)"; done; done; done
  fi
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
for v in A C1 C2; do hashes $(dir $v) > $P/$v-before$X.sha256; done

export P X
gen() {  # gen <run> <cond> <model> <sid> <A|C1|C2> <dir>
  echo "$(date +%T) start r$1 $2 $3 $4 $5" >> $P/order$X.log
  case $2 in
    full|base) (cd $6 && RUN=it29-r$1 bash evals/run.sh $2 $3 $4 >> $P/gen.out 2>> $P/gen.err) ;;
    agent+short) (cd $6 && RUN=it29-r$1 WITH_SHORT=1 bash evals/agent_path.sh $3 $4 >> $P/gen.out 2>> $P/gen.err) ;;
    G-*) (cd $6 && RUN=it29-r$1 bash $P/glossary.sh $2 $3 >> $P/gen.out 2>> $P/gen.err) ;;
  esac
  echo "$(date +%T) end r$1 $2 $3 $4 $5" >> $P/order$X.log
}
export -f gen
# 이 워커만 평가를 실행한다. 작업 하나는 claude -p 하나이므로 동시 claude -p는 6개 이하다.
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/jobs$X.txt
# 출력이 없거나 API 오류 문자열로 시작하는 작업을 다시 생성한다(최대 3번).
missing() { while read r c m s v T; do o=$T/evals/results/it29-r$r/$m/$c/$s.md; { [ -s $o ] && ! grep -q '^API Error' $o; } || echo "$r $c $m $s $v $T"; done < $P/jobs$X.txt; }
for try in 1 2 3; do
  missing > $P/missing$X-$try.txt; [ -s $P/missing$X-$try.txt ] || break
  echo "$(date +%T) retry $try: $(wc -l < $P/missing$X-$try.txt) jobs" >> $P/order$X.log
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/missing$X-$try.txt
done
missing > $P/missing$X-final.txt
hashes $REPO > $P/worktree-after$X.sha256
for v in A C1 C2; do hashes $(dir $v) > $P/$v-after$X.sha256; done

# 출력은 파일 단위로 복사한다(확인 실행이 기존 폴더를 덮지 않게). trace.txt는 임시 폴더의 것이 모든 줄을 가진다.
while read r c m s v T; do
  src=$T/evals/results/it29-r$r/$m/$c; dst=$REPO/evals/results/it29-r$r/$m/$c-$v; mkdir -p $dst
  [ -f $src/$s.md ] && cp $src/$s.md $dst/; [ -f $src/trace.txt ] && cp $src/trace.txt $dst/
done < $P/jobs$X.txt

kill $HB; (while sleep 300; do beat "judging$X: $(grep -c ' judged ' $P/order$X.log 2>/dev/null) rounds"; done) & HB=$!
echo "$(date +%T) judge start" >> $P/order$X.log
# judge.py는 스레드 6개로 claude -p를 실행한다. bin/claude가 동시 실행을 6개 이하로 막으므로 회차 셋을 함께 판정해도 6개 이하다.
# --cond와 --sid로 이번 작업의 출력만 판정한다(확인 실행이 본 실행의 판정을 바꾸지 않게). S3 S4 S8 S9 S23은 judge.py에 판정이 없다.
judge_round() {
  local r=$1 SIDS CS
  SIDS=$(awk -v r=$r '$1==r{print $4}' $P/jobs$X.txt | sort -u | paste -sd, -)
  CS=$(awk -v r=$r '$1==r{print $2"-"$5}' $P/jobs$X.txt | sort -u | paste -sd, -)
  PATH=$P/bin:$PATH KSTE_SLOTS=6 KSTE_SLOT_DIR=${TMPDIR:-/tmp}/kste-it29-slots \
    python3 evals/judge.py evals/results/it29-r$r --cond $CS --sid $SIDS > /dev/null
  echo "$(date +%T) judged r$r" >> $P/order$X.log
}
export -f judge_round
cut -d' ' -f1 $P/jobs$X.txt | sort -un | xargs -P 3 -I{} bash -c 'judge_round {}'
echo "$(date +%T) judge end" >> $P/order$X.log
# 판정 오류(error)만 27-28차 rejudge 방식으로 다시 판정한다.
PATH=$P/bin:$PATH KSTE_SLOTS=6 KSTE_SLOT_DIR=${TMPDIR:-/tmp}/kste-it29-slots python3 $P/rejudge.py >> $P/order$X.log 2>&1
echo "$(date +%T) rejudge end" >> $P/order$X.log
