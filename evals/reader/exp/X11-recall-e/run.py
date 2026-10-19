#!/usr/bin/env python3
"""X11-recall-e: X1-ambiguous texts read without options, answers graded against per-question element rubrics.

Codex writes a rubric (required elements) for every question before any answer exists. Grok (primary) and Haiku
answer in free text. Codex (primary) and Haiku grade every answer. Design and pre-registered criteria: PREREG.md.
Usage: python3 run.py <rubric|read|grade|analyze|all|selftest> [--pilot]
Outputs are cached under out/; a call is skipped when its output file exists. X1's files are read by path, never
copied. Part-2 code of X9-recall-facts/run.py (read2, grade2, analyze2) was the starting point.
"""
import json
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
X1 = HERE.parent / "X1-ambiguous"
# forced, not setdefault: the third round runs X10, X11 and scenario round 19 on shared accounts (exp/BRIEF.md)
os.environ["KSTE_CODEX_HOME"] = str(Path.home() / ".cache/k-ste-eval/codex-home-X11-recall-e")
os.environ["KSTE_CODEX_AUTH"] = ("/Users/ford/Library/Application Support/orca/codex-accounts/"
                                 "e7b29eca-10d5-4ace-b7f2-cacabc9f7b3e/home/auth.json")
os.environ.update(KSTE_LIMIT_GROK="3", KSTE_LIMIT_CODEX="3", KSTE_LIMIT_CLAUDE="3")
sys.path.insert(0, str(HERE.parent.parent))
import reader as R  # noqa: E402

OUT = HERE / "out"
CONDS = R.CONDITIONS
WRITERS = R.WRITERS
PAIRS = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]
READERS = ["grok", "haiku"]  # primary first
GRADERS = ["codex", "haiku"]  # primary first
CATS = ["맞음", "빠뜨림", "오독", "알 수 없음"]
MARKS = ["있음", "없음", "어긋남"]
PILOT = ["M01", "M02"]  # 16 of 192 texts (8.3%)
RUBRIC_BATCH = 3  # memos per Codex rubric call: 8 calls
MAX_CHARS = 50
KAPPA_MIN = 0.6
E_NOTE = re.compile(r"\s*E\. 글만으로는 알 수 없다\s*$")

# ---------- prompts ----------

RUBRIC = """너는 독해 시험의 채점 기준을 만든다. 독자는 아래 메모로 AI가 쓴 업무 글을 읽고, 보기 없이 질문마다 50자 이내로 직접 답한다. 너는 독자의 응답을 보지 않는다. 채점자는 네 기준과 메모만 보고 응답을 채점한다. 문항마다 다음을 쓴다.

- id: 문항 id를 그대로 쓴다.
- answer: 정답의 요지 한 문장.
- elements: 정답의 필수 요소 1-4개. 요소 하나는 응답에 있는지 따로 판정할 수 있는 정보 하나다(예: "11/16(월)-11/18(수)", "매일 09:00-17:00"). 질문이 묻지 않는 부가 정보는 요소로 넣지 않는다.
- unspecified: 빈칸 문항에서 메모가 밝히지 않은 것이 무엇인지 한 문장으로 쓴다. 빈칸이 아닌 문항에는 빈 문자열을 쓴다.
- invented_examples: 빈칸 문항에서 메모에 없는 구체적인 답의 예 2-4개를 쓴다. 글쓴이가 빈칸을 그럴듯하게 메웠을 때 독자가 쓸 답이다. 빈칸이 아닌 문항에는 빈 목록을 쓴다.

빈칸 문항은 "빈칸:" 줄이 있는 문항이다. 정답이 "메모는 이것을 정하지 않았다"인 빈칸 문항의 elements에는 메모가 무엇을 정하지 않았는지를 요소 하나로 쓴다. 객관식 보기는 참고로만 준다. 독자는 보기를 보지 않는다.

{memos}

출력은 JSON 하나다. 형식: {{"items": [{{"id": "M01-Q1", "answer": "...", "elements": ["..."], "unspecified": "", "invented_examples": []}}]}}. 위의 문항 {n}개를 모두 쓴다."""

# X9's READ2 with "알 수 없음" replaced by "글에 없다" (PREREG step 2)
READ = """{persona}
다음 글을 읽고 질문에 답하라. 글에 쓰인 내용만 근거로 답한다. 보기는 없다. 질문마다 답을 50자 이내로 직접 쓴다. 글에 답이 없으면(글만으로 판단할 수 없으면) "글에 없다"라고 쓴다.

<글>
{text}
</글>

{questions}

출력은 JSON 한 줄이다. 예: {{"Q1": "답", "Q2": "글에 없다"}}"""

