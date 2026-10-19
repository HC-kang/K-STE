#!/usr/bin/env python3
"""26차 지표와 기준 (a)-(h). 저장소 루트에서 `python3 -I evals/results/it26-prompt/analyze.py [-v]`로 실행한다.
-v는 기준에 걸린 출력과 "확인 필요" 줄을 함께 출력한다."""
import collections as C
import glob
import json
import math
import re
import subprocess
import sys

R = "evals/results"
CONDS, BR, MODELS = ["short", "agent+short"], ["v3", "v4.1"], ["haiku", "sonnet"]
THREE = ["S1", "S2", "S9", "S11", "S12", "S14", "S16", "S17", "S19"]
VERBOSE = "-v" in sys.argv

drop = lambda x: not re.search(r"백업(이|에)? ?실패", x.strip().split("\n")[0])
fake_head = lambda x: bool(re.search(r"^\*\*[^*]+\*\*:?\s*$", x, re.M))  # 19-21차 grep -E '^\*\*[^*]+\*\*:?\s*$'
ID = re.compile(r"(?<![A-Za-z0-9])K(\d+)(?![0-9])")
cells = lambda l: [c.strip().replace("**", "").strip() for c in l.strip().strip("|").split("|")]
DATE = re.compile(r"[0-9]+월|[0-9]+일|[0-9]+:[0-9]+|날짜|일자|기한|마감|실행일|기준일|시점|시각|언제|요일|일정|금일|오늘|내일|추후|예정")
STATED = re.compile(r"확인 필요.*10월 2[23]일")  # 19-20차 grep


def s9_pass(text):  # 23차 글자 기준
    L, ok, i = text.split("\n"), False, 0
    while i < len(L) - 1:
        if L[i].lstrip().startswith("|") and cells(L[i])[:3] == ["규칙", "원문", "고친 글"] and re.match(r"^\s*\|[\s:|-]+\|?\s*$", L[i + 1]) and "-" in L[i + 1]:
            ok, i = True, i + 2
            while i < len(L) and L[i].lstrip().startswith("|"):
                if any(int(n) > 15 for n in ID.findall(cells(L[i])[0])):
                    return False
                i += 1
        else:
            i += 1
    return ok


def fisher(a, n1, b, n2):  # 양측 정확 검정, a/n1 대 b/n2
    k, n = a + b, n1 + n2
    p = lambda x: math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    return sum(p(x) for x in range(max(0, k - n2), min(k, n1) + 1) if p(x) <= p(a) * (1 + 1e-9))


T = "| 규칙 | 원문 | 고친 글 |\n|---|---|---|\n| K9 | a | b |\n| K0, K15 | c | d |\n"
assert s9_pass(T) and not s9_pass(T + "| K16 | e | f |\n") and not s9_pass("| 문제 | 원문 | 고친 글 |\n|---|---|---|\n| K3 | a | b |")
assert drop("확인하고, 실패하면 중단해야 합니다.") and not drop("백업이 실패하면 중단합니다.\n둘째 줄") and not drop("백업 실패 시")
assert fake_head("앞\n**사실**\n뒤") and fake_head("**추론:**") and not fake_head("**경고:** 문장이 이어진다.")
assert DATE.search("확인 필요: 10월 22일") and not DATE.search("확인 필요: 어느 문서인지")
assert round(fisher(1, 10, 9, 10), 4) == 0.0011

verdict = {}
for f in glob.glob(f"{R}/it26-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        verdict[r["file"]] = r["verdict"]
skill = {}
for f in glob.glob(f"{R}/it26-r*/*/agent+short-*/trace.txt"):
    for l in open(f, encoding="utf-8"):
        sid, rest = l.split("\t", 1)
        skill[f.rsplit("/", 1)[0] + "/" + sid + ".md"] = "k-ste" in rest.split("\t")[0]


def files(c, b, sid, runs=None, model=None):
    out = []
    for f in sorted(glob.glob(f"{R}/it26-r*/*/{c}-{b}/{sid}.md")):
        r, m = int(f.split("/")[2][6:]), f.split("/")[3]
        if (runs is None or r in runs) and (model is None or m == model):
            out.append(f)
    return out


def ok(f):
    sid, v = f.split("/")[-1][:-3], verdict.get(f)
    if sid == "S9":
        return s9_pass(open(f, encoding="utf-8").read())
    if v is None or "error" in v:
        raise SystemExit(f"no verdict: {f}")
    return not v["meaning_changed"] if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))


