# 28차 후보: 전체판(full 블록)에서 B1 문자열 네 개만 지운다. 사용법: python3 -I make_fullB1.py <저장소 폴더>
# 지울 문자열은 27차 make_bundleB.py의 full 블록 부분과 같다(K2 어절 수치와 "길이만 보고 나누지 않는다", K3 명사 셋, K6 헤지, K11 수치의 단위).
# K13 완료 동사 문장(make_bundleB.py의 B1s)은 지우지 않는다. 짧은판 블록, skills/, references는 바꾸지 않는다. 다른 문구는 더하지 않는다.
import re, sys

sp_path = f"{sys.argv[1]}/prompts/system-prompt.md"
SP = open(sp_path, encoding="utf-8").read()

B1 = [" 지시문 20어절, 설명문 25어절을 넘으면 나눌 곳을 찾는다. 길이만 보고 나누지 않는다.", " 명사를 셋 이상 잇지 않는다. 용어로 굳은 복합명사는 예외다.",
      " 헤지는 문장당 하나까지 쓴다.", " 수치에는 단위, 기준, 시점을 쓴다."]
B1s = ' 일이 끝났다는 말("마쳤다", "끝냈다")을 쓸 때는, 결과가 사실에 있으면 같은 문장이나 바로 다음 문장에 결과를 쓴다.'

fm = re.search(r"<!-- full:start -->\n(.*?)\n<!-- full:end -->", SP, re.S)
short = re.search(r"<!-- short:start -->\n(.*?)\n<!-- short:end -->", SP, re.S).group(1)
full = fm.group(1)
for s in B1:
    assert full.count(s) == 1, s[:40]
    full = full.replace(s, "")
assert full.count(B1s) == 1  # K13 완료 동사 문장은 남는다
SP2 = SP[:fm.start(1)] + full + SP[fm.end(1):]
assert re.search(r"<!-- short:start -->\n(.*?)\n<!-- short:end -->", SP2, re.S).group(1) == short
assert SP2[:fm.start(1)] == SP[:fm.start(1)] and SP2[fm.start(1) + len(full):] == SP[fm.end(1):]
assert len(SP) - len(SP2) == sum(map(len, B1))
open(sp_path, "w", encoding="utf-8").write(SP2)