GRADE = """너는 독해 시험의 채점자다. 독자가 업무 글을 읽고 보기 없이 직접 쓴 답을 채점한다. 너는 그 글을 보지 않는다. 그 글은 아래 메모로 쓴 것이다. 메모에는 정보가 빠졌거나 흐린 항목(빈칸)이 있다. 메모, 문항, 채점 기준, 응답을 보고 응답마다 범주 하나와 요소별 판정을 쓴다.

범주:
- 맞음: 필수 요소가 모두 응답에 있고, 질문에 대한 답으로서 메모와 다른 내용이나 메모에 없는 구체적 내용이 없다. 표현, 어순, 날짜와 시각의 형식이 달라도 뜻이 같으면 요소가 있다고 본다. 질문이 묻지 않는 내용을 더했어도 그 내용이 메모와 맞으면 맞음이다.
- 빠뜨림: 필수 요소 일부가 응답에 없고, 메모와 다른 내용이나 메모에 없는 구체적 내용은 없다.
- 오독: 질문에 대한 답으로서 응답이 메모와 다른 내용(날짜, 시각, 사람, 수치, 장소, 대상, 조건, 의무 강도)이나 메모에 없는 구체적 내용을 쓴다. 메모에 있는 내용이라도 질문이 묻는 경우와 다른 경우(다른 대상, 기간, 조건)의 내용이면 오독이다. 필수 요소가 있어도 이런 내용이 함께 있으면 오독이다.
- 알 수 없음: 응답이 답을 하지 않고, 글에 없다거나 글만으로 알 수 없다고 한다.

메모의 날짜에는 연도가 없지만, 메모의 날짜는 모두 2026년이다. 응답이 날짜에 2026년을 붙였어도 메모와 다른 내용으로 보지 않는다.

빈칸 문항은 "빈칸:" 줄이 있는 문항이다. 응답이 "메모가 밝히지 않은 것"을 구체적으로 정하면(예: "메모에 없는 답의 예"와 같은 종류의 답), 그럴듯해도 오독이다. 응답이 정해지지 않았다고 쓰거나 메모의 흐린 표현을 같은 정도로 옮기면, 그 요소는 있다고 본다.

요소별 판정: 필수 요소마다 순서대로 "있음", "없음", "어긋남" 가운데 하나를 쓴다. 있음은 응답에 그 요소가 메모와 같은 뜻으로 있다는 뜻이다. 없음은 응답에 그 요소가 없다는 뜻이다. 어긋남은 응답이 그 요소를 메모와 다르게 썼다는 뜻이다. 빈칸 문항에서 메모가 밝히지 않은 것을 응답이 정했으면 그 요소는 어긋남이다. 범주가 알 수 없음이면 모든 요소는 없음이다.

<메모>
{memo}
</메모>

{block}

출력은 JSON 하나다. 응답 번호마다 범주와 요소별 판정을 쓴다. 예: {{"R1": {{"category": "맞음", "elements": ["있음", "있음"]}}, "R2": {{"category": "오독", "elements": ["어긋남"]}}}}. 응답 {n}개를 모두 쓴다."""


# ---------- shared ----------

def cached(f, fn):
    """JSON cache. fn validates; a parse error retries, a model CLI failure (RuntimeError) propagates."""
    if f.exists():
        return json.loads(f.read_text())
    for i in range(3):
        try:
            rec = fn()
            break
        except (ValueError, KeyError, TypeError) as e:
            R.log(f"retry parse {f.relative_to(OUT)} {i + 1}/3: {e}")
    else:
        raise RuntimeError(f"parse failed 3 times: {f}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


def run_jobs(name, fn, jobs_by_pool):
    """One thread pool per backend so a slow backend never starves the other; failures are logged, a rerun resumes."""
    def safe(job):
        try:
            fn(*job)
            return True
        except Exception as e:  # ponytail: log and move on; a rerun resumes from the cache
            R.log(f"FAIL {name} {job[:1] + tuple(x['id'] if isinstance(x, dict) else x for x in job[1:])}: {e}")
            return False

    with ThreadPoolExecutor(len(jobs_by_pool)) as ex:
        futs = {k: ex.submit(R.pmap, safe, jobs, 3) for k, jobs in jobs_by_pool.items()}
        done = {k: f.result() for k, f in futs.items()}
    R.log(f"{name} done " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in done.items()))


def memos(pilot=False):
    its = [json.loads(p.read_text()) for p in sorted((X1 / "out" / "kept").glob("M*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT]


def q2(q):
    """Question text without the note on option E that 81 X1 questions carry after the question mark (X9 q2)."""
    s = q["q"]
    return s[:s.index("?") + 1] if "E. 글만으로" in s else s


def gold2(q):
    if q["answer"] == "E":
        return "메모는 이것을 정하지 않았다"
    return E_NOTE.sub("", q[q["answer"]])


def gap_line(it, q):
    if q["gap"] < 0:
        return None
    g = it["gaps"][q["gap"]]
    return f"메모 항목 \"{it['facts'][g['fact']]}\" - {g['what']}"


def qid(it, i):
    return f"{it['id']}-Q{i + 1}"


def one_line(s):
    return " ".join(str(s).split())


# ---------- 1. rubric (Codex, before any answer) ----------

RUBRIC_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "answer", "elements", "unspecified", "invented_examples"],
        "properties": {"id": {"type": "string"}, "answer": {"type": "string"},
                       "elements": {"type": "array", "items": {"type": "string"}},
                       "unspecified": {"type": "string"},
                       "invented_examples": {"type": "array", "items": {"type": "string"}}}}}}}


