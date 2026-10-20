# 27차 판정 기준 (a)-(h)와 따로 보고하는 지표를 계산한다. 저장소 루트에서 python3 -I evals/results/it27-prompt/analyze.py로 실행한다.
# 확인 실행의 출력(r4-r6의 추가 시나리오, r11-r20)이 있으면 "합친 수" 판정도 함께 낸다. 파일을 쓰지 않는다.
import collections as C, glob, json, re, subprocess, sys

sys.path.insert(0, "evals")
import score as SC  # noqa: E402

R = "evals/results"
CONDS, CS = ("full", "agent+short"), ("A", "B")
RW = ("S5", "S6", "S7", "S9", "S14")
F_SIDS = ("S11", "S13", "S14", "S15", "S17", "S18", "S19")
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])  # S7 글자 기준 탈락
HEDGE = re.compile(r"것 같|(으)?로 보(입니다|인다|이며|이고|여|임)|듯(합니다|하다|하며|하고|싶|해)|추정(합니다|한다|됩니다|된다|되며|되고|됨|하며|하고)"
                   r"|것으로 판단|가능성이 (있|높|크|존재)|아마|짐작")
DONE = re.compile(r"마쳤습니다|끝냈습니다|끝났습니다|완료했습니다")
RESULT = re.compile(r"\d+\s*(개|건|명)|\d(\.\d+)?:1(?!\d)")
SPLIT = re.compile(r"(?<=[.?!])\s+")

def sents(text):  # score.py score()와 같은 문장 나누기: 코드 블록 처리, 제목·구분선·표 줄 제외, 목록·인용 기호 제거
    text = SC.INLINE.sub("CODE", SC.FENCE.sub(SC.strip_code, text)); out = []
    for line in text.splitlines():
        if SC.HEADER.match(line) or SC.HR.match(line) or SC.TABLE.match(line) or not line.strip():
            continue
        out += SC.sentences(SC.QUOTE.sub("", SC.LIST.sub("", line)))
    return out

def line_sents(text):  # 완료 동사용: 표 줄도 포함한 모든 줄
    return [s for l in text.splitlines() if l.strip() for s in SPLIT.split(SC.LIST.sub("", l).strip()) if s.strip()]

assert len(sents("# 제목\n- 첫째입니다. 둘째입니다.\n| a | b |\n```\nx = 1\n```\n셋째입니다.")) == 4  # CODEBLOCK. 포함
assert len(HEDGE.findall("원인으로 보입니다. 아마 그럴 것 같습니다.")) == 3 and not HEDGE.search("배포할 수 있습니다.")
assert RESULT.search("14개 전부 통과") and RESULT.search("3.9:1") and not RESULT.search("15:10 배포, 10/20 10:00 예정")
assert drop("백업 완료를 확인하고, 실패하면 중단합니다.") and not drop("백업이 실패하면 중단합니다.\n")

