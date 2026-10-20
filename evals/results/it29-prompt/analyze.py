# 29차 판정 기준 (P), (a)-(f), 따로 보고하는 지표, 묶음 2(S23)와 묶음 3(S21, S22)의 수를 계산한다.
# 저장소 루트에서 python3 -I evals/results/it29-prompt/analyze.py로 실행한다. 파일을 쓰지 않는다.
# 확인 실행의 출력(r21-r40, r4-r6)이 있으면 걸린 칸의 "합친 수" 판정도 함께 낸다. 정의는 NOTES 29차 절의 "워커가 실행 전에 정한 세부"와 같다.
import collections as C, glob, json, math, re, subprocess, sys

sys.path.insert(0, "evals")
sys.path.insert(0, "evals/results/it29-prompt")
import score as SC  # noqa: E402
from falsefail import fisher_less, holm2, s9_pass  # noqa: E402

R = "evals/results"
CS, CONDS = ("A", "C1", "C2"), ("full", "agent+short")
T20, T40, R3, R6, R10 = range(1, 21), range(1, 41), range(1, 4), range(1, 7), range(1, 11)

def first(text, anchor):  # (원문을 줄인 문장이 있는 첫 줄, 설명 줄을 건너뛰었는가)
    L = [l for l in text.strip().split("\n") if l.strip()] or [""]
    for l in L:
        if anchor in l: return l, l is not L[0]
    return L[0], False
drop7 = lambda t: not re.search(r"백업(이|에)? ?실패", first(t, "배포")[0])
drop20 = lambda t: not re.search(r"정산(이|에)? ?실패", first(t, "내보내")[0])
COPY = re.compile(r"이미지 빌드|중복이 아니|조건절")
BAN = re.compile(r"테넌트|클라이언트|릴리스|정산 잡")
GLOSS = re.compile(r"용어집|glossary")
TODAY = re.compile(r"오늘(이|은|이자|은 )?\s*\(?(10/20|10월 20일)|(10/20|10월 20일)\)?(이|은)? 오늘|오늘 날짜|이미 지(났|난|나)")  # 27-28차 S12 날짜 문장
RECO = re.compile(r"(operations team|운영팀)[^.]*(recommends|recommending|giving the recommendation|advis|the one who recommend|recommender|권장합니다)"
                  r"|(recommends|recommending|giving the recommendation|advis|recommender)[^.]*(operations team|운영팀)", re.I)  # 28차와 같다

def s5_kind(issue):  # 28차 analyze.py와 같다. 첫 이유로 정한다.
    if RECO.search(issue): return "권장 주체"
    if "이에 따라" in issue or "따라서" in issue: return "이에 따라"
    if "관련하여" in issue: return "관련하여"
    return "기타"

assert drop7("백업 완료를 확인하고, 실패하면 중단합니다.") and not drop7("백업이 실패하면 중단합니다.\n") and not drop7("백업에 실패하면")
assert not drop7("원문이 이미 짧습니다.\n\n배포 전 백업이 실패하면 배포를 멈춰야 합니다.") and first("설명\n\n배포 x", "배포") == ("배포 x", True)
assert drop20("주문 데이터를 내보내기 전에 정산이 모두 끝났는지 점검하고, 실패하면 내보내기를 멈춰야 합니다.")
assert not drop20("내보내기 전에 정산 완료를 점검하고, 정산이 실패하면 멈춰야 합니다.") and not drop20("내보내기 전 정산 실패 시 멈춤")
assert BAN.search("정산 잡이 돈다") and not BAN.search("정산 배치와 고객사")