def rubric_prompt(its):
    parts = []
    for it in its:
        qs = []
        for i, q in enumerate(it["questions"]):
            gl = gap_line(it, q)
            gold = gold2(q) + (f" ({it['gaps'][q['gap']]['what']})" if q["answer"] == "E" else "")
            opts = " / ".join(f"{k}. {one_line(E_NOTE.sub('', q[k]))}" for k in "ABCD")
            qs.append(f"문항 {qid(it, i)}\n질문: {q2(q)}\n" + (f"빈칸: {gl}\n" if gl else "")
                      + f"정답: {gold}\n객관식 보기(참고): {opts}")
        parts.append(f"<메모 {it['id']}>\n{R.memo(it)}\n</메모 {it['id']}>\n\n" + "\n\n".join(qs))
    return RUBRIC.format(memos="\n\n".join(parts), n=sum(len(it["questions"]) for it in its))


def parse_rubric(raw, its):
    """-> {qid: rubric}; raise unless every question has 1-4 elements and every gap question has both gap fields."""
    want = {qid(it, i): q for it in its for i, q in enumerate(it["questions"])}
    got = {str(x["id"]).strip(): x for x in R.first_json(raw)["items"]}
    if set(got) != set(want):
        raise ValueError(f"rubric ids differ: missing {sorted(set(want) - set(got))}, extra {sorted(set(got) - set(want))}")
    out = {}
    for k, q in want.items():
        x = got[k]
        els = [one_line(e) for e in x["elements"] if one_line(e)]
        if not 1 <= len(els) <= 4:
            raise ValueError(f"{k}: {len(els)} elements")
        r = {"answer": one_line(x["answer"]), "elements": els, "unspecified": "", "invented_examples": []}
        if q["gap"] >= 0:
            r["unspecified"] = one_line(x["unspecified"])
            r["invented_examples"] = [one_line(e) for e in x["invented_examples"] if one_line(e)]
            if not r["unspecified"] or not r["invented_examples"]:
                raise ValueError(f"{k}: gap question without unspecified or invented_examples")
        out[k] = r
    return out


def rubric_batches():
    its = memos()
    return [its[i:i + RUBRIC_BATCH] for i in range(0, len(its), RUBRIC_BATCH)]


def cmd_rubric(_pilot=False):
    """Always all 24 memos: rubrics are written before any reading, pilot included (PREREG)."""
    def one(k, its):
        p = rubric_prompt(its)
        cached(OUT / "rubric" / f"b{k}.json", lambda: (lambda raw: {
            "memos": [it["id"] for it in its], "raw": raw, "items": parse_rubric(raw, its)})(R.call("codex", p, RUBRIC_SCHEMA)))

    run_jobs("rubric", one, {"codex": list(enumerate(rubric_batches()))})


def rubrics():
    out = {}
    for f in sorted((OUT / "rubric").glob("b*.json")):
        out.update(json.loads(f.read_text())["items"])
    return out


# ---------- 2. reading (Grok primary, Haiku secondary) ----------

def ans_f(r, c, w, mid):
    return OUT / "answers" / r / c / w / f"{mid}.json"


def read_prompt(it, c, w, r):
    text = (X1 / "out" / "texts" / c / w / f"{it['id']}.md").read_text()
    return READ.format(persona=R.persona_for(f"X11/{c}/{w}/{r}/{it['id']}"), text=text,
                       questions="\n".join(f"Q{i + 1}. {q2(q)}" for i, q in enumerate(it["questions"])))


def parse_answers(raw, n):
    a = R.first_json(raw)
    return [one_line(a[f"Q{i + 1}"]) for i in range(n)]


def read_one(r, it, c, w):
    p = read_prompt(it, c, w, r)
    cached(ans_f(r, c, w, it["id"]), lambda: (lambda raw: {"raw": raw, "answers": parse_answers(
        raw, len(it["questions"]))})(R.call(r, p)))


def cmd_read(pilot):
    run_jobs("read", read_one, {r: [(r, it, c, w) for it in memos(pilot) for c in CONDS for w in WRITERS]
                                for r in READERS})


# ---------- 3. grading (Codex primary, Haiku secondary) ----------

def grade_f(g, r, mid):
    return OUT / "grades" / g / r / f"{mid}.json"


def grade_keys(mid, r, nq):
    """(cond, writer, question) in question order; (cond, writer) shuffled per question; no labels reach the grader."""
    keys = []
    for i in range(nq):
        cw = [(c, w) for c in CONDS for w in WRITERS]
        random.Random(f"X11-{mid}-{r}-{i}").shuffle(cw)
        keys += [(c, w, i) for c, w in cw]
    return keys


