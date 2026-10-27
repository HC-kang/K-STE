#!/usr/bin/env bash
# 30차 날짜 시나리오 재측정(it30d). 저장소 루트에서 `caffeinate -i bash evals/results/it30-prompt/run-dates.sh`로 실행한다.
# claude -p는 --system-prompt를 바꿔도 실행일("Today's date is 2026-10-28")을 받는다. 그래서 시나리오의 예정일과 기한이 지난 날짜가 됐다.
# HEAD를 임시 폴더에 풀고 시나리오 여섯 개와 S18 판정문의 날짜만 뒤로 미룬 뒤, 그 폴더에서 생성하고 판정한다.
# 미루는 날 수: S15는 10일(회의일이 실행 전날이 된다), 나머지는 14일(요일이 그대로다). 저장소의 시나리오는 바꾸지 않는다.
set -u
REPO=$(pwd); P=$REPO/evals/results/it30-prompt; SIDS="S12 S13 S15 S16 S17 S18"
T=$(mktemp -d); git archive HEAD | tar -x -C $T; echo "$T" > $P/dates-dir.txt
sed -i '' 's#10/20 10:00#11/3 10:00#' $T/evals/scenarios/S12.txt
sed -i '' 's#10월 22일#11월 5일#' $T/evals/scenarios/S13.txt
sed -i '' 's#10월 17일#10월 27일#; s#10월 21일#10월 31일#; s#10월 22일#11월 1일#; s#10월 23일#11월 2일#' $T/evals/scenarios/S15.txt
sed -i '' 's#10/21(수)#11/4(수)#' $T/evals/scenarios/S16.txt
sed -i '' 's#10/22 09:00#11/5 09:00#' $T/evals/scenarios/S17.txt
for f in $T/evals/scenarios/S18.txt $T/evals/judge.py; do
  sed -i '' 's#10월 22일#11월 5일#g; s#10월 23일#11월 6일#g; s#10월 26일#11월 9일#g; s#10월 30일#11월 13일#g' $f
done
(for f in $SIDS; do diff $REPO/evals/scenarios/$f.txt $T/evals/scenarios/$f.txt; done; diff $REPO/evals/judge.py $T/evals/judge.py) > $P/dates.diff
CLAUDE_CODE_DATE=$(cd /tmp && claude -p "Quote verbatim the line in your context that states today's date, nothing else." --model haiku --setting-sources "" --strict-mcp-config --system-prompt "You are a helpful assistant." --tools "")
echo "$CLAUDE_CODE_DATE" > $P/dates-today.txt

for r in 1 2 3; do i=0; for s in $SIDS; do
  [ $((r % 2)) = 1 ] && M="haiku sonnet" || M="sonnet haiku"
  for m in $M; do for c in $(printf '%s\n' base short full agent+short | awk -v k=$(((i + r) % 4)) '{a[NR-1]=$0} END{for(j=0;j<NR;j++) print a[(j+k)%NR]}'); do echo "$r $c $m $s"; done; done
  i=$((i + 1))
done; done > $P/dates-jobs.txt

gen() {
  echo "$(date +%T) start r$1 $2 $3 $4" >> $P/dates-order.log
  case $2 in
    agent+short) (cd $T && RUN=it30d-r$1 WITH_SHORT=1 bash evals/agent_path.sh $3 $4 >> $P/dates-gen.out 2>> $P/dates-gen.err) ;;
    *) (cd $T && RUN=it30d-r$1 bash evals/run.sh $2 $3 $4 >> $P/dates-gen.out 2>> $P/dates-gen.err) ;;
  esac
  echo "$(date +%T) end r$1 $2 $3 $4" >> $P/dates-order.log
}
export -f gen; export P T
xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/dates-jobs.txt
missing() { while read r c m s; do o=$T/evals/results/it30d-r$r/$m/$c/$s.md; { [ -s $o ] && ! grep -q '^API Error' $o; } || echo "$r $c $m $s"; done < $P/dates-jobs.txt; }
for try in 1 2 3; do
  missing > $P/dates-missing-$try.txt; [ -s $P/dates-missing-$try.txt ] || break
  xargs -P 6 -L 1 bash -c 'gen "$@"' _ < $P/dates-missing-$try.txt
done
missing > $P/dates-missing-final.txt
echo "$(date +%T) judge start" >> $P/dates-order.log
for r in 1 2 3; do (cd $T && python3 evals/judge.py evals/results/it30d-r$r > /dev/null); done
echo "$(date +%T) judge end" >> $P/dates-order.log
for r in 1 2 3; do cp -R $T/evals/results/it30d-r$r $REPO/evals/results/; done
