# 28차 기준 (A)-(F)가 두 구성이 같을 때 우연히 걸릴 확률을, 확인 실행이 없을 때와 있을 때로 계산한다.
# 비율은 27차 full 출력에서 시나리오마다 낸다(모든 회차, 확인 실행 r11-r20 포함). 출처는 "full A"와 "full A+B 합침" 두 가지다.
# (A)-(D)는 이항분포로 정확히 계산하고, (E)와 (F)는 시나리오마다 출력 단위 복원 추출(seed 0, 20,000회)로 계산한다.
# 저장소 루트에서 python3 -I evals/results/it28-prompt/falsefail.py로 실행한다. 파일을 쓰지 않는다.
import collections as C, glob, json, math, random, re, sys

sys.path.insert(0, "evals")
import score as SC  # noqa: E402

R = "evals/results"
SRC = {"27차 full A": ("full-A",), "27차 full A+B": ("full-A", "full-B")}
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])
RX = re.compile(r"운영팀(은|이|에서는|에서).*권장(합니다|한다)")  # (A) 권장 주체 변경, 문장 단위
HEDGE = re.compile(r"것 같|(으)?로 보(입니다|인다|이며|이고|여|임)|듯(합니다|하다|하며|하고|싶|해)|추정(합니다|한다|됩니다|된다|되며|되고|됨|하며|하고)"
                   r"|것으로 판단|가능성이 (있|높|크|존재)|아마|짐작")

def sents(text):  # 27차 analyze.py와 같은 문장 나누기(score.py score()와 같음)
    text = SC.INLINE.sub("CODE", SC.FENCE.sub(SC.strip_code, text)); out = []
    for line in text.splitlines():
        if SC.HEADER.match(line) or SC.HR.match(line) or SC.TABLE.match(line) or not line.strip():
            continue
        out += SC.sentences(SC.QUOTE.sub("", SC.LIST.sub("", line)))
    return out

V = {}
for f in glob.glob(f"{R}/it27-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]

txt = lambda f: open(f, encoding="utf-8").read()
def judged(f):
    v = V[f]
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

def files(src, sid):
    return sorted(f for c in SRC[src] for f in glob.glob(f"{R}/it27-r*/*/{c}/{sid}.md"))

def binom(n, p):
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]

def conv(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out

def diff_pmf(parts_a, parts_b, sign):  # parts: [(n, p)]. sign*(X_B - X_A)의 분포. sign +1은 B가 많으면 나쁜 지표다.
    xa, xb = [1.0], [1.0]
    for n, p in parts_a: xa = conv(xa, binom(n, p))
    for n, p in parts_b: xb = conv(xb, binom(n, p))
    d = C.Counter()
    for i, x in enumerate(xa):
        for j, y in enumerate(xb):
            d[sign * (j - i)] += x * y
    return d

def fail_probs(parts_a, parts_b, sign, lim):  # 본 실행에서 걸릴 확률, 확인 실행(같은 횟수, 합친 수, 한계 두 배)까지 걸릴 확률
    D = diff_pmf(parts_a, parts_b, sign)
    tail = lambda t: sum(p for d, p in D.items() if d > t)
    return tail(lim), sum(p * tail(2 * lim - d) for d, p in D.items() if d > lim)

S11_19 = [f"S{i}" for i in range(11, 20)]
NEW = ["S1", "S2", "S3", "S4", "S10", "S11", "S12", "S13", "S15", "S16", "S17", "S18", "S19"]  # S5 S6 S7 S9 S14 S8 제외
ALL = ["S5", "S6", "S7"] + [f"S{i}" for i in range(1, 20) if i not in (5, 6, 7, 8)]
N = lambda s: 40 if s in ("S5", "S6", "S7") else 12  # 28차 구성당 출력 수
# 이항 기준: (이름, 시나리오, 방향, 한계, 출력 -> 참)
CRIT = [("(A) S5 권장 주체 변경", ["S5"], +1, 4, lambda f: any(RX.search(s) for s in sents(txt(f)))),
        ("(B) S5-S7 판정 통과", ["S5", "S6", "S7"], -1, 12, judged),
        ("(C) S7 글자 기준 탈락", ["S7"], +1, 6, lambda f: drop(txt(f))),
        ("(D) S11-S19 판정 통과 합", S11_19, -1, 7, judged)]
# 개수 기준: (이름, 시나리오, 한계, 출력 -> 문장 수). 방향은 모두 +1이다.
COUNT = [("(E) 25어절을 넘는 문장", ALL, 5, lambda f: sum(len(s.split()) > 25 for s in sents(txt(f)))),
         ("(F) 새 글의 헤지 2개 이상 문장", NEW, 3, lambda f: sum(len(HEDGE.findall(s)) >= 2 for s in sents(txt(f))))]

def boot(pool, sids, lim, n_iter=20000):
    rng = random.Random(0)
    draw = lambda: sum(rng.choice(pool[s]) for s in sids for _ in range(N(s)))
    main = conf = 0
    for _ in range(n_iter):
        a, b = draw(), draw()
        if b - a > lim:
            main += 1
            conf += (b + draw()) - (a + draw()) > 2 * lim
    return main / n_iter, conf / n_iter

if __name__ == "__main__":
    t = diff_pmf([(6, 0.7)], [(6, 0.7)], -1)
    assert abs(sum(t.values()) - 1) < 1e-12 and all(abs(t[d] - t[-d]) < 1e-12 for d in t)
    assert fail_probs([(5, 1.0)], [(5, 1.0)], -1, 0) == (0, 0)
    for src in SRC:
        print(f"== {src}: 비율과 우연히 걸릴 확률 (본 실행 / 확인 실행 뒤)")
        none = [1.0, 1.0]
        for name, sids, sign, lim, fn in CRIT:
            rs = {s: (sum(bool(fn(f)) for f in files(src, s)), len(files(src, s))) for s in sids}
            pp = [(N(s), rs[s][0] / rs[s][1]) for s in sids]
            p1, p2 = fail_probs(pp, pp, sign, lim)
            none = [none[0] * (1 - p1), none[1] * (1 - p2)]
            print(f"{name}: {' '.join(f'{s} {k}/{n}' for s, (k, n) in rs.items())} -> {p1:.1%} / {p2:.1%}")
        for name, sids, lim, fn in COUNT:
            pool = {s: [fn(f) for f in files(src, s)] for s in sids}
            p1, p2 = boot(pool, sids, lim)
            none = [none[0] * (1 - p1), none[1] * (1 - p2)]
            print(f"{name}: 출력 {sum(map(len, pool.values()))}개, 문장 합 {sum(map(sum, pool.values()))}, "
                  f"0이 아닌 시나리오 {{{', '.join(f'{s}: {sum(v)}' for s, v in pool.items() if sum(v))}}} -> {p1:.1%} / {p2:.1%}")
        print(f"전체(기준이 독립이라고 둠): {1 - none[0]:.1%} / {1 - none[1]:.1%}")
    print("== (A)를 같은 비율 p로 둘 때 (본 실행 / 확인 실행 뒤)")
    for p in (0.025, 0.05, 0.10, 0.125):
        p1, p2 = fail_probs([(40, p)], [(40, p)], +1, 4)
        print(f"p={p}: {p1:.1%} / {p2:.1%}")
    print("== 실제로 나빠진 경우를 잡을 확률: (A) 권장 주체 변경률 5% -> 25% (40회)")
    p1, p2 = fail_probs([(40, 0.05)], [(40, 0.25)], +1, 4)
    print(f"본 실행 {p1:.1%} / 확인 실행 뒤 {p2:.1%}")
