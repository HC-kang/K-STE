#!/usr/bin/env python3
"""X4-recall: Grok answers the phase-1 questions without options; free responses are graded blind.

Design and pre-registered criteria: PREREG.md.
Usage: python3 run.py <pilot|main|analyze|selftest>
Outputs are cached under out/; a call is skipped when its output file exists.
"""
import json
import os
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# forced, not setdefault: six experiments share the accounts (exp/BRIEF.md)
os.environ["KSTE_CODEX_HOME"] = str(Path.home() / ".cache/k-ste-eval/codex-home-X4-recall")
os.environ["KSTE_CODEX_AUTH"] = ("/Users/ford/Library/Application Support/orca/codex-accounts/"
                                 "e7b29eca-10d5-4ace-b7f2-cacabc9f7b3e/home/auth.json")
os.environ.update(KSTE_LIMIT_GROK="2", KSTE_LIMIT_CODEX="2", KSTE_LIMIT_CLAUDE="3")
sys.path.insert(0, str(HERE.parent.parent))
import reader as R  # noqa: E402

OUT = HERE / "out"
WRITER = "sonnet"
CONDS = R.CONDITIONS
PAIRS = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]
GRADES = ["맞음", "틀림", "알 수 없음"]
MAX_CHARS = 30
SAMPLE = 0.2
PILOT_ITEMS = 4  # 4 of 40 fact lists = 16 of 160 texts (10%)

READ = """{persona}
다음 글을 읽고 질문에 답하라. 글에 쓰인 내용만 근거로 답한다. 보기는 없다. 질문마다 답을 30자 이내로 직접 쓴다. 글만으로 판단할 수 없으면 "알 수 없음"이라고 쓴다.

<글>
{text}
</글>

{questions}

출력은 JSON 한 줄이다. 예: {{"Q1": "답", "Q2": "알 수 없음"}}"""

GRADE = """너는 독해 시험의 채점자다. 독자가 글을 읽고 보기 없이 직접 쓴 답을 채점한다. 너는 그 글을 보지 않는다. 질문, 정답, 응답만 보고 판정한다.

- 맞음: 응답의 뜻이 정답과 같다. 표현, 어순, 날짜와 시각의 형식이 달라도 뜻이 같으면 맞음이다. 질문이 묻는 핵심이 정답과 같고 정답과 어긋나는 내용이 없으면, 정답의 부가 정보가 빠져도 맞음이다.
- 틀림: 응답이 정답과 다른 날짜, 시각, 사람, 수치, 장소, 대상, 조건, 의무 강도(해야 한다, 해도 된다, 하지 않아도 된다)를 쓴다. 또는 질문이 묻는 핵심이 빠졌다. 후보를 여러 개 쓰고 그중 정답과 다른 것이 있으면 틀림이다.
- 알 수 없음: 응답이 답을 하지 않고, 글만으로는 알 수 없다거나 글에 없다고 한다.

{block}

출력은 JSON 한 줄이다. 응답 번호마다 "맞음", "틀림", "알 수 없음" 가운데 하나를 쓴다. 예: {{"R1": "맞음", "R2": "틀림"}}"""


def question(q):
    return re.sub(r"^다음 중\s*", "", q["q"])  # "다음 중" points at options that are no longer shown


def gold(q):
    return q[q["answer"]]


# ---------- machine grading (dates, times, numbers) ----------

def _hm(h, m, pm=False):
    h = int(h) + (12 if pm and int(h) < 12 else 0)
    return f" {h}:{int(m or 0):02d} "