def defects(c, b, m):
    dirs = sorted(glob.glob(f"{R}/it26-r[123]/{m}/{c}-{b}"))
    out = subprocess.run(["python3", "evals/score.py", "-v", *dirs], capture_output=True, text=True, check=True).stdout
    head = [h.strip() for h in out.split("\n")[0].strip("|").split("|")]
    s = 0
    for l in out.split("\n")[2:]:
        row = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(row) == len(head) and re.search(r"/S([1-9]|10)\.md$", row[0]):
            s += int(row[head.index("defects")])
    return s / len(dirs), len(dirs)


def flag_lines(fs):
    return [(f, l.strip()) for f in fs for l in open(f, encoding="utf-8").read().split("\n") if "확인 필요" in l]


ALL = [f"S{i}" for i in range(1, 20)]
V, N = C.defaultdict(dict), C.Counter()
for c in CONDS:
    for b in BR:
        x = V[c, b]
        s7 = files(c, b, "S7")
        x["a S7 drop"] = (sum(drop(open(f, encoding="utf-8").read()) for f in s7), len(s7))
        for m in MODELS:
            fm = files(c, b, "S7", model=m)
            x[f"  S7 drop {m}"] = (sum(drop(open(f, encoding="utf-8").read()) for f in fm), len(fm))
        x["  S7 drop & judge fail"] = (sum(drop(open(f, encoding="utf-8").read()) and not ok(f) for f in s7), len(s7))
        s57 = [f for s in ("S5", "S6", "S7") for f in files(c, b, s)]
        x["b S5-S7 pass"] = (sum(map(ok, s57)), len(s57))
        for s in ("S5", "S6", "S7"):
            x[f"  {s} pass"] = (sum(map(ok, files(c, b, s))), len(files(c, b, s)))
        s10 = files(c, b, "S10")
        x["c S10 bold fake heading"] = (sum(fake_head(open(f, encoding="utf-8").read()) for f in s10), len(s10))
        x["c S13 pass"] = (sum(map(ok, files(c, b, "S13"))), len(files(c, b, "S13")))
        for s in ["S15", "S18"] + THREE:
            x[f"d {s} pass"] = (sum(map(ok, files(c, b, s))), len(files(c, b, s)))
        cf = [f for s in ("S1", "S2", "S10") for f in files(c, b, s)]
        x["e conclusion S1+S2+S10"] = (sum(map(ok, cf)), len(cf))
        for m in MODELS:
            x[f"f defects/run {m}"] = defects(c, b, m)
        g = [f for s in ("S13", "S15") for f in files(c, b, s)]
        x["g grep stated-date question (S13,S15)"] = (len({f for f, l in flag_lines(g) if STATED.search(l)}), len(g))
        x["  S13,S15 outputs with 확인 필요"] = (len({f for f, _ in flag_lines(g)}), len(g))
        if c == "agent+short":
            sk = [f for s in ("S5", "S6", "S7", "S9", "S14") for f in files(c, b, s)]
            x["h skill run (S5,S6,S7,S9,S14)"] = (sum(skill.get(f, False) for f in sk), len(sk))
            sa = [f for s in ALL for f in files(c, b, s)]
            x["  skill run, all scenarios"] = (sum(skill.get(f, False) for f in sa), len(sa))
        allf = [f for s in ALL for f in files(c, b, s)]
        fl = flag_lines(allf)
        x["  확인 필요 lines"] = (len(fl), len(allf))
        x["  확인 필요 lines without date words"] = (sum(not DATE.search(l) for _, l in fl), len(fl))
        x["  outputs"] = (len(allf), 212)

keys = list(V["short", "v3"].keys()) + [k for k in V["agent+short", "v3"] if k not in V["short", "v3"]]
fmt = lambda t: f"{t[0]:.1f} ({t[1]} runs)" if isinstance(t[0], float) else f"{t[0]}/{t[1]}"
print(f"{'metric':42s}" + "".join(f"{c + ' ' + b:>22s}" for c in CONDS for b in BR))
for k in keys:
    print(f"{k:42s}" + "".join(f"{fmt(V[c, b][k]) if k in V[c, b] else '':>22s}" for c in CONDS for b in BR))