V = {}
for f in glob.glob(f"{R}/it29-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]
TR = {}  # 출력 파일 -> (스킬 실행, 읽은 파일). 같은 시나리오의 줄이 둘이면(다시 생성) 마지막 줄을 쓴다.
for f in glob.glob(f"{R}/it29-r*/*/*/trace.txt"):
    for l in open(f, encoding="utf-8"):
        sid, sk, rd = l.rstrip("\n").split("\t")[:3]
        TR[f.rsplit("/", 1)[0] + f"/{sid}.md"] = ("k-ste" in sk, rd)

def files(cd, v, sids, runs, m="*"):
    return [f for r in runs for s in sids for f in sorted(glob.glob(f"{R}/it29-r{r}/{m}/{cd}-{v}/{s}.md"))]
def judged(f):
    v = V[f]
    assert "error" not in v, f
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))
txt = lambda f: open(f, encoding="utf-8").read()
ok9_14 = lambda f: s9_pass(txt(f)) if f.endswith("/S9.md") else judged(f)
cnt = lambda F, fn: sum(bool(fn(f)) for f in F)
short = lambda f: f.replace(f"{R}/", "")

# (칸, 이름, 조건, 시나리오, 지표, 본 실행 회차, 합친 회차, 한계, 방향). 방향 +1은 후보가 많으면 나쁘고, -1은 적으면 나쁘다.
S11_19 = [f"S{i}" for i in range(11, 20)]
CRIT = [("a", "agent+short S7 탈락", "agent+short", ["S7"], lambda f: drop7(txt(f)), T20, T40, 6, +1)]
CRIT += [(f"b {cd}", f"{cd} S5-S7 판정 통과", cd, ["S5", "S6", "S7"], judged, T20, T40, 12, -1) for cd in CONDS]
CRIT += [(f"c {cd}", f"{cd} S20 탈락", cd, ["S20"], lambda f: drop20(txt(f)), T20, T40, 6, +1) for cd in CONDS]
CRIT += [("d", "full S11-S19 판정 통과 합", "full", S11_19, judged, R3, R6, 5, -1),
         ("e", "full 첫 문장 결론 S1 S2 S10", "full", ["S1", "S2", "S10"], judged, R3, R6, 3, -1)]
CRIT += [(f"f {cd}", f"{cd} S9+S14 통과 합", cd, ["S9", "S14"], ok9_14, R3, R6, 3, -1) for cd in CONDS]

def verdicts():  # 칸마다 후보마다 [본 실행 A, 후보, 결과, (합친 A, 후보, 결과)]
    out = {}
    for k, name, cd, sids, fn, r1, r2, lim, d in CRIT:
        a = cnt(files(cd, "A", sids, r1), fn); na = len(files(cd, "A", sids, r1))
        for v in ("C1", "C2"):
            c = cnt(files(cd, v, sids, r1), fn); nc = len(files(cd, v, sids, r1)); ok = (c - a) * d <= lim
            row = [f"{a}/{na}", f"{c}/{nc}", ok]
            if not ok and len(files(cd, "A", sids, r2)) > na:
                a2, c2 = cnt(files(cd, "A", sids, r2), fn), cnt(files(cd, v, sids, r2), fn)
                row += [f"{a2}/{len(files(cd, 'A', sids, r2))}", f"{c2}/{len(files(cd, v, sids, r2))}", (c2 - a2) * d <= 2 * lim]
            out[k, v] = row
    return out

def clopper(k, n, a=0.05):  # 정확 95% 신뢰구간(이분법)
    cdf = lambda p, x: sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(x + 1))
    def solve(f):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) else (lo, mid)
        return (lo + hi) / 2
    L = 0.0 if k == 0 else solve(lambda p: 1 - cdf(p, k - 1) < a / 2)
    U = 1.0 if k == n else solve(lambda p: cdf(p, k) > a / 2)
    return L, U

def fisher2(a, n1, b, n2):  # 양측 Fisher 정확 검정: 관측 표의 확률 이하인 표의 확률 합
    K, N = a + b, n1 + n2
    P = lambda x: math.comb(K, x) * math.comb(N - K, n1 - x) / math.comb(N, n1)
    p0 = P(a)
    return min(1.0, sum(P(x) for x in range(max(0, K - n2), min(K, n1) + 1) if P(x) <= p0 * (1 + 1e-9)))

assert abs(fisher2(3, 10, 3, 10) - 1) < 1e-12 and fisher2(0, 20, 10, 20) < 0.001
assert all(abs(x - y) < 1e-3 for x, y in zip(clopper(0, 20), (0.0, 0.1684))) and all(abs(x - y) < 1e-3 for x, y in zip(clopper(10, 20), (0.2720, 0.7280)))