def grade_block(it, rub, ans, keys):
    """ans[(c, w)] = answers. One <문항> block per question with its rubric, then that question's answers."""
    blocks, k = [], 0
    for i, q in enumerate(it["questions"]):
        rb, gl = rub[qid(it, i)], gap_line(it, q)
        lines = [f"<문항 Q{i + 1}>", f"질문: {q2(q)}"] + ([f"빈칸: {gl}"] if gl else []) + [
            f"정답 요지: {rb['answer']}", "필수 요소:"] + [f"{j + 1}. {e}" for j, e in enumerate(rb["elements"])]
        if gl:
            lines += [f"메모가 밝히지 않은 것: {rb['unspecified']}", "메모에 없는 답의 예: " + " / ".join(rb["invented_examples"])]
        lines.append("응답:")
        for c, w, qi in keys:
            if qi == i:
                k += 1
                lines.append(f"R{k}: {one_line(ans[(c, w)][i])}")
        blocks.append("\n".join(lines + [f"</문항 Q{i + 1}>"]))
    return "\n\n".join(blocks)


def grade_prompt(it, rub, ans, keys):
    return GRADE.format(memo=R.memo(it), block=grade_block(it, rub, ans, keys), n=len(keys))


def grade_schema(n):
    one = {"type": "object", "additionalProperties": False, "required": ["category", "elements"],
           "properties": {"category": {"type": "string", "enum": CATS},
                          "elements": {"type": "array", "items": {"type": "string", "enum": MARKS}}}}
    keys = [f"R{k + 1}" for k in range(n)]
    return {"type": "object", "additionalProperties": False, "required": keys, "properties": {k: one for k in keys}}


def parse_grades(raw, nels):
    """nels[k] = element count of response k. Raise unless every response has a category and nels[k] marks."""
    norm = {x.replace(" ", ""): x for x in CATS + MARKS}
    g, out = R.first_json(raw), []
    for k, n in enumerate(nels):
        x = g[f"R{k + 1}"]
        cat = norm.get(str(x["category"]).replace(" ", ""))
        marks = [norm.get(str(m).replace(" ", "")) for m in x["elements"]]
        if cat not in CATS or len(marks) != n or any(m not in MARKS for m in marks):
            raise ValueError(f"bad grade R{k + 1}: {x}")
        out.append({"category": cat, "elements": marks})
    return out


def grade_one(g, r, it):
    mid, rub = it["id"], rubrics()
    keys = grade_keys(mid, r, len(it["questions"]))
    ans = {(c, w): json.loads(ans_f(r, c, w, mid).read_text())["answers"] for c in CONDS for w in WRITERS}
    p = grade_prompt(it, rub, ans, keys)
    nels = [len(rub[qid(it, i)]["elements"]) for _, _, i in keys]
    cached(grade_f(g, r, mid), lambda: (lambda raw: {"keys": [f"{c}/{w}/{i}" for c, w, i in keys], "raw": raw,
                                                     "grades": parse_grades(raw, nels)})(
        R.call(g, p, grade_schema(len(keys)))))


def cmd_grade(pilot):
    ready = [(r, it) for it in memos(pilot) for r in READERS
             if all(ans_f(r, c, w, it["id"]).exists() for c in CONDS for w in WRITERS)]
    run_jobs("grade", grade_one, {g: [(g, r, it) for r, it in ready] for g in GRADERS})


# ---------- 4. analysis ----------

def outcome(gold_letter, cat):
    """Free-response category -> outcome. 알 수 없음 is right when the gold is E, as choosing E is in X1."""
    if cat == "맞음" or (cat == "알 수 없음" and gold_letter == "E"):
        return "ok"
    return {"빠뜨림": "part", "오독": "mis", "알 수 없음": "ab"}[cat]


def mc_outcome(a, g):
    return "ok" if a == g else ("ab" if a == "E" else "mis")


def orates(outs):
    n = len(outs)
    if not n:
        return None
    return {"acc": round(outs.count("ok") / n, 4), "partial": round(outs.count("part") / n, 4),
            "misread": round(outs.count("mis") / n, 4), "abstain": round(outs.count("ab") / n, 4), "n": n}


def paired(px, py):
    ids = sorted(i for i in set(px) & set(py) if px[i] is not None and py[i] is not None)
    if not ids:
        return None
    m, lo, hi = R.boot([px[i] - py[i] for i in ids])
    return {"memos": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "ci_excludes_0": lo > 0 or hi < 0}


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in set(a) | set(b))
    return None if pe == 1 else (po - pe) / (1 - pe)


