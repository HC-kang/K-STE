#!/usr/bin/env python3
"""24차 지표. 저장소 루트에서 `python3 -I evals/results/it24-prompt/analyze.py`로 실행한다."""
import collections as C
import glob
import json
import math
import random
import re

B = ["v3", "v4.1", "G1", "G2", "G3", "G4"]
drop = lambda f: not re.search(r"백업(이|에)? ?실패", open(f).read().strip().split("\n")[0])


def fisher(a, n1, b, n2):  # 양측 정확 검정, a/n1 대 b/n2
    k, n = a + b, n1 + n2
    p = lambda x: math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    return sum(p(x) for x in range(max(0, k - n2), min(k, n1) + 1) if p(x) <= p(a) * (1 + 1e-9))


def holm(ps):  # 원래 순서로 보정 p를 돌려준다
    order, adj, run = sorted(range(len(ps)), key=lambda i: ps[i]), [0.0] * len(ps), 0.0
    for j, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - j) * ps[i]))
        adj[i] = run
    return adj


assert round(fisher(1, 10, 9, 10), 4) == 0.0011 and round(fisher(3, 6, 0, 6), 4) == 0.1818
assert [round(x, 3) for x in holm([0.01, 0.04, 0.03, 0.005])] == [0.03, 0.06, 0.06, 0.02]

v = {}
for f in glob.glob("evals/results/it24-r*/judge.jsonl"):
    for l in open(f):
        r = json.loads(l)
        v[r["file"]] = r["verdict"]
skill = {}
for f in glob.glob("evals/results/it24-r*/*/agent+short-*/trace.txt"):
    for l in open(f):
        skill[f.rsplit("/", 1)[0] + "/" + l.split("\t")[0] + ".md"] = "k-ste" in l.split("\t")[1]

files = {b: sorted(glob.glob(f"evals/results/it24-r*/*/agent+short-{b}/S7.md")) for b in B}
X = {b: [drop(f) for f in files[b]] for b in B}
t = C.Counter()
for b in B:
    for f in files[b]:
        m, d, ok, sk = f.split("/")[-3], drop(f), v[f].get("meaning_changed") is False, skill[f]
        t[b, "n"] += 1; t[b, "drop"] += d; t[b, "drop", m] += d; t[b, "judge pass"] += ok
        t[b, "judge error"] += "error" in v[f]; t[b, "skill"] += sk; t[b, "skill", m] += sk
        t[b, "drop & judge fail"] += d and not ok; t[b, "no drop & judge fail"] += (not d) and not ok
        t[b, "no skill & drop"] += (not sk) and d
for k in sorted(t):
    print(*k, t[k])

print("\nbranch drop/n diff boot95 fisher_p holm_p")
p = {b: fisher(sum(X[b]), len(X[b]), sum(X["v3"]), len(X["v3"])) for b in B[1:]}
adj = dict(zip(B[2:], holm([p[b] for b in B[2:]])))
for b in B[1:]:
    random.seed(0)
    xa, xb = X[b], X["v3"]
    d = sorted(sum(random.choices(xa, k=len(xa))) / len(xa) - sum(random.choices(xb, k=len(xb))) / len(xb) for _ in range(10000))
    print(f"{b} {sum(xa)}/{len(xa)} vs v3 {sum(xb)}/{len(xb)} diff {sum(xa)/len(xa)-sum(xb)/len(xb):+.1%}"
          f" boot95 [{d[249]:+.1%}, {d[9749]:+.1%}] p={p[b]:.4f}" + (f" holm={adj[b]:.4f}" if b in adj else ""))

print("\n추가 확인(사전 기준에 없음)")
A = [(f, drop(f)) for b in B for f in files[b]]
half = lambda f: int(f.split("/")[2][6:]) <= 10
for name, key in (("r1-10 vs r11-20", half), ("haiku vs sonnet", lambda f: "/haiku/" in f)):
    a = [d for f, d in A if key(f)]; b = [d for f, d in A if not key(f)]
    print(f"{name}: {sum(a)}/{len(a)} vs {sum(b)}/{len(b)} p={fisher(sum(a), len(a), sum(b), len(b)):.4f}")
old = lambda it, c: [drop(f) for f in sorted(glob.glob(f"evals/results/{it}-r*/*/{c}/S7.md"))]
for name, xa, xb in (("it24 v3 vs it23 cand", X["v3"], old("it23", "agent+short-cand")),
                     ("it24 v3 vs it23 v3", X["v3"], old("it23", "agent+short-v3")),
                     ("it24 v3 vs it22 v3", X["v3"], old("it22", "agent+short-v3")),
                     ("it24 v4.1 vs it22 v4.1", X["v4.1"], old("it22", "agent+short-v4.1"))):
    print(f"{name}: {sum(xa)}/{len(xa)} vs {sum(xb)}/{len(xb)} p={fisher(sum(xa), len(xa), sum(xb), len(xb)):.4f}")
n3 = sum(X["v3"])
print("Holm 1순위(p<0.0125)를 넘는 최소 탈락 수:", min(a for a in range(n3, 41) if fisher(a, 40, n3, 40) < 0.0125))
