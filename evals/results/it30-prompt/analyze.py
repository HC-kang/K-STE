#!/usr/bin/env python3
"""30차 지표(README 평가 표). 저장소 루트에서 `python3 -I evals/results/it30-prompt/analyze.py [-v]`로 실행한다.
-v는 판정기 실패를 함께 출력한다."""
import glob
import json
import re
import subprocess
import sys

R = "evals/results"
CONDS, MODELS = ["base", "short", "full", "agent+short"], ["haiku", "sonnet"]
S = lambda *n: [f"S{i}" for i in n]
ID = re.compile(r"(?<![A-Za-z0-9])K(\d+)(?![0-9])")
cells = lambda l: [c.strip().replace("**", "").strip() for c in l.strip().strip("|").split("|")]


def s9_pass(text):  # 23차 글자 기준(26차 analyze.py와 같다)
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


T = "| 규칙 | 원문 | 고친 글 |\n|---|---|---|\n| K9 | a | b |\n| K0, K15 | c | d |\n"
assert s9_pass(T) and not s9_pass(T + "| K16 | e | f |\n") and not s9_pass("| 문제 | 원문 | 고친 글 |\n|---|---|---|\n| K3 | a | b |")

verdict = {}
for f in glob.glob(f"{R}/it30-r*/judge.jsonl") + glob.glob(f"{R}/it30d-r*/judge.jsonl"):
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        verdict[r["file"]] = r["verdict"]
skill = {}
for f in glob.glob(f"{R}/it30-r*/*/agent+short/trace.txt") + glob.glob(f"{R}/it30d-r*/*/agent+short/trace.txt"):
    for l in open(f, encoding="utf-8"):
        sid, rest = l.rstrip("\n").split("\t", 1)
        skill[f.rsplit("/", 1)[0] + "/" + sid + ".md"] = "k-ste" in rest.split("\t")[0]


SHIFTED = {"S12", "S13", "S15", "S16", "S17", "S18"}  # 날짜를 미룬 재측정(it30d)을 쓴다. run-dates.sh 참고


def files(c, sids, model=None, past=False):
    run = lambda s: "it30" if past or s not in SHIFTED else "it30d"
    out = [f"{R}/{run(s)}-r{r}/{m}/{c}/{s}.md" for r in (1, 2, 3) for m in MODELS for s in sids if model in (None, m)]
    missing = [f for f in out if not glob.glob(f)]
    if missing:
        raise SystemExit(f"no output: {missing[:3]}")
    return out


def ok(f):
    sid, v = f.split("/")[-1][:-3], verdict.get(f)
    if sid == "S9":
        return s9_pass(open(f, encoding="utf-8").read())
    if sid == "S8":
        return "K-STE 규칙은 홍보 문구" in open(f, encoding="utf-8").read()
    if v is None or "error" in v:
        raise SystemExit(f"no verdict: {f}")
    return not v["meaning_changed"] if "meaning_changed" in v else v.get("conclusion_first", v.get("pass"))


def cnt(F):
    return f"{sum(map(ok, F))}/{len(F)}"


def defects(c, m):  # 29차와 같다: r1-r3의 S1-S10 defects 합 / 3
    out = subprocess.run(["python3", "evals/score.py", "-v", *sorted(glob.glob(f"{R}/it30-r[123]/{m}/{c}"))],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    head = [h.strip() for h in out[0].split("|")]
    row = {x[1]: dict(zip(head, x)) for x in ([y.strip() for y in l.split("|")] for l in out[2:]) if x[1].endswith(".md")}
    F = files(c, S(*range(1, 11)), m)
    return sum(int(row[f]["defects"]) for f in F) / 3


ROWS = [
    ("어휘 통제 시나리오 통과 (S11-S15)", S(11, 12, 13, 14, 15)),
    ("목록 밖 모호어 시나리오 통과 (S16)", S(16)),
    ("완료 동사 시나리오 통과 (S17)", S(17)),
    ("실행일과 기한 시나리오 통과 (S18, S19)", S(18, 19)),
    ("재작성에서 뜻이 바뀌지 않음 (S5-S7)", S(5, 6, 7)),
    ("답변의 첫 문장이 결론 (S1, S2, S10)", S(1, 2, 10)),
]
print("| 지표 | " + " | ".join(CONDS) + " |\n|---|" + "---:|" * len(CONDS))
for name, sids in ROWS:
    print(f"| {name} | " + " | ".join(cnt(files(c, sids)) for c in CONDS) + " |")
for m in MODELS:
    print(f"| 독자가 보는 결함, 실행 1회당 ({m}, S1-S10) | " + " | ".join(f"{defects(c, m):.1f}" for c in CONDS) + " |")
print("| 홍보 문구 요청에 범위 밖이라고 알림 (S8) | " + " | ".join(cnt(files(c, S(8))) for c in CONDS) + " |")
print("| 검수 요청에 표와 실제 규칙 ID로 답함 (S9) | " + " | ".join(cnt(files(c, S(9))) for c in CONDS) + " |")
sk = files("agent+short", S(5, 6, 7, 9, 14))
print(f"| 재작성·검수 요청에 스킬 실행 | - | - | - | {sum(skill.get(f, False) for f in sk)}/{len(sk)} |")

drop = lambda f: not re.search(r"백업(이|에)? ?실패", open(f, encoding="utf-8").read().strip().split("\n")[0])  # 21-29차 글자 기준
print("| S7 \"백업이\" 탈락 (글자 기준) | " + " | ".join(f"{sum(map(drop, files(c, S(7))))}/6" for c in CONDS) + " |")

allf = [f for c in CONDS for f in files(c, S(*range(1, 20)))]
errs = sum(1 for v in verdict.values() if "error" in v)
print(f"\n출력 {len(allf)}개(그중 날짜를 미룬 재측정 {sum('/it30d-' in f for f in allf)}개), 판정 {len(verdict)}건, 판정 오류 {errs}건")

# 원래 날짜(실행일보다 앞선 예정일과 기한)로 잰 여섯 시나리오. 판정 이유에 실행일(10/28)이 나온 실패를 따로 센다.
dated = sorted(SHIFTED, key=lambda s: int(s[1:]))
print("\n원래 날짜의 여섯 시나리오(it30): 통과 / 판정 이유에 10/28이나 '오늘'이 나온 실패 / 미룬 날짜(it30d)의 통과")
for c in CONDS:
    P_, N_ = files(c, dated, past=True), files(c, dated)
    today = [f for f in P_ if not ok(f) and re.search(r"10/28|10월 28일|today|오늘", json.dumps(verdict[f], ensure_ascii=False))]
    print(f"| {c} | {sum(map(ok, P_))}/{len(P_)} | {len(today)} | {sum(map(ok, N_))}/{len(N_)} |")
for c in CONDS:
    hit = [f for f in files(c, dated) if re.search(r"10/28|10월 28일", open(f, encoding="utf-8").read())]
    print(f"{c}: 미룬 날짜 출력에 실행일(10/28)이 나온 출력 {len(hit)}/{len(files(c, dated))}")
if "-v" in sys.argv:
    print("\n판정기 실패")
    for c in CONDS:
        for f in files(c, S(1, 2, 5, 6, 7, *range(10, 20))):
            if not ok(f):
                v = verdict[f]
                print(f"{f}\t{v.get('issues', v.get('first_sentence', ''))}")