def agreement(pairs_by_unit, cats):
    """pairs_by_unit: {memo: [(codex, haiku)]}. Kappa with a memo-level bootstrap CI (X9's agreement)."""
    flat = [p for v in pairs_by_unit.values() for p in v]
    if not flat:
        return None
    a, b = [x for x, _ in flat], [y for _, y in flat]
    units, rnd, ks = sorted(pairs_by_unit), random.Random(7), []
    for _ in range(10000):
        s = [p for u in (rnd.choice(units) for _ in units) for p in pairs_by_unit[u]]
        k = kappa([x for x, _ in s], [y for _, y in s])
        if k is not None:
            ks.append(k)
    ks.sort()
    k = kappa(a, b)
    return {"n": len(flat), "units": len(units), "agree": round(sum(x == y for x, y in flat) / len(flat), 4),
            "kappa": None if k is None else round(k, 4),
            "kappa_ci95": [round(ks[int(0.025 * len(ks))], 4), round(ks[int(0.975 * len(ks))], 4)] if ks else None,
            "confusion": {f"{x}->{y}": sum(p == x and q == y for p, q in flat) for x in cats for y in cats}}


def binary(pairs_by_unit):
    """Misread yes/no per grader: crosstab, kappa, positive agreement 2a / (2a + b + c)."""
    ag = agreement(pairs_by_unit, [True, False])
    if ag is None:
        return None
    flat = [p for v in pairs_by_unit.values() for p in v]
    a, b = sum(x and y for x, y in flat), sum(x and not y for x, y in flat)
    c, d = sum(y and not x for x, y in flat), sum(not x and not y for x, y in flat)
    ag.pop("confusion")
    return {**ag, "both": a, "codex_only": b, "haiku_only": c, "neither": d,
            "positive_agreement": round(2 * a / (2 * a + b + c), 4) if a + b + c else None}


def load_grades(g, r, mid):
    d = json.loads(grade_f(g, r, mid).read_text())
    out = {}
    for k, x in zip(d["keys"], d["grades"]):
        c, w, i = k.split("/")
        out[(c, w, int(i))] = x
    return out