def canon(s, drop_until=False):
    s = re.sub(r"\(\s*[월화수목금토일](?:요일)?\s*\)", " ", s.lower())
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)
    s = re.sub(r"(\d+)\s*만\s*원", lambda m: f"{int(m[1]) * 10000}원", s)
    s = re.sub(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", lambda m: f" {int(m[1])}/{int(m[2])} ", s)
    s = re.sub(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", lambda m: f" {int(m[1])}/{int(m[2])} ", s)
    s = re.sub(r"(오전|오후)\s*(\d{1,2})(?::(\d{2})|시(?![간작])(?:\s*(\d{1,2})\s*분)?)",
               lambda m: _hm(m[2], m[3] or m[4], m[1] == "오후"), s)
    s = re.sub(r"(?<![\d/])(\d{1,2}):(\d{2})", lambda m: _hm(m[1], m[2]), s)
    s = re.sub(r"(?<![\d/])(\d{1,2})시(?![간작])(?:\s*(\d{1,2})\s*분|\s*(반))?",
               lambda m: _hm(m[1], m[2] or (30 if m[3] else 0)), s)
    s = re.sub(r"\s*(?:부터|~|-|–)\s*", " ~ ", s)
    if drop_until:
        s = s.replace("까지", " ")
    s = re.sub(r"[.,·!?\"'“”‘’]", " ", s)
    return " ".join(s.split())


TOKEN = r"\d+/\d+|\d+:\d\d|\d+(?:[a-z%]+|[가-힣]{1,2})?|~|이내"


def eligible(g):
    """Gold option made only of dates, times, numbers with units."""
    return bool(re.fullmatch(rf"(?:(?:{TOKEN})\s*)+", canon(g, drop_until=True)))


def nums(s):
    return set(re.findall(r"\d+/\d+|\d+:\d\d|\d+", canon(s, drop_until=True)))


def auto(q, resp):
    """Machine grade, or None when the model grader must decide. A mismatch is never auto-wrong."""
    if re.sub(r"[\s.\"'“”]", "", resp).startswith("알수없"):
        return "알 수 없음"
    drop = bool(re.search(r"까지|마감|기한", q["q"]))  # deadline question: "까지" in an answer is implied
    g = gold(q)
    if eligible(g) and canon(resp, drop).replace(" ", "") == canon(g, drop).replace(" ", ""):
        return "맞음"
    return None


# ---------- model calls (cached) ----------

def cached(f, fn):
    if f.exists():
        return json.loads(f.read_text())
    for i in range(3):
        try:
            rec = fn()
            break
        except (ValueError, KeyError) as e:
            R.log(f"retry parse {f} {i + 1}/3: {e}")
    else:
        raise RuntimeError(f"parse failed 3 times: {f}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


def read(it, c):
    qs = it["questions"]
    text = (R.OUT / "texts" / c / WRITER / f"{it['id']}.md").read_text()
    p = READ.format(persona=R.persona_for(f"X4-recall/{c}/{it['id']}"), text=text,
                    questions="\n".join(f"Q{i + 1}. {question(q)}" for i, q in enumerate(qs)))

    def fn():
        raw = R.call("grok", p)
        a = R.first_json(raw)
        return {"raw": raw, "answers": [str(a[f"Q{i + 1}"]).strip() for i in range(len(qs))]}
    return cached(OUT / "answers" / c / f"{it['id']}.json", fn)


def grade_schema(n):
    keys = [f"R{k + 1}" for k in range(n)]
    return {"type": "object", "additionalProperties": False, "required": keys,
            "properties": {k: {"type": "string", "enum": GRADES} for k in keys}}


def grade_prompt(it, answers, idx):
    qs = it["questions"]
    return GRADE.format(block="\n\n".join(
        f"R{k + 1}\n질문: {question(qs[i])}\n정답: {gold(qs[i])}\n응답: {answers[i]}" for k, i in enumerate(idx)))


def model_grade(who, it, c, answers):
    """Codex grades what the machine left; Haiku re-grades all answers of a sampled text."""
    idx = ([i for i, (q, a) in enumerate(zip(it["questions"], answers)) if auto(q, a) is None]
           if who == "codex" else list(range(len(answers))))
    norm = {g.replace(" ", ""): g for g in GRADES}

    def fn():
        if not idx:
            return {"idx": [], "grades": []}
        raw = R.call(who, grade_prompt(it, answers, idx), grade_schema(len(idx)))
        g = R.first_json(raw)
        out = [norm.get(str(g[f"R{k + 1}"]).replace(" ", "")) for k in range(len(idx))]
        if None in out:
            raise ValueError(f"bad grade in {raw[:200]}")
        return {"idx": idx, "raw": raw, "grades": out}
    return cached(OUT / "grades" / who / c / f"{it['id']}.json", fn)


def sample_keys():
    keys = sorted(f"{c}/{it['id']}" for it in R.items() for c in CONDS)
    return set(random.Random("X4").sample(keys, round(SAMPLE * len(keys))))


def cmd_run(n_items=None):
    its = R.items()[:n_items] if n_items else R.items()
    sample = sample_keys()

    def one(job):
        it, c = job
        try:
            ans = read(it, c)["answers"]
            model_grade("codex", it, c, ans)
            if f"{c}/{it['id']}" in sample:
                model_grade("haiku", it, c, ans)
            return True
        except Exception as e:  # ponytail: log and move on; a rerun resumes from the cache
            R.log(f"FAIL {c}/{it['id']}: {e}")
            return False

    ok = R.pmap(one, [(it, c) for it in its for c in CONDS], workers=6)
    R.log(f"texts done {sum(ok)}/{len(ok)}")


# ---------- analysis ----------

LETTER = {"맞음": "A", "틀림": "B", "알 수 없음": "E"}


def rates(gs):
    """acc = correct, misread = wrong answer (not 알 수 없음), abstain = 알 수 없음; shares of all answers."""
    return R.rates([{"answers": [LETTER[g] for g in gs], "gold": ["A"] * len(gs)}])


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in set(a) | set(b))
    return None if pe == 1 else (po - pe) / (1 - pe)


def compare(G, fids):
    """G[(cond, fid)] = grades. Paired differences x - y per fact list, bootstrapped."""
    tests = {}
    for x, y in PAIRS:
        for m in ("acc", "misread", "abstain"):
            d = [rates(G[(x, f)])[m] - rates(G[(y, f)])[m] for f in fids]
            mean, lo, hi = R.boot(d)
            tests[f"{m} {x}-{y}"] = {"items": len(d), "diff": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                                     "ci_excludes_0": lo > 0 or hi < 0}
    return tests


def summarize(G, fids):
    return {c: {k: round(v, 4) if isinstance(v, float) else v
                for k, v in rates([g for f in fids for g in G[(c, f)]]).items()} for c in CONDS}


def final(it, c):
    ans = json.loads((OUT / "answers" / c / f"{it['id']}.json").read_text())["answers"]
    cx = json.loads((OUT / "grades" / "codex" / c / f"{it['id']}.json").read_text())
    g = [auto(q, a) for q, a in zip(it["questions"], ans)]
    src = ["auto" if x else None for x in g]
    for i, x in zip(cx["idx"], cx["grades"]):  # machine grade wins; pilot Codex files may cover more answers
        if g[i] is None:
            g[i], src[i] = x, "codex"
    assert None not in g, f"ungraded answer in {c}/{it['id']}"
    return ans, g, src


def cmd_analyze():
    its = [it for it in R.items() if all((OUT / "grades" / "codex" / c / f"{it['id']}.json").exists()
                                         for c in CONDS)]
    fids = [it["id"] for it in its]
    G, A, S = {}, {}, {}
    for it in its:
        for c in CONDS:
            A[(c, it["id"])], G[(c, it["id"])], S[(c, it["id"])] = final(it, c)
    rep = {"items": len(its), "summary": summarize(G, fids), "tests": compare(G, fids)}
    for c in CONDS:
        s = rep["summary"][c]
        s["chars_mean"] = round(sum(len((R.OUT / "texts" / c / WRITER / f"{f}.md").read_text()) for f in fids) / len(fids))
        mc = [json.loads((R.OUT / "answers" / c / WRITER / "grok" / f"{f}.json").read_text()) for f in fids]
        s["mc_acc_phase1"] = round(R.rates(mc)["acc"], 4)
        s["over_30_chars"] = sum(len(a) > MAX_CHARS for f in fids for a in A[(c, f)])
        s["graded_by"] = {k: sum(x == k for f in fids for x in S[(c, f)]) for k in ("auto", "codex")}
    b = rep["summary"]["base"]
    rep["ceiling_broken"] = b["acc"] <= 0.95 or b["misread"] >= 0.03
    # sensitivity: drop questions no condition answered right (may lack a unique answer without options)
    drop = {(f, i) for f in fids for i in range(len(G[("base", f)])) if all(G[(c, f)][i] != "맞음" for c in CONDS)}
    G2 = {k: [g for i, g in enumerate(v) if (k[1], i) not in drop] for k, v in G.items()}
    rep["sensitivity"] = {"dropped_questions": sorted(f"{f}-Q{i + 1}" for f, i in drop),
                          "summary": summarize(G2, fids), "tests": compare(G2, fids)}
    types = sorted({q["type"] for it in its for q in it["questions"]})
    rep["by_type"] = {t: {c: {g: sum(G[(c, it["id"])][i] == g for it in its for i, q in enumerate(it["questions"])
                                     if q["type"] == t) for g in GRADES} for c in CONDS} for t in types}
    # exploratory, added after the pilot: a wrong answer with a date/time/number found in neither gold nor question
    rows, rep["wrong_kinds"] = [], {c: {"value_conflict": 0, "other": 0} for c in CONDS}
    for it in its:
        for c in CONDS:
            for i, q in enumerate(it["questions"]):
                if G[(c, it["id"])][i] == "틀림":
                    a = A[(c, it["id"])][i]
                    k = "value_conflict" if nums(a) - nums(gold(q)) - nums(q["q"]) else "other"
                    rep["wrong_kinds"][c][k] += 1
                    rows.append("\t".join([c, it["id"], f"Q{i + 1}", q["type"], k, S[(c, it["id"])][i],
                                           question(q), gold(q), a]))
    (OUT / "wrong.tsv").write_text("cond\tfid\tq\ttype\tkind\tgrader\tquestion\tgold\tresponse\n" + "\n".join(rows) + "\n")
    pairs = {"codex": ([], []), "auto": ([], [])}
    for it in its:
        for c in CONDS:
            hf = OUT / "grades" / "haiku" / c / f"{it['id']}.json"
            if hf.exists():
                h = json.loads(hf.read_text())["grades"]
                for i, x in enumerate(h):
                    pairs[S[(c, it["id"])][i]][0].append(G[(c, it["id"])][i])
                    pairs[S[(c, it["id"])][i]][1].append(x)
    rep["agreement"] = {k: {"n": len(a), "agree": round(sum(x == y for x, y in zip(a, b)) / len(a), 4) if a else None,
                            "kappa": round(kappa(a, b), 4) if a and kappa(a, b) is not None else None,
                            "confusion": {f"{x}->{y}": sum(p == x and q == y for p, q in zip(a, b))
                                          for x in GRADES for y in GRADES}}
                        for k, (a, b) in pairs.items()}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / "report.json").write_text(out)
    print(out)


def selftest():
    assert canon("11월 9일(월) 오전 9시") == canon("11/09(월) 09:00") == "11/9 9:00"
    assert canon("오후 4시 30분") == "16:30" and canon("18시") == "18:00" and canon("1시간") == "1시간"
    assert canon("11/12 시작") == "11/12 시작"
    assert canon("2만 원") == canon("20,000원") == "20000원"
    assert canon("13:00부터 17:00") == canon("13:00-17:00") == "13:00 ~ 17:00"
    assert all(eligible(g) for g in ("11/12(목) 16:00", "1회 28,000원", "12/24(목) 14:30~17:00", "15분 이내", "40kg"))
    assert not any(eligible(g) for g in ("3호선만", "공연당 2대", "복직 당일 17:00까지", "D14", "본사 2층 지원실"))
    q = {"q": "언제까지 신청해야 하는가?", "A": "11/12(목) 16:00", "B": "x", "C": "y", "D": "z", "answer": "A"}
    assert auto(q, "11월 12일 오후 4시까지") == "맞음"
    assert auto(q, "11/13 16:00") is None and auto(q, "11/12 16:00까지 포털에서 신청") is None
    assert auto(q, " 알 수 없음.") == "알 수 없음" and auto(q, '"알수 없음"') == "알 수 없음"
    q2 = {**q, "q": "답변 기한은?", "A": "15분 이내"}
    assert auto(q2, "15분 이내") == "맞음" and auto(q2, "15분 후") is None
    q3 = {**q, "q": "신청 마감은?"}
    assert auto(q3, "11/12(목) 16:00까지") == "맞음" and auto({**q3, "q": "배송 시각은?"}, "11/12 16:00까지") is None
    assert nums("11/12(목) 오후 4시, 3명") == {"11/12", "16:00", "3"}
    assert question({"q": "다음 중 반드시 해야 하는 일은?"}) == "반드시 해야 하는 일은?"
    assert rates(["맞음", "틀림", "알 수 없음", "맞음"]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert abs(kappa(list("aabb"), list("aaba")) - 0.5) < 1e-9 and kappa(list("aa"), list("aa")) is None
    G = {(c, f): ["맞음"] * 7 for c in CONDS for f in ("F01", "F02")}
    G[("base", "F01")] = ["틀림"] + ["맞음"] * 6
    t = compare(G, ["F01", "F02"])
    assert abs(t["acc full-base"]["diff"] - 1 / 14) < 1e-4 and abs(t["misread full-base"]["diff"] + 1 / 14) < 1e-4
    assert t["acc full-clarity"]["diff"] == 0 and abs(summarize(G, ["F01", "F02"])["base"]["acc"] - 13 / 14) < 1e-4
    assert len(sample_keys()) == 32 and sample_keys() == sample_keys()
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"pilot": lambda: cmd_run(PILOT_ITEMS), "main": cmd_run, "analyze": cmd_analyze,
     "selftest": selftest}.get(cmd, lambda: sys.exit(__doc__))()
