# 27차: 25차 파일에 전체판(full 블록)을 더했다. 경량화 리뷰 부록 A와 같은 방식으로 글자 수(Python len)를 센다. 사용법: python3 -I measure_size.py <이름>=<저장소 폴더> ...
import re, sys

def parts(root):
    sk = open(f"{root}/skills/k-ste/SKILL.md", encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", sk, re.S)
    sp = open(f"{root}/prompts/system-prompt.md", encoding="utf-8").read()
    d = {"desc": re.search(r"^description: (.*)$", m.group(1), re.M).group(1), "SKILL": sk[m.end():],
         "short": re.search(r"<!-- short:start -->\n(.*?)\n<!-- short:end -->", sp, re.S).group(1),
         "full": re.search(r"<!-- full:start -->\n(.*?)\n<!-- full:end -->", sp, re.S).group(1),
         "rewrite": open(f"{root}/skills/k-ste/references/rewrite.md", encoding="utf-8").read()}
    d["new path"] = len(d["desc"]) + len(d["short"]) + len(d["SKILL"])
    d["rewrite path"] = d["new path"] + len(d["rewrite"])
    return {k: v if isinstance(v, int) else len(v) for k, v in d.items()}

R = {a.split("=", 1)[0]: parts(a.split("=", 1)[1]) for a in sys.argv[1:]}
keys = list(next(iter(R.values())))
print(f"{'':14s}" + "".join(f"{n:>10s}" for n in R) + ("   diff" if len(R) == 2 else ""))
for k in keys:
    v = [R[n][k] for n in R]
    print(f"{k:14s}" + "".join(f"{x:10,d}" for x in v) + (f" {v[1] - v[0]:+6,d} ({(v[1] - v[0]) / v[0]:+.1%})" if len(v) == 2 else ""))
