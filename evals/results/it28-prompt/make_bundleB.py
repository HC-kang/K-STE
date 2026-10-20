# 27차 묶음 B(B1, B2)를 저장소 복사본에 적용한다. 사용법: python3 -I make_bundleB.py <저장소 폴더>
# 지울 문자열은 경량화 리뷰 부록 A 7절의 NOEV, B1s, B1e, K11 예, "지루해 보여도"와 같다. 다른 문구는 더하지 않는다.
# SKILL.md는 본문(머리말 뒤)에서, prompts/system-prompt.md는 full 블록 안에서만 지운다. 짧은판 블록은 바꾸지 않는다.
import re, sys

root = sys.argv[1]
sk_path, sp_path = f"{root}/skills/k-ste/SKILL.md", f"{root}/prompts/system-prompt.md"
SK, SP = open(sk_path, encoding="utf-8").read(), open(sp_path, encoding="utf-8").read()

NOEV = [" 20어절, 설명문{} 25어절을 넘으면 나눌 곳을 찾는다. 길이만 보고 나누지 않는다.", " 명사를 셋 이상 잇지 않는다. 용어로 굳은 복합명사는 예외다.",
        " 헤지는 문장당 하나까지 쓴다.", " 수치에는 단위, 기준, 시점을 쓴다."]
B1s = ' 일이 끝났다는 말("마쳤다", "끝냈다")을 쓸 때는, 결과가 사실에 있으면 같은 문장이나 바로 다음 문장에 결과를 쓴다.'
B1e = ' 사실이 "번역 30쪽 검수, 오류 2건 수정"이면 "번역 검수를 마쳤습니다" 대신 "번역 30쪽을 검수했고 오류 2건을 고쳤습니다"라고 쓴다.'
K11e = '"10월 1일부터 월간 활성 사용자가 12,000명에서 15,400명으로 늘었습니다."'

def cut(text, s):
    assert text.count(s) == 1, s[:40]
    return text.replace(s, "")

m = re.match(r"---\n.*?\n---\n", SK, re.S)
head, body = SK[:m.end()], SK[m.end():]
for s in [" 지시문이" + NOEV[0].format("이"), *NOEV[1:], " 지루해 보여도 동의어로 바꾸지 않는다.", B1s, B1e]:
    body = cut(body, s)
body = cut(body, K11e)  # K11 예 칸을 비운다: "| ... 유지한다. |  |"
assert "| K11 | 한 글 안에서 문체를 섞지 않는다. 목록, 표, `확인 필요:` 줄도 본문과 같은 문체로 쓴다. 재작성은 원문의 문체를 유지한다. |  |\n" in body

fm = re.search(r"<!-- full:start -->\n(.*?)\n<!-- full:end -->", SP, re.S)
short = re.search(r"<!-- short:start -->\n(.*?)\n<!-- short:end -->", SP, re.S).group(1)
full = fm.group(1)
for s in [" 지시문" + NOEV[0].format(""), *NOEV[1:], B1s]:
    full = cut(full, s)
SP2 = SP[:fm.start(1)] + full + SP[fm.end(1):]
assert re.search(r"<!-- short:start -->\n(.*?)\n<!-- short:end -->", SP2, re.S).group(1) == short
assert SP2[:fm.start(1)] == SP[:fm.start(1)] and SP2[fm.start(1) + len(full):] == SP[fm.end(1):]

open(sk_path, "w", encoding="utf-8").write(head + body)
open(sp_path, "w", encoding="utf-8").write(SP2)
