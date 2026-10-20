# 29차 회귀 기준 (a)-(f)가 세 구성이 같을 때 우연히 걸릴 확률과 (P)의 검정력을 계산한다.
# 비율은 27-28차 출력에서 시나리오마다 낸다. 출처는 "A만"(27차 full A, 28차 full A, 27차 agent+short A)과 "모두"(같은 차수의 A와 B를 합침) 두 가지다.
# 모든 확률은 이항분포와 초기하분포로 정확히 계산한다. 두 후보는 같은 A와 비교하므로 "두 후보 중 하나라도"는 A의 수를 조건으로 계산한다.
# 저장소 루트에서 python3 -I evals/results/it29-prompt/falsefail.py로 실행한다. 파일을 쓰지 않는다.
import glob, json, math, re

R = "evals/results"
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])  # S7 글자 기준 탈락(21-28차와 같음)
ID = re.compile(r"(?<![A-Za-z0-9])K(\d+)(?![0-9])")
cells = lambda l: [c.strip().replace("**", "").strip() for c in l.strip().strip("|").split("|")]

def s9_pass(text):  # 25차 analyze.py와 같다: 머리 행 앞 세 칸이 규칙/원문/고친 글인 표가 있고, 그 표들의 첫 칸 ID가 모두 K0-K15
    L, ok, i = text.split("\n"), False, 0
    while i < len(L) - 1:
        if L[i].lstrip().startswith("|") and cells(L[i])[:3] == ["규칙", "원문", "고친 글"] and re.match(r"^\s*\|[\s:|-]+\|?\s*$", L[i + 1]) and "-" in L[i + 1]:
            ok, i = True, i + 2
            while i < len(L) and L[i].lstrip().startswith("|"):
                if any(int(n) > 15 for n in ID.findall(cells(L[i])[0])): return False
                i += 1
        else:
            i += 1
    return ok