V = {}
for f in glob.glob(f"{R}/it27-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]
TR = {}
for f in glob.glob(f"{R}/it27-r*/*/agent+short-*/trace.txt"):
    for l in open(f, encoding="utf-8"):
        sid, sk, rd = l.rstrip("\n").split("\t")[:3]
        TR[f.rsplit("/", 1)[0] + f"/{sid}.md"] = ("k-ste" in sk, rd)

def files(cd, c, sids, runs, m="*"):
    return [f for r in runs for s in sids for f in sorted(glob.glob(f"{R}/it27-r{r}/{m}/{cd}-{c}/{s}.md"))]

def judged(f):
    v = V[f]
    assert "error" not in v, f
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

txt = lambda f: open(f, encoding="utf-8").read()
cnt = lambda cd, c, sids, fn, runs: sum(bool(fn(f)) for f in files(cd, c, sids, runs))
n = lambda cd, c, sids, runs: len(files(cd, c, sids, runs))
TEN, TEN2, R3, R6 = range(1, 11), range(1, 21), range(1, 4), range(1, 7)

DEF = {}
def defect_rows(cd, c, m):  # 출력 파일 -> score.py defects
    key = (cd, c, m)
    if key not in DEF:
        dirs = sorted(glob.glob(f"{R}/it27-r*/{m}/{cd}-{c}"))
        out = subprocess.run(["python3", "evals/score.py", "-v", *dirs], capture_output=True, text=True, check=True).stdout.splitlines()
        head = [h.strip() for h in out[0].split("|")]
        DEF[key] = {x[1]: {h: x[i] for i, h in enumerate(head) if h} for x in ([y.strip() for y in l.split("|")] for l in out[2:]) if x[1].endswith(".md")}
    return DEF[key]

def defects(cd, c, m, runs):  # r1-r3(또는 r1-r6)의 S1-S10 defects 합 / 회차 수
    rows = defect_rows(cd, c, m)
    F = files(cd, c, [f"S{i}" for i in range(1, 11)], runs, m)
    assert len(F) == 10 * len(runs), (cd, c, m, len(F))
    return sum(int(rows[f]["defects"]) for f in F) / len(runs)

# (키, 이름, 시나리오, 지표, 본 실행 회차, 확인 실행까지의 회차, 한계, 방향): 방향 +1은 B가 많으면 나쁘고, -1은 적으면 나쁘다.
CRIT = [("a", "S7 글자 기준 탈락", ["S7"], lambda f: drop(txt(f)), TEN, TEN2, 3, +1),
        ("b", "S5-S7 판정 통과", ["S5", "S6", "S7"], judged, TEN, TEN2, 6, -1),
        ("c S12", "S12 판정 통과", ["S12"], judged, TEN, TEN2, 2, -1),
        ("c S16", "S16 판정 통과", ["S16"], judged, TEN, TEN2, 2, -1),
        ("f", "S11 S13 S14 S15 S17 S18 S19 판정 통과 합", list(F_SIDS), judged, R3, R6, 3, -1),
        ("g", "첫 문장 결론 S1 S2 S10", ["S1", "S2", "S10"], judged, R3, R6, 1, -1)]

def verdicts(cd):
    rows = []
    for k, name, sids, fn, r1, r2, lim, d in CRIT:
        a, b = cnt(cd, "A", sids, fn, r1), cnt(cd, "B", sids, fn, r1); na, nb = n(cd, "A", sids, r1), n(cd, "B", sids, r1)
        ok = (b - a) * d <= lim
        row = [k, name, f"{a}/{na}", f"{b}/{nb}", lim, ok]
        if not ok and n(cd, "A", sids, [r for r in r2 if r not in r1]):  # 확인 실행 출력이 있으면 합친 수로 다시 판정한다
            a2, b2 = cnt(cd, "A", sids, fn, r2), cnt(cd, "B", sids, fn, r2)
            row += [f"{a2}/{n(cd, 'A', sids, r2)}", f"{b2}/{n(cd, 'B', sids, r2)}", 2 * lim, (b2 - a2) * d <= 2 * lim]
        rows.append(row)
    for m in ("haiku", "sonnet"):
        a, b = defects(cd, "A", m, R3), defects(cd, "B", m, R3)
        ok = b - a <= 2.0 + 1e-9
        row = [f"h {m}", f"실행 1회당 결함 {m}", f"{a:.1f}", f"{b:.1f}", 2.0, ok]
        if not ok and len(files(cd, "A", [f"S{i}" for i in range(1, 11)], R6, m)) == 60:
            a2, b2 = defects(cd, "A", m, R6), defects(cd, "B", m, R6)
            row += [f"{a2:.2f}", f"{b2:.2f}", 2.0, b2 - a2 <= 2.0 + 1e-9]
        rows.append(row)
    return rows

if __name__ == "__main__":
    print("== 출력 수와 판정")
    for cd in CONDS:
        for c in CS:
            out = n(cd, c, ["S5", "S6", "S7", "S12", "S16"], TEN) + n(cd, c, [f"S{i}" for i in (1, 2, 3, 4, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19)], R3)
            jv = [f for f in V if f"/{cd}-{c}/" in f]
            print(f"{cd}-{c} 본 실행 출력 {out}/184, 판정(모든 회차) {len(jv)}, 판정 오류 {sum('error' in V[f] for f in jv)}")
    print("== 판정 기준 (A / B / 한계 / 결과, 확인 실행이 있으면 합친 A / B / 한계 / 결과)")
    final = {}
    for cd in CONDS:
        ok_all = True
        for row in verdicts(cd):
            last = row[-1]; ok_all &= last
            print(cd, f"({row[0]}) {row[1]}:", " / ".join(str(x) for x in row[2:5]), "충족" if row[5] else "불충족",
                  ("| 합친 " + " / ".join(str(x) for x in row[6:9]) + (" 충족" if row[9] else " 불충족")) if len(row) > 6 else "")
        final[cd] = ok_all
        print(cd, "-> 모든 기준 충족(확인 실행 반영)" if ok_all else "-> 기준 불충족 있음")

    print("== 시나리오별 판정 통과 (A / B, 모든 회차)")
    for cd in CONDS:
        print(cd, {s: f"{cnt(cd, 'A', [s], judged, TEN2)}/{n(cd, 'A', [s], TEN2)} {cnt(cd, 'B', [s], judged, TEN2)}/{n(cd, 'B', [s], TEN2)}"
                   for s in ("S1", "S2", "S5", "S6", "S7", "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19")})
        print(cd, "S7 탈락 모델별", {c: {m: sum(drop(txt(f)) for f in files(cd, c, ["S7"], TEN2, m)) for m in ("haiku", "sonnet")} for c in CS},
              "| S7 탈락 중 판정기 실패", {c: f"{sum(not judged(f) for f in files(cd, c, ['S7'], TEN2) if drop(txt(f)))}/{cnt(cd, c, ['S7'], lambda f: drop(txt(f)), TEN2)}" for c in CS})

    print("== 문장 길이와 헤지 (S8 제외, 본 실행 출력)")
    for cd in CONDS:
        for c in CS:
            F = files(cd, c, ["S5", "S6", "S7", "S12", "S16"], TEN) + files(cd, c, [f"S{i}" for i in (1, 2, 3, 4, 9, 10, 11, 13, 14, 15, 17, 18, 19)], R3)
            mx = [max([len(s.split()) for s in sents(txt(f))] or [0]) for f in F]
            S = [s for f in F for s in sents(txt(f))]; L = [len(s.split()) for s in S]
            h = [len(HEDGE.findall(s)) for s in S]
            print(f"{cd}-{c} 출력 {len(F)} max_eojeol 평균 {sum(mx)/len(F):.2f} max>25 출력 {sum(x > 25 for x in mx)} | 문장 {len(S)} "
                  f">20어절 {sum(x > 20 for x in L)} >25어절 {sum(x > 25 for x in L)} | 헤지 일치 {sum(h)} 헤지 2개 이상 문장 {sum(x >= 2 for x in h)}")
            for f, s in [(f, s) for f in F for s in sents(txt(f)) if len(HEDGE.findall(s)) >= 2]:
                print("   헤지 2개 이상:", f.replace(f"{R}/", ""), "|", s[:160])
        # score.py의 max_eojeol이 위 계산과 같은지 확인한다(같은 문장 나누기를 쓰는지).
        for c in CS:
            for m in ("haiku", "sonnet"):
                rows = defect_rows(cd, c, m)
                for f in files(cd, c, ["S1", "S5", "S10", "S16"], R3, m):
                    assert int(rows[f]["max_eojeol"]) == max([len(s.split()) for s in sents(txt(f))] or [0]), f

    print("== S12와 S16의 완료 동사 문장 (본 실행, 각 20회)")
    for cd in CONDS:
        for c in CS:
            for s in ("S12", "S16"):
                k = res = 0; ex = []
                for f in files(cd, c, [s], TEN):
                    L = line_sents(txt(f))
                    for i, x in enumerate(L):
                        if DONE.search(x):
                            k += 1; hit = bool(RESULT.search(x) or (i + 1 < len(L) and RESULT.search(L[i + 1])))
                            res += hit
                            if not hit: ex.append(f"{f.replace(R + '/', '')} | {x[:120]}")
                print(f"{cd}-{c} {s}: 완료 동사 문장 {k}, 그 문장이나 다음 문장에 결과 수치 {res}, 수치 없음 {k - res}")
                for e in ex: print("   수치 없음:", e)

    print("== 스킬, references, 확인 필요 (본 실행)")
    for cd in CONDS:
        for c in CS:
            F = files(cd, c, ["S5", "S6", "S7", "S12", "S16"], TEN) + files(cd, c, [f"S{i}" for i in (1, 2, 3, 4, 8, 9, 10, 11, 13, 14, 15, 17, 18, 19)], R3)
            q = C.Counter()
            for f in F: q[f.split("/")[-1][:-3]] += sum("확인 필요" in l for l in txt(f).split("\n"))
            line = f"{cd}-{c} 확인 필요 줄 {sum(q.values())} {dict(sorted((k, v) for k, v in q.items() if v))}"
            if cd == "agent+short":
                rw = [f for f in F if f.split("/")[-1][:-3] in RW]
                line += (f" | 스킬 재작성·검수 {sum(TR[f][0] for f in rw)}/{len(rw)} 모든 출력 {sum(TR[f][0] for f in F)}/{len(F)}"
                         f" | rewrite.md 읽음(재작성·검수) {sum('references/rewrite.md' in TR[f][1] for f in rw)}/{len(rw)}"
                         f" | word-swaps.md 읽음(모든 출력) {sum('word-swaps' in TR[f][1] for f in F)}")
            print(line)
        if cd == "agent+short":
            print("스킬 미실행 출력:", [f.replace(f"{R}/", "") for f in sorted(TR) if not TR[f][0] and "/S8.md" not in f])

    print("== 판정기가 실패로 본 출력 (모든 회차)")
    for f in sorted(V, key=lambda x: (x.split("/")[3], x.split("/")[4], int(x.split("/")[2].split("-r")[1]), x)):
        if not judged(f):
            sk = "" if "/full-" in f else (" skill" if TR[f][0] else " no-skill")
            print(f.replace(f"{R}/", "") + sk, "|", " / ".join(V[f].get("issues", [V[f].get("first_sentence", "")]))[:260])
