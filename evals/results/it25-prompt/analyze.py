# 25차 판정 기준 (a)-(h)와 따로 보고하는 지표를 계산한다. 저장소 루트에서 python3 -I evals/results/it25-prompt/analyze.py로 실행한다.
import collections as C, glob, json, random, re, subprocess

R = "evals/results"
CS = ("v4", "cand")
RW = ("S5", "S6", "S7", "S9", "S14")
NEW = ("S1", "S2", "S3", "S4", "S10", "S11", "S12", "S13", "S15", "S16", "S17", "S18", "S19")
ID = re.compile(r"(?<![A-Za-z0-9])K(\d+)(?![0-9])")
cells = lambda l: [c.strip().replace("**", "").strip() for c in l.strip().strip("|").split("|")]

def s9_pass(text):  # 23차와 같다: 머리 행 앞 세 칸이 규칙/원문/고친 글인 표가 있고, 그 표들의 첫 칸 ID가 모두 K0-K15
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

bad_id = lambda t: any(int(n) > 15 for n in ID.findall(t))
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])  # S7 글자 기준 탈락
fake_head = lambda t: any(re.fullmatch(r"\*\*[^*]+\*\*:?\s*", l) for l in t.split("\n"))  # 21차 grep -lE '^\*\*[^*]+\*\*:?\s*$'

T = "| 규칙 | 원문 | 고친 글 |\n|---|---|---|\n| K9 | a | b |\n| K0, K15 | c | d |\n"
assert s9_pass(T) and not s9_pass(T + "| K16 | e | f |\n") and not s9_pass("| 규칙 | 원문 | 고친 글 |\n| K3 | a | b |")
assert bad_id("K16번") and not bad_id("K-STE, K1")
assert drop("백업 완료를 확인하고, 실패하면 중단합니다.") and not drop("백업이 실패하면 중단합니다.\n") and not drop("백업에 실패하면")
assert fake_head("앞\n**현상**\n뒤") and fake_head("**원인:** ") and not fake_head("**경고:** 지우면 안 됩니다.") and not fake_head("**a** 와 **b**")