DEF = {}
def defects(v, m):  # 28차와 같다: full r1-r3의 S1-S10 defects 합 / 3
    if (v, m) not in DEF:
        dirs = sorted(glob.glob(f"{R}/it29-r[123]/{m}/full-{v}"))
        out = subprocess.run(["python3", "evals/score.py", "-v", *dirs], capture_output=True, text=True, check=True).stdout.splitlines()
        head = [h.strip() for h in out[0].split("|")]
        DEF[v, m] = {x[1]: {h: x[i] for i, h in enumerate(head) if h} for x in ([y.strip() for y in l.split("|")] for l in out[2:]) if x[1].endswith(".md")}
    F = files("full", v, [f"S{i}" for i in range(1, 11)], R3, m)
    assert len(F) == 30, (v, m, len(F))
    return sum(int(DEF[v, m][f]["defects"]) for f in F) / 3

if __name__ == "__main__":
    print("== 출력 수와 판정 수")
    for cd in CONDS + ("base",):
        for v in CS:
            F = [f for r in T40 for f in glob.glob(f"{R}/it29-r{r}/*/{cd}-{v}/*.md")]
            if F: print(f"{cd}-{v}: 출력 {len(F)}, 판정 {sum(f in V for f in F)}, 판정 오류 {sum('error' in V.get(f, {}) for f in F)}")
    G = [f for f in glob.glob(f"{R}/it29-r*/*/G-*-A/S23.md")]
    print(f"묶음 2 출력 {len(G)}")

    print("== (P) full S7 탈락 r1-r20 (단측 Fisher, Holm 보정)")
    a = cnt(files("full", "A", ["S7"], T20), lambda f: drop7(txt(f)))
    cs = {v: cnt(files("full", v, ["S7"], T20), lambda f: drop7(txt(f))) for v in ("C1", "C2")}
    ps = {v: fisher_less(a, cs[v]) for v in cs}
    adj = dict(zip(("C1", "C2"), holm2(ps["C1"], ps["C2"])))
    P_ok = {v: adj[v] < 0.05 for v in cs}
    for v in cs:
        print(f"{v}: A {a}/40, {v} {cs[v]}/40, p {ps[v]:.4f}, Holm 보정 p {adj[v]:.4f} -> {'충족' if P_ok[v] else '불충족'}")

    print("== 회귀 기준 (A / 후보 / 결과, 확인 실행이 있으면 합친 A / 후보 / 결과)")
    VD = verdicts(); reg_ok = {"C1": True, "C2": True}
    for k, name, cd, sids, fn, r1, r2, lim, d in CRIT:
        for v in ("C1", "C2"):
            row = VD[k, v]; final = row[-1]
            reg_ok[v] &= final
            print(f"({k}) {name}, 한계 {lim}: {v} " + " / ".join(map(str, row[:2])) + (" 충족" if row[2] else " 불충족")
                  + (f" | 합친 {row[3]} / {row[4]} 한계 {2 * lim} " + ("충족" if row[5] else "불충족") if len(row) > 3 else ""))
    s7sum = {v: cnt(files("full", v, ["S7"], T20) + files("agent+short", v, ["S7"], T20), lambda f: drop7(txt(f))) for v in CS}
    cand = [v for v in ("C1", "C2") if P_ok[v] and reg_ok[v]]
    print("S7 탈락 합(full + agent+short, r1-r20):", s7sum)
    print("배포 후보:", (min(cand, key=lambda v: (s7sum[v], v)) if cand else "없음"), "| (P)와 회귀 기준을 모두 만족한 후보:", cand or "없음",
          "| 회귀 기준 최종:", reg_ok)

    print("== 묶음 1 시나리오별 (구성마다, 모든 회차)")
    for cd in CONDS:
        for v in CS:
            parts = []
            for s, fn in (("S5", judged), ("S6", judged), ("S7", judged), ("S20", judged)):
                F = files(cd, v, [s], T40); parts.append(f"{s} 판정 통과 {cnt(F, fn)}/{len(F)}")
            for s, dr in (("S7", drop7), ("S20", drop20)):
                for runs, tag in ((T20, "r1-r20"), (T40, "모든 회차")):
                    F = files(cd, v, [s], runs)
                    parts.append(f"{s} 탈락 {tag} {cnt(F, lambda f: dr(txt(f)))}/{len(F)} (haiku {cnt([f for f in F if '/haiku/' in f], lambda f: dr(txt(f)))}, "
                                 f"sonnet {cnt([f for f in F if '/sonnet/' in f], lambda f: dr(txt(f)))})")
            print(f"{cd}-{v}: " + "; ".join(parts))
    print("-- r1-r3 시나리오별 판정 통과(full)")
    for v in CS:
        print(f"full-{v}", {s: f"{cnt(files('full', v, [s], R6), ok9_14 if s in ('S9', 'S14') else judged)}/{len(files('full', v, [s], R6))}"
                            for s in ["S1", "S2", "S9", "S10", "S14"] + S11_19})
        print(f"   agent+short-{v}", {s: f"{cnt(files('agent+short', v, [s], R6), ok9_14)}/{len(files('agent+short', v, [s], R6))}" for s in ("S9", "S14")})

    print("== 설명 줄을 건너뛴 S7, S20 출력")
    for cd in CONDS:
        for v in CS:
            for s, an in (("S7", "배포"), ("S20", "내보내")):
                for f in files(cd, v, [s], T40):
                    if first(txt(f), an)[1]: print(short(f), "|", txt(f).strip().split("\n")[0][:120])

    print("== 판정기와 글자 기준이 다른 S7, S20 출력 (글자 기준 탈락인데 판정 통과 / 글자 기준 통과인데 판정 실패)")
    for cd in CONDS:
        for v in CS:
            for s, dr in (("S7", drop7), ("S20", drop20)):
                F = files(cd, v, [s], T40)
                x = [short(f) for f in F if dr(txt(f)) and judged(f)]; y = [short(f) for f in F if not dr(txt(f)) and not judged(f)]
                print(f"{cd}-{v} {s}: 탈락인데 통과 {len(x)}, 통과인데 실패 {len(y)}")
                for f in y: print("   통과인데 실패:", f, "|", " / ".join(V[f"{R}/{f}"]["issues"])[:250])
                for f in x: print("   탈락인데 통과:", f, "|", first(txt(f"{R}/{f}"), "배포" if s == "S7" else "내보내")[0][:150])

    print("== agent+short S7, S20: 스킬 실행 수와 rewrite.md를 읽은 수 (r1-r20)")
    for v in CS:
        for s in ("S7", "S20", "S5", "S6", "S9", "S14"):
            F = files("agent+short", v, [s], T20 if s not in ("S9", "S14") else R3)
            print(f"agent+short-{v} {s}: 스킬 {sum(TR[f][0] for f in F)}/{len(F)}, rewrite.md {sum('references/rewrite.md' in TR[f][1] for f in F)}/{len(F)}")

    print("== 원리 문장이나 예를 옮긴 출력 (정규식 이미지 빌드|중복이 아니|조건절, 모든 출력)")
    for cd in CONDS:
        for v in CS:
            F = [f for r in T40 for f in glob.glob(f"{R}/it29-r{r}/*/{cd}-{v}/*.md")]
            hit = [f for f in F if COPY.search(txt(f))]
            print(f"{cd}-{v}: {len(hit)}/{len(F)}")
            for f in hit:
                for l in txt(f).split("\n"):
                    if COPY.search(l): print("   ", short(f), "|", l.strip()[:200])

    print("== S5 판정기 실패 종류 (첫 이유, r1-r20)")
    for cd in CONDS:
        for v in CS:
            F = [f for f in files(cd, v, ["S5"], T20) if not judged(f)]
            print(f"{cd}-{v}: 실패 {len(F)}", dict(C.Counter(s5_kind(V[f]["issues"][0]) for f in F)))

    print("== 따로 보고: 첫 문장 결론(S1 S2 S10, r1-r3), 실행 1회당 결함(score.py, full S1-S10, r1-r3), S12 날짜 문장")
    for v in CS:
        F = files("full", v, ["S1", "S2", "S10"], R3)
        S12 = files("full", v, ["S12"], R6)
        print(f"full-{v} 첫 문장 결론 {cnt(F, judged)}/{len(F)} | 결함 haiku {defects(v, 'haiku'):.2f} sonnet {defects(v, 'sonnet'):.2f}"
              f" | S12 날짜 문장이 있는 출력 {sum(bool(TODAY.search(txt(f))) for f in S12)}/{len(S12)}")

    print("== 묶음 2: S23 (실패 = 용어집 줄을 뺀 본문에 금지어, 정확 95% 신뢰구간)")
    B = ("G-sys-base", "G-sys-full", "G-inline", "G-ptr", "G-file")
    def s23(f):
        body = [l for l in txt(f).split("\n") if not GLOSS.search(l)]
        return [l for l in body if BAN.search(l)]
    res = {}
    for b in B:
        F = sorted(glob.glob(f"{R}/it29-r*/*/{b}-A/S23.md")); k = sum(bool(s23(f)) for f in F)
        res[b] = (k, len(F)); L, U = clopper(k, len(F))
        gl = sum(any(GLOSS.search(l) for l in txt(f).split("\n")) for f in F)
        hk = sum(bool(s23(f)) for f in F if "/haiku/" in f); sk = k - hk
        line = f"{b}: 실패 {k}/{len(F)} ({L:.1%}-{U:.1%}), haiku {hk} sonnet {sk}, 용어집 줄이 있는 출력 {gl}"
        if b in ("G-inline", "G-ptr", "G-file"):
            rd = [f for f in F if "glossary.md" in TR[f][1]]
            line += (f", 읽은 회 {len(rd)}, 스킬 {sum(TR[f][0] for f in F)}, 읽은 회의 실패 {sum(bool(s23(f)) for f in rd)}/{len(rd)},"
                     f" 읽지 않은 회의 실패 {sum(bool(s23(f)) for f in F if f not in rd)}/{len(F) - len(rd)}")
        print(line)
        for f in F:
            for l in s23(f): print("   ", short(f), "|", l.strip()[:200])
            for l in txt(f).split("\n"):
                if GLOSS.search(l): print("    [용어집 줄]", short(f), "|", l.strip()[:200])
    for x, y in (("G-inline", "G-ptr"), ("G-ptr", "G-file")):
        print(f"양측 Fisher {x} 대 {y}: p = {fisher2(res[x][0], res[x][1], res[y][0], res[y][1]):.4f}")

    print("== 묶음 3: S21, S22 실패 (판정기 pass false, 정확 95% 신뢰구간)")
    for s in ("S21", "S22"):
        for cd in ("base", "full", "agent+short"):
            F = files(cd, "A", [s], R10); k = sum(not judged(f) for f in F); L, U = clopper(k, len(F))
            q = sum("확인 필요" in txt(f) for f in F)
            print(f"{s} {cd}: 실패 {k}/{len(F)} ({L:.1%}-{U:.1%}), '확인 필요'가 있는 출력 {q}"
                  + (f", 스킬 {sum(TR[f][0] for f in F)}" if cd == "agent+short" else ""))

    print("== 판정기가 실패로 본 출력 (모든 회차)")
    key = lambda x: (x.split("/")[4], x.split("/")[-1], int(x.split("/")[2].split("-r")[1]), x)
    for f in sorted(V, key=key):
        if not judged(f):
            s = f.rsplit("/", 1)[1][:-3]
            tag = {"S7": " [S7 탈락]" if drop7(txt(f)) else "", "S20": " [S20 탈락]" if drop20(txt(f)) else ""}.get(s, "")
            sk = f" [스킬 {'O' if TR[f][0] else 'X'}]" if f in TR else ""
            print(short(f) + tag + sk, "|", " / ".join(V[f].get("issues", [V[f].get("first_sentence", "")]))[:400])
