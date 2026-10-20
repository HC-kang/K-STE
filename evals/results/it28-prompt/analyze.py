# 28차 판정 기준 (A)-(F)와 따로 보고하는 지표를 계산한다. 저장소 루트에서 python3 -I evals/results/it28-prompt/analyze.py로 실행한다.
# 확인 실행의 출력(r21-r40, r7-r12)이 있으면 걸린 기준의 "합친 수" 판정도 함께 낸다. 파일을 쓰지 않는다.
# 문장 나누기, 헤지 정규식, S7 글자 기준, S12 날짜 정규식은 27차 analyze.py와 NOTES 27차 절과 같다.
import collections as C, glob, json, re, subprocess, sys

sys.path.insert(0, "evals")
import score as SC  # noqa: E402

R = "evals/results"
CS = ("A", "B")
drop = lambda t: not re.search(r"백업(이|에)? ?실패", t.strip().split("\n")[0])  # S7 글자 기준 탈락
RX = re.compile(r"운영팀(은|이|에서는|에서).*권장(합니다|한다)")  # (A) 권장 주체 변경, 문장 단위
HEDGE = re.compile(r"것 같|(으)?로 보(입니다|인다|이며|이고|여|임)|듯(합니다|하다|하며|하고|싶|해)|추정(합니다|한다|됩니다|된다|되며|되고|됨|하며|하고)"
                   r"|것으로 판단|가능성이 (있|높|크|존재)|아마|짐작")
TODAY = re.compile(r"오늘(이|은|이자|은 )?\s*\(?(10/20|10월 20일)|(10/20|10월 20일)\)?(이|은)? 오늘|오늘 날짜|이미 지(났|난|나)")  # 27차 S12 날짜 문장
# 판정기 이유로 센 권장 주체 변경: 판정 이유가 운영팀을 권장하는 쪽으로 읽힌다고 쓴 경우
RECO = re.compile(r"(operations team|운영팀)[^.]*(recommends|recommending|giving the recommendation|advis|the one who recommend|recommender|권장합니다)"
                  r"|(recommends|recommending|giving the recommendation|advis|recommender)[^.]*(operations team|운영팀)", re.I)

def sents(text):  # score.py score()와 같은 문장 나누기: 코드 블록 처리, 제목·구분선·표 줄 제외, 목록·인용 기호 제거
    text = SC.INLINE.sub("CODE", SC.FENCE.sub(SC.strip_code, text)); out = []
    for line in text.splitlines():
        if SC.HEADER.match(line) or SC.HR.match(line) or SC.TABLE.match(line) or not line.strip():
            continue
        out += SC.sentences(SC.QUOTE.sub("", SC.LIST.sub("", line)))
    return out

assert len(sents("# 제목\n- 첫째입니다. 둘째입니다.\n| a | b |\n```\nx = 1\n```\n셋째입니다.")) == 4  # CODEBLOCK. 포함
assert len(HEDGE.findall("원인으로 보입니다. 아마 그럴 것 같습니다.")) == 3 and not HEDGE.search("배포할 수 있습니다.")
assert drop("백업 완료를 확인하고, 실패하면 중단합니다.") and not drop("백업이 실패하면 중단합니다.\n")
assert RX.search("운영팀은 스테이징에서 먼저 검증하기를 권장합니다.") and not RX.search("스테이징 사전 검증이 권장됩니다.")
assert TODAY.search("오늘(10/20) 오전이라 이미 지났습니다") and not TODAY.search("운영 배포는 10/20 10:00 예정입니다.")

V = {}
for f in glob.glob(f"{R}/it28-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l); V[r["file"]] = r["verdict"]

def files(c, sids, runs, m="*"):
    return [f for r in runs for s in sids for f in sorted(glob.glob(f"{R}/it28-r{r}/{m}/full-{c}/{s}.md"))]

def judged(f):
    v = V[f]
    assert "error" not in v, f
    return (not v["meaning_changed"]) if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))

