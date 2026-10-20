# 27차 배포분: 묶음 B 가운데 B1만 SKILL.md 본문에 적용한다. B2(K13 완료 동사 문장)와 전체판은 바꾸지 않는다.
# 사용법: python3 -I deploy_B1_skill.py <저장소 폴더>. 문자열은 make_bundleB.py의 B1과 같다.
import re, sys

p = f"{sys.argv[1]}/skills/k-ste/SKILL.md"
SK = open(p, encoding="utf-8").read()
m = re.match(r"---\n.*?\n---\n", SK, re.S)
head, body = SK[:m.end()], SK[m.end():]
for s in [" 지시문이 20어절, 설명문이 25어절을 넘으면 나눌 곳을 찾는다. 길이만 보고 나누지 않는다.", " 명사를 셋 이상 잇지 않는다. 용어로 굳은 복합명사는 예외다.",
          " 헤지는 문장당 하나까지 쓴다.", " 수치에는 단위, 기준, 시점을 쓴다.", " 지루해 보여도 동의어로 바꾸지 않는다.",
          '"10월 1일부터 월간 활성 사용자가 12,000명에서 15,400명으로 늘었습니다."']:
    assert body.count(s) == 1, s[:40]
    body = body.replace(s, "")
assert '("마쳤다", "끝냈다")' in body and "번역 30쪽" in body  # B2는 남긴다
open(p, "w", encoding="utf-8").write(head + body)