def cmd_analyze(pilot=False):
    its = [it for it in memos(pilot) if all(grade_f(g, r, it["id"]).exists() for g in GRADERS for r in READERS)]
    missing = sorted(set(it["id"] for it in memos(pilot)) - set(it["id"] for it in its))
    if missing:
        R.log(f"analyze: memos without all grades left out: {missing}")
    mids, byid = [it["id"] for it in its], {it["id"]: it for it in its}
    gap = {(it["id"], i) for it in its for i, q in enumerate(it["questions"]) if q["gap"] >= 0}
    kind = {(it["id"], i): it["gaps"][q["gap"]]["kind"] for it in its for i, q in enumerate(it["questions"])
            if q["gap"] >= 0}
    sub = {"all": lambda k: True, "gap": lambda k: (k[3], k[4]) in gap, "nongap": lambda k: (k[3], k[4]) not in gap}

    A, GR, MC = {}, {g: {} for g in GRADERS}, {}  # keys (reader, cond, writer, memo, question)
    for it in its:
        m, qs = it["id"], it["questions"]
        for r in READERS:
            gr = {g: load_grades(g, r, m) for g in GRADERS}
            for c in CONDS:
                for w in WRITERS:
                    ans = json.loads(ans_f(r, c, w, m).read_text())["answers"]
                    mc = json.loads((X1 / "out" / "answers" / c / w / r / f"{m}.json").read_text())
                    assert mc["gold"] == [q["answer"] for q in qs], f"X1 question order differs {c}/{w}/{r}/{m}"
                    for i in range(len(qs)):
                        k = (r, c, w, m, i)
                        A[k], MC[k] = ans[i], mc_outcome(mc["answers"][i], mc["gold"][i])
                        for g in GRADERS:
                            GR[g][k] = gr[g][(c, w, i)]
    gold_letter = {k: byid[k[3]]["questions"][k[4]]["answer"] for k in A}
    FR = {g: {k: outcome(gold_letter[k], GR[g][k]["category"]) for k in A} for g in GRADERS}
    CONS = {k: "mis" if FR["codex"][k] == FR["haiku"][k] == "mis" else "other" for k in A}
    O = {"free": FR["codex"], "free_haiku_grader": FR["haiku"], "conservative": CONS, "mc": MC}

    def pool(src, r, c, s, ws=WRITERS, ms=None):
        return orates([o for k, o in O[src].items() if k[0] == r and k[1] == c and k[2] in ws
                       and (ms is None or k[3] in ms) and sub[s](k)])

    def per_memo(src, r, c, s, metric):
        return {m: (pool(src, r, c, s, ms={m}) or {}).get(metric) for m in mids}

    summary = {}
    for r in READERS:
        for c in CONDS:
            summary.setdefault(r, {})[c] = {
                "free": {s: pool("free", r, c, s) for s in sub},
                "mc": {s: pool("mc", r, c, s) for s in sub},
                "free_haiku_grader_gap": pool("free_haiku_grader", r, c, "gap"),
                "conservative_gap_misread": (pool("conservative", r, c, "gap") or {}).get("misread"),
                "by_writer_gap": {w: {"free": pool("free", r, c, "gap", [w]), "mc": pool("mc", r, c, "gap", [w])}
                                  for w in WRITERS},
                "over_50_chars": sum(len(a) > MAX_CHARS for k, a in A.items() if k[0] == r and k[1] == c)}
    if len(its) == 24:  # X1 reproduction check: the MC side must match X1's own report
        x1 = json.loads((X1 / "out" / "report.json").read_text())["summary"]
        for r in READERS:
            for c in CONDS:
                for s in sub:
                    for k in ("acc", "misread", "abstain", "n"):
                        assert summary[r][c]["mc"][s][k] == x1[c][r][s][k], f"X1 reproduction failed {r} {c} {s} {k}"

    tests = {}
    plan = [("free", "gap", "misread"), ("free", "nongap", "acc"), ("free", "gap", "acc"),
            ("conservative", "gap", "misread"), ("free_haiku_grader", "gap", "misread"), ("mc", "gap", "misread")]
    for r in READERS:
        for src, s, metric in plan:
            for x, y in PAIRS:
                tests[f"{src} {r} {s} {metric} {x}-{y}"] = paired(per_memo(src, r, x, s, metric),
                                                                  per_memo(src, r, y, s, metric))
    h2 = {}
    for r in READERS:
        for c in CONDS:
            h2[f"{r} gap misread free-mc {c}"] = paired(per_memo("free", r, c, "gap", "misread"),
                                                        per_memo("mc", r, c, "gap", "misread"))
        for x, y in PAIRS:
            d = {}
            for src in ("free", "mc"):
                px, py = per_memo(src, r, x, "gap", "misread"), per_memo(src, r, y, "gap", "misread")
                d[src] = {m: px[m] - py[m] for m in mids if px[m] is not None and py[m] is not None}
            h2[f"{r} gap misread diff-in-diff (free {x}-{y}) - (mc {x}-{y})"] = paired(d["free"], d["mc"])

    reliability = {}
    for r in READERS:
        for s in sub:
            cat_pairs, mis_pairs = {}, {}
            for k in A:
                if k[0] == r and sub[s](k):
                    a, b = GR["codex"][k]["category"], GR["haiku"][k]["category"]
                    cat_pairs.setdefault(k[3], []).append((a, b))
                    mis_pairs.setdefault(k[3], []).append((a == "오독", b == "오독"))
            reliability[f"{r} {s}"] = {"category": agreement(cat_pairs, CATS), "misread": binary(mis_pairs)}
        el = {}
        for k in A:
            if k[0] == r:
                el.setdefault(k[3], []).extend(zip(GR["codex"][k]["elements"], GR["haiku"][k]["elements"]))
        reliability[f"{r} elements"] = agreement(el, MARKS)
    gate = reliability["grok gap"]["misread"]["kappa"]
    consistency = {g: dict(sorted(Counter(f"{x['category']} | 어긋남 {'있음' if '어긋남' in x['elements'] else '없음'}"
                                          f" | 없음 {'있음' if '없음' in x['elements'] else '없음'}"
                                          for x in GR[g].values()).items())) for g in GRADERS}

    by_kind = {}
    for k, o in O["free"].items():
        if k[0] == "grok" and (k[3], k[4]) in gap:
            d = by_kind.setdefault(kind[(k[3], k[4])], {}).setdefault(k[1], {"free": [], "mc": []})
            d["free"].append(o)
            d["mc"].append(MC[k])
    by_kind = {kd: {c: {f: orates(v[f]) for f in v} for c, v in sorted(d.items())} for kd, d in sorted(by_kind.items())}
    cross = {c: dict(sorted(Counter(f"mc {MC[k]} -> free {FR['codex'][k]}" for k in A
                                    if k[0] == "grok" and k[1] == c and (k[3], k[4]) in gap).items())) for c in CONDS}

    # exploratory, added after the main run (PREREG change log): weak_obligation drove most of the free-vs-MC gap,
    # and Codex counted "권장" there as a misread; so the gap metric without it, and grader disagreement by kind
    sub["gap_no_weak"] = lambda k: (k[3], k[4]) in gap and kind[(k[3], k[4])] != "weak_obligation"
    no_weak = {"summary": {c: {src: pool(src, "grok", c, "gap_no_weak") for src in ("free", "mc")} for c in CONDS},
               "tests": {f"{src} {x}-{y}": paired(per_memo(src, "grok", x, "gap_no_weak", "misread"),
                                                   per_memo(src, "grok", y, "gap_no_weak", "misread"))
                         for src in ("free", "mc") for x, y in PAIRS},
               "free-mc": {c: paired(per_memo("free", "grok", c, "gap_no_weak", "misread"),
                                     per_memo("mc", "grok", c, "gap_no_weak", "misread")) for c in CONDS}}
    dis_kind = {}
    for k in A:
        if k[0] == "grok" and (k[3], k[4]) in gap:
            a, b = GR["codex"][k]["category"] == "오독", GR["haiku"][k]["category"] == "오독"
            d = dis_kind.setdefault(kind[(k[3], k[4])], Counter())
            d["both" if a and b else "codex_only" if a else "haiku_only" if b else "neither"] += 1
    exploratory = {"grok_gap_without_weak_obligation": no_weak,
                   "grok_gap_misread_agreement_by_kind": {kd: dict(v) for kd, v in sorted(dis_kind.items())}}

    b = summary["grok"]["base"]["free"]["all"]
    h1 = tests["free grok gap misread full-base"]
    rep = {"memos": len(its), "memos_missing": missing,
           "ceiling_broken": bool(b and (b["acc"] <= 0.95 or b["misread"] >= 0.03)),
           "h1": {**(h1 or {}), "supported": bool(h1 and h1["ci95"][1] < 0)},
           "grading_reliability_gate": {"kappa": gate, "threshold": KAPPA_MIN,
                                        "low": gate is None or gate < KAPPA_MIN},
           "summary": summary, "tests": tests, "h2": h2, "reliability": reliability,
           "grader_consistency": consistency, "grok_gap_by_kind": by_kind, "grok_gap_mc_vs_free": cross,
           "exploratory": exploratory}

    rows, drows = [], []
    for k in sorted(A):
        r, c, w, m, i = k
        q, cx, hk = byid[m]["questions"][i], GR["codex"][k]["category"], GR["haiku"][k]["category"]
        cols = [r, c, w, m, f"Q{i + 1}", kind.get((m, i), "-"), q["answer"], cx, hk, MC[k], q2(q), gold2(q), A[k]]
        if r == "grok" and (m, i) in gap and FR["codex"][k] != "ok":
            rows.append("\t".join(cols))
        if (cx == "오독") != (hk == "오독"):
            drows.append("\t".join(cols))
    head = "reader\tcond\twriter\tmemo\tq\tkind\tgold_letter\tcodex\thaiku\tmc\tquestion\tgold\tresponse\n"
    sfx = "-pilot" if pilot else ""
    (OUT / f"gap-nonok{sfx}.tsv").write_text(head + "\n".join(rows) + "\n")
    (OUT / f"misread-disagree{sfx}.tsv").write_text(head + "\n".join(drows) + "\n")
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / f"report{sfx}.json").write_text(out)
    print(out)


