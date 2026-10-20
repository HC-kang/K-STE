# 27차 기준 (a)-(h)가 두 구성의 통과율이 같을 때 우연히 걸릴 확률을, 확인 실행이 없을 때와 있을 때로 계산한다.
# 통과율은 25차(agent+short, v4와 후보를 합침)와 21차(full, agent+short)의 출력에서 시나리오마다 낸다. 모든 회차를 쓴다.
# (a)-(g)는 이항분포로 정확히 계산하고, (h)는 출력 단위 복원 추출(seed 0, 20,000회)로 계산한다.
# 저장소 루트에서 python3 -I evals/results/it27-prompt/falsefail.py로 실행한다. 파일을 쓰지 않는다.
import collections as C, glob, json, math, random, re, subprocess

R = "evals/results"
SRC = {"25차 agent+short": ("it25", ("agent+short-v4", "agent+short-cand")), "21차 full": ("it21", ("full",)),
       "21차 agent+short": ("it21", ("agent+short",))}
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])

V = {}
for f in glob.glob(f"{R}/it2[15]-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]

def judged(f):
    v = V[f]
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

def files(src, sid, m="*"):
    it, conds = SRC[src]
    return sorted(f for c in conds for f in glob.glob(f"{R}/{it}-r*/{m}/{c}/{sid}.md"))

def rate(src, sid, fn=judged):
    F = files(src, sid)
    return sum(bool(fn(f)) for f in F), len(F)

def binom(n, p):
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]

def conv(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out

def diff_pmf(parts_a, parts_b, sign):
    # parts: [(n, p)]. 반환값은 sign*(X_B - X_A)의 분포 {d: 확률}이다. sign +1은 B가 많으면 나쁜 지표다.
    xa, xb = [1.0], [1.0]
    for n, p in parts_a: xa = conv(xa, binom(n, p))
    for n, p in parts_b: xb = conv(xb, binom(n, p))
    d = C.Counter()
    for i, x in enumerate(xa):
        for j, y in enumerate(xb):
            d[sign * (j - i)] += x * y
    return d

def fail_probs(parts_a, parts_b, sign, lim):
    # 본 실행에서 걸릴 확률, 그리고 확인 실행(같은 횟수, 합친 수, 한계 두 배)까지 걸릴 확률.
    D = diff_pmf(parts_a, parts_b, sign)
    tail = lambda t: sum(p for d, p in D.items() if d > t)
    return tail(lim), sum(p * tail(2 * lim - d) for d, p in D.items() if d > lim)

# 기준: (이름, [(시나리오, 횟수)], 방향, 한계, 지표). 지표 "drop"은 S7 글자 기준 탈락이고, 나머지는 판정 통과다.
CRIT = [("(a) S7 탈락", [("S7", 20)], +1, 3, "drop"), ("(b) S5-S7 통과", [("S5", 20), ("S6", 20), ("S7", 20)], -1, 6, "judged"),
        ("(c) S12 통과", [("S12", 20)], -1, 2, "judged"), ("(c) S16 통과", [("S16", 20)], -1, 2, "judged"),
        ("(f) S11 S13-S15 S17-S19 합", [(s, 6) for s in ("S11", "S13", "S14", "S15", "S17", "S18", "S19")], -1, 3, "judged"),
        ("(g) 첫 문장 결론", [("S1", 6), ("S2", 6), ("S10", 6)], -1, 1, "judged")]

def score_rows(src, m):
    it, conds = SRC[src]
    dirs = sorted(d for c in conds for d in glob.glob(f"{R}/{it}-r*/{m}/{c}"))
    out = subprocess.run(["python3", "evals/score.py", "-v", *dirs], capture_output=True, text=True, check=True).stdout.splitlines()
    head = [h.strip() for h in out[0].split("|")]; k = head.index("defects"); pool = C.defaultdict(list)
    for l in out[2:]:
        x = [y.strip() for y in l.split("|")]
        s = re.search(r"/(S\d+)\.md$", x[1])
        if s and int(s.group(1)[1:]) <= 10: pool[s.group(1)].append(int(x[k]))
    return pool

def h_probs(src, m, N=20000):
    pool = score_rows(src, m); rng = random.Random(0)
    draw = lambda runs: sum(rng.choice(pool[s]) for s in pool for _ in range(runs))
    main = conf = 0
    for _ in range(N):
        a, b = draw(3), draw(3)
        if (b - a) / 3 > 2.0:
            main += 1
            a2, b2 = draw(3), draw(3)
            conf += (b + b2 - a - a2) / 6 > 2.0
    return main / N, conf / N, {s: len(v) for s, v in pool.items()}

if __name__ == "__main__":
    total = {}
    for src in SRC:
        print(f"== {src}: 통과율과 우연히 걸릴 확률 (본 실행 / 확인 실행 뒤)")
        none = [1.0, 1.0]
        for name, parts, sign, lim, kind in CRIT:
            rs = {s: rate(src, s, (lambda f: drop(open(f, encoding="utf-8").read())) if kind == "drop" else judged) for s, _ in parts}
            pp = [(n, rs[s][0] / rs[s][1]) for s, n in parts]
            p1, p2 = fail_probs(pp, pp, sign, lim)
            none = [none[0] * (1 - p1), none[1] * (1 - p2)]
            print(f"{name}: 비율 {' '.join(f'{s} {k}/{n}' for s, (k, n) in rs.items())} -> {p1:.1%} / {p2:.1%}")
        for m in ("haiku", "sonnet"):
            p1, p2, sizes = h_probs(src, m)
            none = [none[0] * (1 - p1), none[1] * (1 - p2)]
            print(f"(h) 결함 {m}: 출력 {sum(sizes.values())}개 -> {p1:.1%} / {p2:.1%}")
        total[src] = (1 - none[0], 1 - none[1])
        print(f"조건 전체(기준이 독립이라고 둠): {total[src][0]:.1%} / {total[src][1]:.1%}")
    print("== 두 조건 전체 (full은 21차 full, agent+short는 25차 또는 21차)")
    for a in ("25차 agent+short", "21차 agent+short"):
        f, s = total["21차 full"], total[a]
        print(f"full 21차 + {a}: {1 - (1 - f[0]) * (1 - s[0]):.1%} / {1 - (1 - f[1]) * (1 - s[1]):.1%}")
    print("== 실제로 나빠진 경우를 잡을 확률 (코디네이터 예: S16 실패율 20%에서 45%, 20회)")
    p1, p2 = fail_probs([(20, 0.80)], [(20, 0.55)], -1, 2)
    print(f"(c) S16: 본 실행 {p1:.1%} / 확인 실행 뒤 {p2:.1%}")
    # 자체 시험: 같은 분포의 차이는 0을 중심으로 대칭이고, 확률의 합은 1이다.
    t = diff_pmf([(6, 0.7)], [(6, 0.7)], -1)
    assert abs(sum(t.values()) - 1) < 1e-12 and all(abs(t[d] - t[-d]) < 1e-12 for d in t)
    assert fail_probs([(5, 1.0)], [(5, 1.0)], -1, 0) == (0, 0)
