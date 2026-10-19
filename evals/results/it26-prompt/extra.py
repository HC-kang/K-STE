#!/usr/bin/env python3
"""26차 추가 확인(사전 기준에 없음). 저장소 루트에서 `python3 -I evals/results/it26-prompt/extra.py`로 실행한다.
값은 analyze.py 출력과 22차, 24차 절의 값을 옮겨 적었다."""
import collections as C
import glob
import math
import random
import re


def fisher(a, n1, b, n2):  # 양측 정확 검정, a/n1 대 b/n2
    k, n = a + b, n1 + n2
    p = lambda x: math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    return sum(p(x) for x in range(max(0, k - n2), min(k, n1) + 1) if p(x) <= p(a) * (1 + 1e-9))


def boot(a, n1, b, n2):  # 가지 안에서 출력 단위 복원 추출 10,000회, seed 0, 백분위 구간
    random.seed(0)
    xa, xb = [1] * a + [0] * (n1 - a), [1] * b + [0] * (n2 - b)
    d = sorted(sum(random.choices(xa, k=n1)) / n1 - sum(random.choices(xb, k=n2)) / n2 for _ in range(10000))
    return f"{a / n1 - b / n2:+.1%} [{d[249]:+.1%}, {d[9749]:+.1%}]"


assert round(fisher(1, 10, 9, 10), 4) == 0.0011
for name, a, n1, b, n2 in [("agent+short S7 drop", 11, 20, 5, 20), ("short S7 drop", 13, 20, 11, 20),
                           ("agent+short S7 drop, skill run only", 10, 18, 4, 19),
                           ("agent+short S7 drop, it22+it24+it26", 33, 80, 22, 80),
                           ("short S16 pass", 3, 6, 5, 6), ("agent+short S16 pass", 4, 6, 6, 6),
                           ("agent+short skill run, all scenarios", 162, 212, 175, 212)]:
    print(f"{name}: v4.1 {a}/{n1} vs v3 {b}/{n2} fisher p={fisher(a, n1, b, n2):.3f} diff {boot(a, n1, b, n2)}")

# 차수(22, 24, 26)로 층을 나눈 Cochran-Mantel-Haenszel 검정(연속성 보정). (v4.1 탈락, n, v3 탈락, n)
S = [(8, 20, 2, 20), (14, 40, 15, 40), (11, 20, 5, 20)]
num = sum(a - (a + b) * n1 / (n1 + n2) for a, n1, b, n2 in S)
var = sum((a + b) * (n1 + n2 - a - b) * n1 * n2 / ((n1 + n2) ** 2 * (n1 + n2 - 1)) for a, n1, b, n2 in S)
chi = (abs(num) - 0.5) ** 2 / var
print(f"CMH it22+it24+it26 chi2={chi:.3f} p={math.erfc(math.sqrt(chi / 2)):.3f}")

# 기준 (d)의 3회 시나리오가 우연히 걸릴 확률: 두 가지의 통과율이 같고(26차 두 가지 합) 6회씩일 때 v3 - v4.1 > 1일 확률
pb = lambda n, k, p: math.comb(n, k) * p ** k * (1 - p) ** (n - k)
pfail = lambda p: sum(pb(6, i, p) * pb(6, j, p) for i in range(7) for j in range(7) if i - j > 1)
RATES = {"short": {"S1": 12, "S2": 12, "S9": 0, "S11": 11, "S12": 8, "S14": 11, "S16": 8, "S17": 12, "S19": 12},
         "agent+short": {"S1": 12, "S2": 12, "S9": 12, "S11": 12, "S12": 11, "S14": 12, "S16": 10, "S17": 12, "S19": 12}}
for c, R in RATES.items():
    ps = {s: pfail(k / 12) for s, k in R.items()}
    print(c, {s: round(p, 3) for s, p in ps.items()}, f"P(3회 시나리오 중 하나 이상 불충족)={1 - math.prod(1 - p for p in ps.values()):.3f}")

# 날짜 표현이 있는 "확인 필요" 줄(읽어서 날짜 질문인지 가린다)과 시나리오별 스킬 미실행
DATE = re.compile(r"[0-9]+월|[0-9]+일|[0-9]+:[0-9]+|날짜|일자|기한|마감|실행일|기준일|시점|시각|언제|요일|일정|금일|오늘|내일|추후|예정")
for c in ("short", "agent+short"):
    for b in ("v3", "v4.1"):
        for f in sorted(glob.glob(f"evals/results/it26-r*/*/{c}-{b}/S*.md")):
            for l in open(f, encoding="utf-8").read().split("\n"):
                if "확인 필요" in l and DATE.search(l):
                    print(f.replace("evals/results/", ""), "|", l.strip()[:200])
t = C.Counter()
for b in ("v3", "v4.1"):
    for f in glob.glob(f"evals/results/it26-r*/*/agent+short-{b}/trace.txt"):
        for l in open(f, encoding="utf-8"):
            s, rest = l.split("\t", 1)
            t[b, s, f.split("/")[3]] += "k-ste" not in rest.split("\t")[0]
for s in [f"S{i}" for i in range(1, 20)]:
    print(s, "skill not run haiku+sonnet:", *(f"{b} {t[b, s, 'haiku']}+{t[b, s, 'sonnet']}" for b in ("v3", "v4.1")))