V = {}
for f in glob.glob(f"{R}/it2[78]-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]
txt = lambda f: open(f, encoding="utf-8").read()
def judged(f):
    v = V[f]
    assert "error" not in v, f
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

SRC = {("full", "A만"): ["it27-r*/*/full-A", "it28-r*/*/full-A"], ("full", "모두"): ["it27-r*/*/full-[AB]", "it28-r*/*/full-[AB]"],
       ("agent+short", "A만"): ["it27-r*/*/agent+short-A"], ("agent+short", "모두"): ["it27-r*/*/agent+short-[AB]"]}
def rate(cd, src, sid, fn):
    F = sorted(f for g in SRC[cd, src] for f in glob.glob(f"{R}/{g}/{sid}.md"))
    return sum(bool(fn(f)) for f in F), len(F)

def binom(n, p):
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
def conv(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out
def pmf(parts):  # parts: [(n, p)] -> 합의 분포
    x = [1.0]
    for n, p in parts: x = conv(x, binom(n, p))
    return x

def crit_probs(parts, sign, lim):
    """한 기준에서 (한 후보가 본 실행에서 걸릴 확률, 한 후보가 확인 실행 뒤에도 걸릴 확률, 두 후보 중 하나라도 확인 실행 뒤에 걸릴 확률).
    sign +1은 후보가 많으면 나쁘고, -1은 적으면 나쁘다. 세 구성의 비율은 같다. 확인 실행은 같은 횟수를 더 재고 한계를 두 배로 한다."""
    X = pmf(parts); K = range(len(X))
    bad = lambda c, a, l: sign * (c - a) > l
    main1 = sum(X[a] * X[c] for a in K for c in K if bad(c, a, lim))
    # 확인 실행: A의 본 실행 a1, 확인 실행 a2가 정해지면 두 후보는 독립이다.
    tail2 = {}  # (c1 - a1 - a2) -> 확인 실행 c2를 더한 합이 한계 2배를 넘을 확률
    def f(a1, a2):  # 한 후보가 본 실행에서 걸리고 합친 수에서도 걸릴 확률
        s = 0.0
        for c1 in K:
            if not bad(c1, a1, lim): continue
            key = c1 - a1 - a2
            if key not in tail2: tail2[key] = sum(X[c2] for c2 in K if sign * (key + c2) > 2 * lim)
            s += X[c1] * tail2[key]
        return s
    one = both_ok = 0.0
    for a1 in K:
        for a2 in K:
            q = f(a1, a2); w = X[a1] * X[a2]
            one += w * q; both_ok += w * (1 - q) ** 2
    return main1, one, 1 - both_ok

def fisher_less(xa, xc, n=40):  # 단측 Fisher 정확 검정: 후보의 탈락이 A보다 적다는 대립가설의 p
    K, N = xa + xc, 2 * n
    return sum(math.comb(K, k) * math.comb(N - K, n - k) for k in range(max(0, K - n), xc + 1)) / math.comb(N, n)

def holm2(p1, p2):  # 두 후보의 Holm 보정 p
    if p1 <= p2: a1 = min(1, 2 * p1); return a1, max(a1, p2)
    a2 = min(1, 2 * p2); return max(a2, p1), a2

def power(pa, p1, p2, n=40):  # (C1 개선 판정 확률, C2 개선 판정 확률, 하나라도, 둘 다)
    FP = [[fisher_less(a, c, n) for c in range(n + 1)] for a in range(n + 1)]
    A, B1, B2 = binom(n, pa), binom(n, p1), binom(n, p2)
    r = [0.0] * 4
    for a in range(n + 1):
        for x1 in range(n + 1):
            for x2 in range(n + 1):
                w = A[a] * B1[x1] * B2[x2]
                h1, h2 = holm2(FP[a][x1], FP[a][x2])
                d1, d2 = h1 < 0.05, h2 < 0.05
                r[0] += w * d1; r[1] += w * d2; r[2] += w * (d1 or d2); r[3] += w * (d1 and d2)
    return r

S11_19 = [f"S{i}" for i in range(11, 20)]
if __name__ == "__main__":
    assert abs(sum(pmf([(6, 0.3), (6, 0.8)])) - 1) < 1e-12
    assert crit_probs([(5, 1.0)], -1, 0) == (0, 0, 0)
    assert abs(fisher_less(20, 20) - 0.5880) < 1e-3 and fisher_less(30, 10) < 1e-4  # 20/40 대 20/40, 30/40 대 10/40
    assert holm2(0.01, 0.03) == (0.02, 0.03) and holm2(0.04, 0.01) == (0.04, 0.02)
    dr = lambda f: drop(txt(f))
    for src in ("A만", "모두"):
        print(f"== 출처 {src}: 비율, 우연히 걸릴 확률 (한 후보 본 실행 / 한 후보 확인 실행 뒤 / 두 후보 중 하나라도 확인 실행 뒤)")
        none1 = none2 = none_any = 1.0
        rows = []
        r7 = {cd: rate(cd, src, "S7", dr) for cd in ("full", "agent+short")}
        rows.append(("(a) agent+short S7 탈락(40회, 한계 6)", [("S7", r7["agent+short"], 40)], +1, 6))
        for cd in ("full", "agent+short"):
            rows.append((f"(b) {cd} S5-S7 판정 통과(120회, 한계 12)", [(s, rate(cd, src, s, judged), 40) for s in ("S5", "S6", "S7")], -1, 12))
        for cd in ("full", "agent+short"):
            rows.append((f"(c) {cd} S20 탈락(40회, 한계 6), S7 탈락 비율을 씀", [("S7", r7[cd], 40)], +1, 6))
        rows.append(("(d) full S11-S19 판정 통과 합(54회, 한계 5)", [(s, rate("full", src, s, judged), 6) for s in S11_19], -1, 5))
        rows.append(("(e) full 첫 문장 결론 S1 S2 S10(18회, 한계 3)", [(s, rate("full", src, s, judged), 6) for s in ("S1", "S2", "S10")], -1, 3))
        for cd in ("full", "agent+short"):
            rows.append((f"(f) {cd} S9+S14 통과 합(12회, 한계 3)",
                         [("S9", rate(cd, src, "S9", lambda f: s9_pass(txt(f))), 6), ("S14", rate(cd, src, "S14", judged), 6)], -1, 3))
        for name, sc, sign, lim in rows:
            p1, p2, p3 = crit_probs([(n, k / m) for _, (k, m), n in sc], sign, lim)
            none1 *= 1 - p1; none2 *= 1 - p2; none_any *= 1 - p3
            print(f"{name}: {' '.join(f'{s} {k}/{m}' for s, (k, m), _ in sc)} -> {p1:.1%} / {p2:.1%} / {p3:.1%}")
        print(f"전체(기준이 독립이라고 둠): 한 후보 본 실행 {1 - none1:.1%}, 한 후보 확인 실행 뒤 {1 - none2:.1%}, 두 후보 중 하나라도 확인 실행 뒤 {1 - none_any:.1%}")
    print("== (c) S20 탈락을 같은 비율 p로 둘 때 (한 후보 본 실행 / 확인 실행 뒤 / 두 후보 중 하나라도 확인 실행 뒤)")
    for p in (0.1, 1 / 3, 0.5):
        print(f"p={p:.3f}: " + " / ".join(f"{x:.1%}" for x in crit_probs([(40, p)], +1, 6)))
    print("== (P) 단측 Fisher, 두 후보 Holm 보정, 보정 p < 0.05 (C1 개선 / C2 개선 / 하나라도 / 둘 다)")
    for pa, p1, p2, tag in ((0.56, 0.30, 0.30, "A 56%, 두 후보 30%"), (0.56, 0.30, 0.56, "A 56%, C1 30%, C2 56%(효과 없음)"),
                            (0.56, 0.56, 0.56, "세 구성 모두 56%(우연히 개선 판정)")):
        print(f"{tag}: " + " / ".join(f"{x:.1%}" for x in power(pa, p1, p2)))
    print("== 같은 결과를 내는 최소 차이: A 탈락 수마다 보정 p < 0.05가 되려면 후보 탈락이 몇 이하여야 하는가(이 후보의 p가 둘 중 작을 때, 보정 p = 2p)")
    for a in (16, 20, 22, 24, 28):
        c = max([x for x in range(41) if 2 * fisher_less(a, x) < 0.05] or [None])
        print(f"A {a}/40 -> 후보 {c}/40 이하")