txt = lambda f: open(f, encoding="utf-8").read()
reco = lambda f: [s for s in sents(txt(f)) if RX.search(s)]
cnt = lambda c, sids, fn, runs: sum(fn(f) for f in files(c, sids, runs))
n = lambda c, sids, runs: len(files(c, sids, runs))
T20, T40, R6, R12 = range(1, 21), range(1, 41), range(1, 7), range(1, 13)
S11_19 = [f"S{i}" for i in range(11, 20)]
SIX_ALL = [f"S{i}" for i in range(1, 20) if i not in (5, 6, 7)]
NEW = ["S1", "S2", "S3", "S4", "S10", "S11", "S12", "S13", "S15", "S16", "S17", "S18", "S19"]  # S5 S6 S7 S9 S14 S8 제외
NO_S8 = [s for s in SIX_ALL if s != "S8"]
main = lambda c, sids6, sids20=("S5", "S6", "S7"): files(c, list(sids20), T20) + files(c, sids6, R6)
both = lambda c, sids6, sids20=("S5", "S6", "S7"): files(c, list(sids20), T40) + files(c, sids6, R12)
long25 = lambda f: sum(len(s.split()) > 25 for s in sents(txt(f)))
hedge2 = lambda f: sum(len(HEDGE.findall(s)) >= 2 for s in sents(txt(f)))

# (키, 이름, 본 실행 출력, 합친 출력, 출력 -> 수, 한계, 방향). 방향 +1은 B가 많으면 나쁘고, -1은 적으면 나쁘다.
CRIT = [("A", "S5 권장 주체 변경(글자 기준)", lambda c: files(c, ["S5"], T20), lambda c: files(c, ["S5"], T40), lambda f: bool(reco(f)), 4, +1),
        ("B", "S5-S7 판정 통과", lambda c: files(c, ["S5", "S6", "S7"], T20), lambda c: files(c, ["S5", "S6", "S7"], T40), judged, 12, -1),
        ("C", "S7 글자 기준 탈락", lambda c: files(c, ["S7"], T20), lambda c: files(c, ["S7"], T40), lambda f: drop(txt(f)), 6, +1),
        ("D", "S11-S19 판정 통과 합", lambda c: files(c, S11_19, R6), lambda c: files(c, S11_19, R12), judged, 7, -1),
        ("E", "25어절을 넘는 문장(S8 제외)", lambda c: main(c, NO_S8), lambda c: both(c, NO_S8), long25, 5, +1),
        ("F", "새 글의 헤지 2개 이상 문장", lambda c: files(c, NEW, R6), lambda c: files(c, NEW, R12), hedge2, 3, +1)]

def verdicts():
    rows = []
    for k, name, F1, F2, fn, lim, d in CRIT:
        a, b = sum(fn(f) for f in F1("A")), sum(fn(f) for f in F1("B"))
        ok = (b - a) * d <= lim
        row = [k, name, f"{a} ({len(F1('A'))})", f"{b} ({len(F1('B'))})", lim, ok]
        if not ok and len(F2("A")) > len(F1("A")):  # 확인 실행 출력이 있으면 합친 수로 다시 판정한다
            a2, b2 = sum(fn(f) for f in F2("A")), sum(fn(f) for f in F2("B"))
            row += [f"{a2} ({len(F2('A'))})", f"{b2} ({len(F2('B'))})", 2 * lim, (b2 - a2) * d <= 2 * lim]
        rows.append(row)
    return rows

DEF = {}
def defect_rows(c, m):  # 출력 파일 -> score.py 행
    if (c, m) not in DEF:
        dirs = sorted(glob.glob(f"{R}/it28-r*/{m}/full-{c}"))
        out = subprocess.run(["python3", "evals/score.py", "-v", *dirs], capture_output=True, text=True, check=True).stdout.splitlines()
        head = [h.strip() for h in out[0].split("|")]
        DEF[c, m] = {x[1]: {h: x[i] for i, h in enumerate(head) if h} for x in ([y.strip() for y in l.split("|")] for l in out[2:]) if x[1].endswith(".md")}
    return DEF[c, m]