# 기준 판정. more=True는 v4.1이 v3보다 많으면 나쁜 지표다.
RULES = [("a", "a S7 drop", 3, True), ("b", "b S5-S7 pass", 6, False), ("c", "c S10 bold fake heading", 2, True),
         ("c", "c S13 pass", 2, False), ("d", "d S15 pass", 3, False), ("d", "d S18 pass", 3, False)] + \
        [("d", f"d {s} pass", 1, False) for s in THREE] + \
        [("e", "e conclusion S1+S2+S10", 2, False)] + [("f", f"f defects/run {m}", 2.0, True) for m in MODELS] + \
        [("g", "g stated-date question (manual)", 2, True), ("h", "h skill run (S5,S6,S7,S9,S14)", 2, False)]
# (g)는 줄을 읽어서 센다. 손으로 센 값은 manual_g.json({"short v3": n, ...})에 둔다.
try:
    MG = json.load(open(f"{R}/it26-prompt/manual_g.json"))
except FileNotFoundError:
    MG = None
print()
for c in CONDS:
    goods = []
    for crit, k, lim, more in RULES:
        if k.startswith("h") and c == "short":
            continue
        if k.startswith("g") and MG is None:
            print(f"{c:12s} ({crit}) {k}: manual_g.json 없음")
            goods.append(None)
            continue
        a, b = ((MG[f"{c} v3"], MG[f"{c} v4.1"]) if k.startswith("g") else (V[c, "v3"][k][0], V[c, "v4.1"][k][0]))
        d = b - a if more else a - b
        goods.append(d <= lim + 1e-9)
        print(f"{c:12s} ({crit}) {k}: v3 {a:g} v4.1 {b:g} -> {'more' if more else 'fewer'} by {d:+g} (limit {lim:g}) {'OK' if goods[-1] else 'FAIL'}")
    print(f"{c:12s} ALL: {'undecided (g)' if None in goods and all(g is not False for g in goods) else all(goods)}")
    a, b = V[c, "v3"]["a S7 drop"], V[c, "v4.1"]["a S7 drop"]
    print(f"{c:12s} S7 drop fisher p={fisher(b[0], b[1], a[0], a[1]):.3f}")

errs = [f for f, v in verdict.items() if "error" in v]
print(f"\njudge rows {len(verdict)}, errors {len(errs)}", *errs, sep="\n  ")

if VERBOSE:
    print("\n== S7 drops")
    for c in CONDS:
        for b in BR:
            for f in files(c, b, "S7"):
                t = open(f, encoding="utf-8").read()
                if drop(t) or not ok(f):
                    print(f"{f}\tdrop={drop(t)} judge_ok={ok(f)}\t{t.strip().split(chr(10))[0][:120]}")
    print("\n== judge failures (S1, S2, S5, S6, S10-S19) and S9 letter-rule failures")
    for c in CONDS:
        for b in BR:
            for s in [x for x in ALL if x not in ("S3", "S4", "S7", "S8")]:
                for f in files(c, b, s):
                    if not ok(f):
                        v = verdict.get(f, {})
                        print(f"{f}\t{v.get('issues', v.get('first_sentence', 'S9 letter rule'))}")
    print("\n== S10 bold fake headings")
    for c in CONDS:
        for b in BR:
            for f in files(c, b, "S10"):
                t = open(f, encoding="utf-8").read()
                if fake_head(t):
                    print(f, re.findall(r"^\*\*[^*]+\*\*:?\s*$", t, re.M))
    print("\n== 확인 필요 lines in S13, S15")
    for c in CONDS:
        for b in BR:
            for f, l in flag_lines([f for s in ("S13", "S15") for f in files(c, b, s)]):
                print(f"{f}\t{l}")
    print("\n== 확인 필요 lines by scenario (all, without date words)")
    for c in CONDS:
        for b in BR:
            row = []
            for s in ALL:
                fl = flag_lines(files(c, b, s))
                if fl:
                    row.append(f"{s} {len(fl)}/{sum(not DATE.search(l) for _, l in fl)}")
            print(f"{c}-{b}: " + ", ".join(row))
    print("\n== skill not run (agent+short)")
    for b in BR:
        for f in [f for s in ALL for f in files("agent+short", b, s)]:
            if not skill.get(f, False):
                print(f)
