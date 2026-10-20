# 29차 후보: "짧게" 요청의 "중복" 뜻을 바로잡는 문장을 전체판 블록과 rewrite.md에 한 줄씩 넣는다. 사용법: python3 -I make_cand.py <저장소 폴더> <C1|C2>
# C1은 원리 문장(PR)만, C2는 PR 다음 예 문장(EX)을 넣는다. 짧은판 블록, SKILL.md, genres.md, word-swaps.md는 바꾸지 않는다. 다른 문구는 더하지 않는다.
import re, sys

root, cand = sys.argv[1], sys.argv[2]
PR = ' 앞에 나온 주어를 조건절("~하면")에서 다시 쓴 것은 중복이 아니다.'
EX = ' 예를 들어 "이미지 빌드가 끝났는지 확인하고, 실패하면"은 확인이 실패한 경우로도 읽힌다.'
assert (len(PR), len(EX)) == (40, 51)
ADD = {"C1": PR, "C2": PR + EX}[cand]
FULL_AT = '"짧게" 요청은 군말과 중복을 지우는 것이다.'
RW_AT = "2. 중복: 같은 뜻을 두 번 말한 부분."

sp_path, rw_path = f"{root}/prompts/system-prompt.md", f"{root}/skills/k-ste/references/rewrite.md"
SP, RW = open(sp_path, encoding="utf-8").read(), open(rw_path, encoding="utf-8").read()
blk = lambda t, b: re.search(rf"<!-- {b}:start -->\n(.*?)\n<!-- {b}:end -->", t, re.S)
fm, short = blk(SP, "full"), blk(SP, "short").group(1)
assert SP.count(FULL_AT) == 1 and fm.group(1).count(FULL_AT) == 1 and RW.count(RW_AT) == 1
assert PR.strip() not in SP + RW and EX.strip() not in SP + RW

full2 = fm.group(1).replace(FULL_AT, FULL_AT + ADD)
SP2 = SP[:fm.start(1)] + full2 + SP[fm.end(1):]
RW2 = RW.replace(RW_AT, RW_AT + ADD)
# 바뀐 것은 전체판 블록의 한 줄과 rewrite.md의 한 줄뿐이다.
assert blk(SP2, "short").group(1) == short and SP2[:fm.start(1)] == SP[:fm.start(1)] and SP2[fm.start(1) + len(full2):] == SP[fm.end(1):]
for a, b in ((SP, SP2), (RW, RW2)):
    la, lb = a.split("\n"), b.split("\n")
    assert len(la) == len(lb) and sum(x != y for x, y in zip(la, lb)) == 1 and len(b) - len(a) == len(ADD)
open(sp_path, "w", encoding="utf-8").write(SP2)
open(rw_path, "w", encoding="utf-8").write(RW2)