def defects(c, m, runs=R6):  # r1-r6의 S1-S10 defects 합 / 회차 수
    rows = defect_rows(c, m); F = files(c, [f"S{i}" for i in range(1, 11)], runs, m)
    assert len(F) == 10 * len(runs), (c, m, len(F))
    return sum(int(rows[f]["defects"]) for f in F) / len(runs)

def s5_kind(issue):  # S5 판정기 실패의 종류(27차 표와 같은 종류). 첫 이유로 정한다.
    if RECO.search(issue): return "권장 주체"
    if "이에 따라" in issue or "따라서" in issue: return "이에 따라"
    if "관련하여" in issue: return "관련하여"
    return "기타"

short = lambda f: f.replace(f"{R}/", "")

if __name__ == "__main__":
    print("== 출력 수와 판정")
    for c in CS:
        out = n(c, ["S5", "S6", "S7"], T20) + n(c, SIX_ALL, R6)
        jv = [f for f in V if f"/full-{c}/" in f]
        print(f"full-{c} 본 실행 출력 {out}/216(모델 하나) 또는 /312(모델 둘), 모든 회차 출력 {n(c, ['S5', 'S6', 'S7'], T40) + n(c, SIX_ALL, R12)}, "
              f"판정(모든 회차) {len(jv)}, 판정 오류 {sum('error' in V[f] for f in jv)}")
    print("== 판정 기준 (A / B / 한계 / 결과, 확인 실행이 있으면 합친 A / B / 한계 / 결과). 괄호는 출력 수")
    ok_all = True
    for row in verdicts():
        ok_all &= row[-1]
        print(f"({row[0]}) {row[1]}:", " / ".join(str(x) for x in row[2:5]), "충족" if row[5] else "불충족",
              ("| 합친 " + " / ".join(str(x) for x in row[6:9]) + (" 충족" if row[9] else " 불충족")) if len(row) > 6 else "")
    print("-> 모든 기준 충족(확인 실행 반영)" if ok_all else "-> 기준 불충족 있음")

    print("== (A) 판정기 이유로 센 권장 주체 변경 (S5 실패 가운데 이유 하나라도 권장 주체를 말한 출력, 첫 이유가 권장 주체인 출력)")
    for c in CS:
        for runs, tag in ((T20, "본 실행"), (T40, "모든 회차")):
            F = [f for f in files(c, ["S5"], runs) if not judged(f)]
            print(f"full-{c} {tag}: 이유 하나라도 {sum(any(RECO.search(i) for i in V[f]['issues']) for f in F)}, "
                  f"첫 이유 {sum(s5_kind(V[f]['issues'][0]) == '권장 주체' for f in F)}, S5 실패 {len(F)}")
    print("== (A) 글자 기준 권장 주체 변경 출력의 문장 (모든 회차)")
    for c in CS:
        for f in files(c, ["S5"], T40):
            for s in reco(f):
                print(f"full-{c} {short(f)} | 판정 {'통과' if judged(f) else '실패'} | {s}")
    print("== S5 판정기 실패 종류 (첫 이유, 본 실행 / 모든 회차)")
    for c in CS:
        k1 = C.Counter(s5_kind(V[f]["issues"][0]) for f in files(c, ["S5"], T20) if not judged(f))
        k2 = C.Counter(s5_kind(V[f]["issues"][0]) for f in files(c, ["S5"], T40) if not judged(f))
        print(f"full-{c}", dict(k1), "|", dict(k2))

    print("== 시나리오별 판정 통과 (A / B, 모든 회차)")
    print({s: f"{cnt('A', [s], judged, T40)}/{n('A', [s], T40)} {cnt('B', [s], judged, T40)}/{n('B', [s], T40)}"
           for s in ("S1", "S2", "S5", "S6", "S7", "S10", *S11_19)})
    print("S7 탈락 모델별", {c: {m: sum(drop(txt(f)) for f in files(c, ["S7"], T40, m)) for m in ("haiku", "sonnet")} for c in CS},
          "| S7 탈락 중 판정기 실패", {c: f"{sum(not judged(f) for f in files(c, ['S7'], T40) if drop(txt(f)))}/{cnt(c, ['S7'], lambda f: drop(txt(f)), T40)}" for c in CS})

    print("== 따로 보고: 첫 문장 결론(S1 S2 S10, r1-r6), 실행 1회당 결함(score.py, S1-S10, r1-r6)")
    for c in CS:
        print(f"full-{c} 첫 문장 결론 {cnt(c, ['S1', 'S2', 'S10'], judged, R6)}/{n(c, ['S1', 'S2', 'S10'], R6)} | 결함 haiku {defects(c, 'haiku'):.2f} sonnet {defects(c, 'sonnet'):.2f}")
        for m in ("haiku", "sonnet"):
            rows = defect_rows(c, m)
            per = {s: sum(int(rows[f]["defects"]) for f in files(c, [s], R6, m)) for s in [f"S{i}" for i in range(1, 11)]}
            print(f"   {m} 시나리오별 결함 합(r1-r6)", per)

    print("== 따로 보고: 문장 길이와 헤지 (S8 제외, 본 실행 출력)")
    for c in CS:
        F = main(c, NO_S8)
        mx = [max([len(s.split()) for s in sents(txt(f))] or [0]) for f in F]
        S = [s for f in F for s in sents(txt(f))]; L = [len(s.split()) for s in S]
        h = [len(HEDGE.findall(s)) for s in S]
        print(f"full-{c} 출력 {len(F)} max_eojeol 평균 {sum(mx)/len(F):.2f} max>25 출력 {sum(x > 25 for x in mx)} | 문장 {len(S)} "
              f">20어절 {sum(x > 20 for x in L)} >25어절 {sum(x > 25 for x in L)} | 헤지 일치 {sum(h)} 헤지 2개 이상 문장 {sum(x >= 2 for x in h)} "
              f"(S5 {sum(hedge2(f) for f in files(c, ['S5'], T20))}, 새 글 {sum(hedge2(f) for f in files(c, NEW, R6))})")
        for f in F:
            for s in sents(txt(f)):
                if len(s.split()) > 25: print(f"   25어절 초과({len(s.split())}): {short(f)} | {s[:200]}")
        for f in files(c, NEW, R6) + files(c, ["S9", "S14"], R6):
            for s in sents(txt(f)):
                if len(HEDGE.findall(s)) >= 2: print(f"   헤지 2개 이상: {short(f)} | {s[:200]}")
    # score.py의 max_eojeol이 위 계산과 같은지 확인한다(같은 문장 나누기를 쓰는지).
    for c in CS:
        for m in ("haiku", "sonnet"):
            rows = defect_rows(c, m)
            for f in files(c, ["S1", "S5", "S10", "S16"], R6, m):
                assert int(rows[f]["max_eojeol"]) == max([len(s.split()) for s in sents(txt(f))] or [0]), f

    print("== 따로 보고: S12 날짜 문장 (27차 정규식, 출력 수와 문장 수)")
    for c in CS:
        for runs, tag in ((R6, "본 실행"), (R12, "모든 회차")):
            F = files(c, ["S12"], runs)
            k = [sum(bool(TODAY.search(s)) for s in sents(txt(f))) for f in F]
            print(f"full-{c} {tag}: 출력 {sum(x > 0 for x in k)}/{len(F)}, 문장 {sum(k)}")

    print("== 판정기가 실패로 본 출력 (모든 회차)")
    for f in sorted(V, key=lambda x: (x.split("/")[4], x.split("/")[-1], int(x.split("/")[2].split("-r")[1]), x)):
        if not judged(f):
            tag = (" [S7 탈락]" if drop(txt(f)) else "") if f.endswith("/S7.md") else ""
            print(short(f) + tag, "|", " / ".join(V[f].get("issues", [V[f].get("first_sentence", "")]))[:300])