# ---------- selftest ----------

def selftest():
    # question cleanup and gold (X9 q2, gold2)
    for s in ("누가 맡는가? 모든 문항의 A-D 다음에는 공통으로 ‘E. 글만으로는 알 수 없다’가 붙는다.",
              "누가 맡는가?\nE. 글만으로는 알 수 없다", "누가 맡는가? (공통 추가 보기: E. 글만으로는 알 수 없다)",
              "누가 맡는가?"):
        assert q2({"q": s}) == "누가 맡는가?"
    assert gold2({"answer": "B", "B": "총무팀이 한다.\nE. 글만으로는 알 수 없다"}) == "총무팀이 한다."
    assert gold2({"answer": "E"}) == "메모는 이것을 정하지 않았다"
    it = {"id": "M01", "request": "공지를 써 줘.", "facts": ["가", "11/20(금) 반납"],
          "gaps": [{"kind": "deadline_vs_date", "fact": 1, "what": "모호하다."}],
          "questions": [{"q": "11/20은? E. 글만으로는 알 수 없다", "A": "a\nE. 글만으로는 알 수 없다", "B": "b", "C": "c",
                         "D": "d", "answer": "E", "gap": 0},
                        {"q": "가는?", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "B", "gap": -1}]}
    assert gap_line(it, it["questions"][0]) == '메모 항목 "11/20(금) 반납" - 모호하다.'
    assert gap_line(it, it["questions"][1]) is None
    # rubric prompt and parsing
    p = rubric_prompt([it])
    assert "문항 M01-Q1\n질문: 11/20은?\n빈칸: 메모 항목" in p and "정답: 메모는 이것을 정하지 않았다 (모호하다.)" in p
    assert "A. a / B. b" in p and "E. 글만으로" not in p.split("<메모 M01>")[1] and "문항 2개를" in p
    good = {"items": [{"id": "M01-Q1", "answer": "정하지 않았다", "elements": ["기한인지 지정일인지 정하지 않음"],
                       "unspecified": "기한인지 지정일인지", "invented_examples": ["11/20까지", "11/20 당일"]},
                      {"id": "M01-Q2", "answer": "b", "elements": ["b", " "], "unspecified": "x", "invented_examples": ["y"]}]}
    rb = parse_rubric(json.dumps(good, ensure_ascii=False), [it])
    assert rb["M01-Q2"] == {"answer": "b", "elements": ["b"], "unspecified": "", "invented_examples": []}
    assert rb["M01-Q1"]["invented_examples"] == ["11/20까지", "11/20 당일"]
    for bad in ({"items": good["items"][:1]},
                {"items": [{**good["items"][0], "invented_examples": []}, good["items"][1]]},
                {"items": [good["items"][0], {**good["items"][1], "elements": list("abcde")}]}):
        try:
            parse_rubric(json.dumps(bad, ensure_ascii=False), [it])
            raise AssertionError(f"parse_rubric accepted {bad}")
        except ValueError:
            pass
    # reading
    assert parse_answers('x {"Q1": " 글에\\n없다 ", "Q2": "b"}', 2) == ["글에 없다", "b"]
    try:
        parse_answers('{"Q1": "a"}', 2)
        raise AssertionError("parse_answers accepted a missing answer")
    except KeyError:
        pass
    # grading batch: deterministic, complete, question order, no labels, one rubric block per question
    keys = grade_keys("M01", "grok", 2)
    assert keys == grade_keys("M01", "grok", 2) and keys != grade_keys("M01", "haiku", 2)
    assert sorted(keys) == sorted((c, w, i) for c in CONDS for w in WRITERS for i in range(2))
    assert [i for _, _, i in keys] == [0] * 8 + [1] * 8
    ans = {(c, w): [f"답-{c}-{w}-1", f"답-{c}-{w}-2"] for c in CONDS for w in WRITERS}
    gp = grade_prompt(it, rb, ans, keys)
    c0, w0, _ = keys[0]
    assert f"R1: 답-{c0}-{w0}-1" in gp and "R16: " in gp and "R17" not in gp and "응답 16개를" in gp
    assert gp.count("<문항 Q") == 2 and gp.count("메모가 밝히지 않은 것:") == 1 and "빈칸: 메모 항목" in gp
    stripped = re.sub(r"답-\w+-\w+-\d", "", gp)
    assert not any(x in stripped for x in CONDS + WRITERS + ["grok"])
    # grade parsing
    raw = 'x {"R1": {"category": "알수 없음", "elements": ["없음"]}, "R2": {"category": "오독", "elements": ["어긋남", "있음"]}}'
    assert parse_grades(raw, [1, 2]) == [{"category": "알 수 없음", "elements": ["없음"]},
                                         {"category": "오독", "elements": ["어긋남", "있음"]}]
    for bad, n in (('{"R1": {"category": "부분", "elements": ["있음"]}}', [1]),
                   ('{"R1": {"category": "맞음", "elements": ["있음"]}}', [2]),
                   ('{"R1": {"category": "맞음", "elements": ["반쯤"]}}', [1]),
                   ('{"R2": {"category": "맞음", "elements": []}}', [0])):
        try:
            parse_grades(bad, n)
            raise AssertionError("parse_grades accepted " + bad)
        except (KeyError, ValueError):
            pass
    assert grade_schema(2)["required"] == ["R1", "R2"]
    # scoring
    assert [outcome("E", c) for c in CATS] == ["ok", "part", "mis", "ok"]
    assert [outcome("B", c) for c in CATS] == ["ok", "part", "mis", "ab"]
    assert [mc_outcome(a, "E") for a in "EA"] == ["ok", "mis"]
    assert [mc_outcome(a, "B") for a in "BEC"] == ["ok", "ab", "mis"]
    assert orates(["ok", "mis", "ab", "part"]) == {"acc": 0.25, "partial": 0.25, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert orates([]) is None
    assert paired({"M01": 0.5, "M02": None}, {"M01": 0.25, "M02": 0.0}) == {
        "memos": 1, "diff": 0.25, "ci95": [0.25, 0.25], "ci_excludes_0": True}
    # agreement
    assert abs(kappa(list("aabb"), list("aaba")) - 0.5) < 1e-9 and kappa(list("aa"), list("aa")) is None
    ag = agreement({"u1": [("맞음", "맞음"), ("오독", "오독")], "u2": [("맞음", "오독"), ("맞음", "맞음")]}, CATS)
    assert ag["n"] == 4 and ag["agree"] == 0.75 and ag["kappa"] == 0.5 and ag["confusion"]["맞음->오독"] == 1
    assert ag["kappa_ci95"][0] <= ag["kappa"] <= ag["kappa_ci95"][1]
    bn = binary({"u1": [(True, True), (True, False)], "u2": [(False, True), (False, False), (False, False)]})
    assert (bn["both"], bn["codex_only"], bn["haiku_only"], bn["neither"]) == (1, 1, 1, 2)
    assert bn["positive_agreement"] == 0.5 and "confusion" not in bn
    # every template formats without a stray brace
    assert "{" not in READ.format(persona="p", text="t", questions="q").replace('{"Q1"', "")
    assert GRADE.format(memo="m", block="b", n=1).count("<메모>") == 1
    assert "메모의 날짜는 모두 2026년이다" in GRADE  # pilot fix (PREREG change log)
    print("selftest ok")


STEPS = {"rubric": cmd_rubric, "read": cmd_read, "grade": cmd_grade, "analyze": cmd_analyze}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    pilot = "--pilot" in sys.argv
    if cmd == "selftest":
        selftest()
    elif cmd == "all":
        for step in STEPS.values():
            step(pilot)
    elif cmd in STEPS:
        STEPS[cmd](pilot)
    else:
        sys.exit(__doc__)
