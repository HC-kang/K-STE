# 25차 묶음 A를 skills/k-ste 복사본에 적용한다. 사용법: python3 -I make_bundleA.py <skills/k-ste 폴더> [A1] [A2] [A3]
# 묶음을 주지 않으면 A1, A2, A3을 모두 적용한다. 지울 문자열은 경량화 리뷰 부록 A 7절과 같다.
# 차이 두 곳(코디네이터 결정): A1의 8행은 rewrite.md의 "### 흔한 합리화" 아래에 둔다. A2는 "`확인 필요:`는 "을 남긴다.
import re, sys

d, items = sys.argv[1], sys.argv[2:] or ["A1", "A2", "A3"]
sk_path, rw_path = f"{d}/SKILL.md", f"{d}/references/rewrite.md"
SK, RW = open(sk_path, encoding="utf-8").read(), open(rw_path, encoding="utf-8").read()

def cut(text, s):
    assert text.count(s) == 1, s[:40]
    return text.replace(s, "")

if "A1" in items:
    rat = SK[SK.index("## 흔한 합리화"):SK.index("## 내보내기 전 점검")]
    rows = [l for l in rat.splitlines() if l.startswith('| "')]
    assert len(rows) == 19
    moved = "| 생각 | 실제 |\n|---|---|\n" + "".join(rows[i] + "\n" for i in (0, 1, 2, 3, 4, 5, 7, 8))
    assert len(moved) == 678
    SK = cut(SK, rat)
    assert RW.count("\n## 검수\n") == 1
    RW = RW.replace("\n## 검수\n", "\n### 흔한 합리화\n\n" + moved + "\n## 검수\n")

if "A2" in items:
    for s in ['트리거: "쉽게 바꿔줘", "다듬어줘", "읽기 쉽게", "줄여줘", "K-STE로".\n\n',
              '트리거: "검사해줘", "어디가 문제야", "리뷰해줘", "규칙 위반 찾아줘".\n\n',
              '해석이 갈리는 곳이 있으면 고친 글 아래에 다음 형식으로 붙인다.\n\n```\n확인 필요: <원문 표현>. <가능한 해석 두 가지>.\n```\n\n',
              '해석에 따라 독자의 행동이 달라지는 곳에만 쓴다. 최대 세 개까지 쓴다. ',  # 리뷰 문자열에서 앞의 "`확인 필요:`는 "을 남긴다
              ' 이때는 다음 형식으로 쓴다.\n\n```\n확인 필요: <원문 표현>. <빠진 정보>.\n```\n',
              '- 규칙 열에는 K0-K15만 쓴다. 존재하지 않는 ID를 지어내지 않는다.\n', '- 한 행에 위반 하나를 쓴다.\n',
              '- 원문이 두 가지로 읽히는 곳은 고친 글 열에 "확인 필요: <가능한 해석 두 가지>"라고 쓴다. 해석을 하나로 골라 고치지 않는다.\n']:
        RW = cut(RW, s)
    assert "`확인 필요:`는 문맥상 한 해석만 자연스러우면 쓰지 않는다." in RW

if "A3" in items:
    s = "문서(README, 설계 문서, 런북, 절차서, PR 설명, 장애 보고서, 회의록)는 다음 순서로"
    assert SK.count(s) == 1
    SK = SK.replace(s, "문서는 다음 순서로")

open(sk_path, "w", encoding="utf-8").write(SK)
open(rw_path, "w", encoding="utf-8").write(RW)