V = {}
for f in glob.glob(f"{R}/it25-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]
TR = {}
for f in glob.glob(f"{R}/it25-r*/*/agent+short-*/trace.txt"):
    for l in open(f, encoding="utf-8"):
        sid, sk, rd = l.rstrip("\n").split("\t")[:3]
        TR[f.rsplit("/", 1)[0] + f"/{sid}.md"] = ("k-ste" in sk, rd)

def files(c, sids, runs=range(1, 11), m="*"):
    return [f for r in runs for s in sids for f in sorted(glob.glob(f"{R}/it25-r{r}/{m}/agent+short-{c}/{s}.md"))]

def judged(f):
    v = V[f]
    assert "error" not in v, f
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

txt = lambda f: open(f, encoding="utf-8").read()
cnt = lambda c, sids, fn, runs=range(1, 11): sum(bool(fn(f)) for f in files(c, sids, runs))
n = lambda c, sids, runs=range(1, 11): len(files(c, sids, runs))
R3 = range(1, 4)

def defects(c, m):  # 21차와 같다: r1-r3의 S1-S10 출력의 defects 합 / 3
    out = subprocess.run(["python3", "evals/score.py", "-v", *[f"{R}/it25-r{r}/{m}/agent+short-{c}" for r in R3]],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    head = [h.strip() for h in out[0].split("|")]; k = head.index("defects"); s = 0
    for l in out[2:]:
        x = [y.strip() for y in l.split("|")]
        if re.search(r"/S([1-9]|10)\.md$", x[1]): s += int(x[k])
    return s / 3

print("== 출력 수와 판정 오류")
for c in CS:
    print(c, "출력", n(c, RW + ("S10", "S13"), range(1, 11)) + n(c, ("S1", "S2", "S3", "S4", "S8", "S11", "S12", "S15", "S16", "S17", "S18", "S19"), R3),
          "/212, 판정", sum(1 for f in V if f"agent+short-{c}/" in f), "판정 오류", sum("error" in V[f] for f in V if f"agent+short-{c}/" in f))

M = {}
for c in CS:
    M[c] = {
        "a": cnt(c, ["S7"], lambda f: drop(txt(f))),
        "b": cnt(c, ["S5", "S6", "S7"], judged),
        "c": cnt(c, ["S9"], lambda f: s9_pass(txt(f))) + cnt(c, ["S14"], judged),
        "d": cnt(c, RW, lambda f: TR[f][0]),
        "e1": cnt(c, ["S10"], lambda f: fake_head(txt(f))),
        "e2": cnt(c, ["S13"], judged),
        **{f"f {s}": cnt(c, [s], judged, R3) for s in ("S15", "S18", "S19")},
        "f S11-S15": cnt(c, ["S11", "S12", "S13", "S14", "S15"], judged, R3),
        "g": cnt(c, ["S1", "S2", "S10"], judged, R3),
        "h haiku": defects(c, "haiku"), "h sonnet": defects(c, "sonnet"),
    }
# (기준, 이름, 한계, 방향): 방향 +1은 후보가 많으면 나쁘고, -1은 적으면 나쁘다.
CRIT = [("a", "S7 글자 기준 탈락 (20회)", 3, +1), ("b", "S5-S7 판정 통과 (60회)", 6, -1), ("c", "S9 글자 기준 + S14 판정 통과 (40회)", 4, -1),
        ("d", "스킬 실행, S5 S6 S7 S9 S14 (100회)", 2, -1), ("e1", "S10 볼드 가짜 제목 (20회)", 2, +1), ("e2", "S13 판정 통과 (20회)", 2, -1),
        ("f S15", "S15 판정 통과 (r1-r3, 6회)", 1, -1), ("f S18", "S18 판정 통과 (r1-r3, 6회)", 1, -1), ("f S19", "S19 판정 통과 (r1-r3, 6회)", 1, -1),
        ("f S11-S15", "S11-S15 판정 통과 (r1-r3, 30회)", 2, -1), ("g", "첫 문장 결론 S1 S2 S10 (r1-r3, 18회)", 1, -1),
        ("h haiku", "실행 1회당 결함 haiku (r1-r3)", 2.0, +1), ("h sonnet", "실행 1회당 결함 sonnet (r1-r3)", 2.0, +1)]
print("== 판정 기준 (v4 / 후보 / 차이 / 한계 / 결과)")
allok = True
for k, name, lim, d in CRIT:
    a, b = M["v4"][k], M["cand"][k]
    ok = (b - a) * d <= lim + 1e-9
    allok &= ok
    fmt = (lambda x: f"{x:.1f}") if k.startswith("h") else (lambda x: f"{x:d}")
    print(f"({k}) {name}: {fmt(a)} / {fmt(b)} / {b - a:+.1f} / {lim} / {'충족' if ok else '불충족'}")
print("모든 기준 충족" if allok else "기준 불충족 있음")

print("== 따로 보고하는 지표")
for c in CS:
    rw = cnt(c, RW, lambda f: "references/rewrite.md" in TR[f][1])
    print(c, "재작성·검수 rewrite.md 읽음", f"{rw}/{n(c, RW)}",
          "| genres.md 읽음(모든 출력)", sum("genres" in TR[f][1] for f in TR if f"-{c}/" in f),
          "| word-swaps.md 읽음(재작성·검수)", cnt(c, RW, lambda f: "word-swaps" in TR[f][1]))
    print(c, "새 글 스킬 실행 r1-r3", f"{cnt(c, NEW, lambda f: TR[f][0], R3)}/{n(c, NEW, R3)}",
          "| 새 글 모든 회차", f"{sum(TR[f][0] for f in files(c, NEW))}/{len(files(c, NEW))}",
          "| S8", f"{cnt(c, ['S8'], lambda f: TR[f][0], R3)}/{n(c, ['S8'], R3)}",
          "| 모든 출력", f"{sum(v[0] for f, v in TR.items() if f'-{c}/' in f)}/{sum(1 for f in TR if f'-{c}/' in f)}")
    q = {s: sum(l.count("확인 필요") > 0 for f in files(c, [s]) for l in txt(f).split("\n")) for s in [f"S{i}" for i in range(1, 20)]}
    q3 = sum(l.count("확인 필요") > 0 for f in files(c, [f"S{i}" for i in range(1, 20)], R3) for l in txt(f).split("\n"))
    print(c, "확인 필요 줄 (모든 회차)", {s: v for s, v in q.items() if v}, "합", sum(q.values()), "| r1-r3 합", q3)
    print(c, "S9 없는 ID 출력", cnt(c, ["S9"], lambda f: bad_id(txt(f))), "| S9 K15 인용 출력", cnt(c, ["S9"], lambda f: "15" in ID.findall(txt(f))),
          "| S7 판정 실패 중 글자 기준 탈락", sum(drop(txt(f)) for f in files(c, ["S7"]) if not judged(f)), "/", sum(not judged(f) for f in files(c, ["S7"])))
    print(c, "모델별: S7 탈락", {m: sum(drop(txt(f)) for f in files(c, ["S7"], m=m)) for m in ("haiku", "sonnet")},
          "S5-S7 통과", {m: sum(judged(f) for f in files(c, ["S5", "S6", "S7"], m=m)) for m in ("haiku", "sonnet")})
    print(c, "시나리오별 판정 통과", {s: f"{cnt(c, [s], judged)}/{n(c, [s])}" for s in ("S1", "S2", "S5", "S6", "S7", "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19") if n(c, [s])})

random.seed(0)
for name, sids, fn in (("S7 탈락", ["S7"], lambda f: drop(txt(f))), ("S5-S7 통과", ["S5", "S6", "S7"], judged)):
    a, b = [fn(f) for f in files("cand", sids)], [fn(f) for f in files("v4", sids)]
    d = sorted(sum(random.choices(a, k=len(a))) / len(a) - sum(random.choices(b, k=len(b))) / len(b) for _ in range(10000))
    print(f"{name} 후보-v4 {sum(a)/len(a)-sum(b)/len(b):+.1%} 부트스트랩 95% [{d[249]:+.1%}, {d[9749]:+.1%}]")

print("== S7 탈락과 S5-S7 통과, rewrite.md를 읽었는지에 따라 (읽음 / 안 읽음)")
for c in CS:
    rd = lambda f: "references/rewrite.md" in TR[f][1]
    for name, sids, fn in (("S7 탈락", ["S7"], lambda f: drop(txt(f))), ("S5-S7 통과", ["S5", "S6", "S7"], judged)):
        F = files(c, sids)
        print(c, name, f"{sum(fn(f) for f in F if rd(f))}/{sum(map(rd, F))}", f"{sum(fn(f) for f in F if not rd(f))}/{sum(not rd(f) for f in F)}")
print("== S5-S7 밖의 판정 실패 (스킬 실행 여부)")
for f in sorted(V):
    if "/S5.md" not in f and "/S6.md" not in f and "/S7.md" not in f and not judged(f):
        print(f.replace(f"{R}/", ""), "skill" if TR[f][0] else "no-skill", "|", " / ".join(V[f].get("issues", [V[f].get("first_sentence", "")]))[:200])
