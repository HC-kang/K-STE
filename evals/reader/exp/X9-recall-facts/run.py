#!/usr/bin/env python3
"""X9-recall-facts: free responses graded by a model that sees the facts (part 1) or the memo (part 2).

Part 1 re-grades X4-recall's 1,120 Grok answers. Part 2 (only when part 1's kappa >= 0.6) has Grok answer
X1-ambiguous's questions without options. Design and pre-registered criteria: PREREG.md.
Usage: python3 run.py <grade1|analyze1|read2|grade2|analyze2|selftest> [--pilot]
Outputs are cached under out/; a call is skipped when its output file exists. Other experiments' files are read
by path, never copied.
"""
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
X4 = HERE.parent / "X4-recall"
X1 = HERE.parent / "X1-ambiguous"
# forced, not setdefault: the second round runs three experiments on shared accounts (exp/BRIEF.md)
os.environ["KSTE_CODEX_HOME"] = str(Path.home() / ".cache/k-ste-eval/codex-home-X9-recall-facts")
os.environ["KSTE_CODEX_AUTH"] = ("/Users/ford/Library/Application Support/orca/codex-accounts/"
                                 "e7b29eca-10d5-4ace-b7f2-cacabc9f7b3e/home/auth.json")
os.environ.update(KSTE_LIMIT_GROK="4", KSTE_LIMIT_CODEX="3", KSTE_LIMIT_CLAUDE="4")
sys.path.insert(0, str(HERE.parent.parent))
import reader as R  # noqa: E402

OUT = HERE / "out"
CONDS = R.CONDITIONS
PAIRS = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]
GRADES = ["맞음", "틀림", "알 수 없음"]
GRADERS = ["codex", "haiku"]  # primary first
PILOT1 = 4  # F01-F04: 112 of 1,120 answers (10%)
PILOT2 = ["M01", "M02"]  # 16 of 192 texts (8.3%)
MAX_CHARS = 50
KAPPA_MIN = 0.6

RULES = """- 맞음: 응답이 질문에 대한 답으로서 정답과 뜻이 같다. 표현, 어순, 날짜와 시각의 형식이 달라도 뜻이 같으면 맞음이다. 질문이 묻는 핵심이 정답과 같고 정답과 어긋나는 내용이 없으면, 정답의 부가 정보가 빠져도 맞음이다. 응답이 정답에 없는 내용을 더했어도, 더한 내용이 {gwa} 맞으면 맞음이다. {src}에 따라 이 질문에 맞는 답이 둘 이상이면, 그중 하나를 쓴 응답도 맞음이다.
- 틀림: 질문에 대한 답으로서 응답이 {gwa} 어긋나는 날짜, 시각, 사람, 수치, 장소, 대상, 조건, 의무 강도(해야 한다, 해도 된다, 하지 않아도 된다)를 쓴다. {src}에 있는 내용이라도 질문이 묻는 경우와 다른 경우(다른 대상, 기간, 조건)의 내용이면 틀림이다. 또는 질문이 묻는 핵심이 빠졌다. 후보를 여러 개 쓰고 그중 {gwa} 어긋나는 것이 있으면 틀림이다.
- 알 수 없음: 응답이 답을 하지 않고, 글만으로는 알 수 없다거나 글에 없다고 한다."""

OUTPUT = """출력은 JSON 한 줄이다. 응답 번호마다 "맞음", "틀림", "알 수 없음" 가운데 하나를 쓴다. 예: {"R1": "맞음", "R2": "틀림"}"""

GRADE1 = """너는 독해 시험의 채점자다. 독자가 업무 글을 읽고 보기 없이 직접 쓴 답을 채점한다. 너는 그 글을 보지 않는다. 그 글은 아래 사실 목록을 담아 쓴 것이다. 사실 목록, 질문, 정답, 응답을 보고 판정한다.

""" + RULES.format(src="사실 목록", gwa="사실 목록과") + """

<사실 목록>
{facts}
</사실 목록>

{block}

""" + OUTPUT.replace("{", "{{").replace("}", "}}")

GRADE2 = """너는 독해 시험의 채점자다. 독자가 업무 글을 읽고 보기 없이 직접 쓴 답을 채점한다. 너는 그 글을 보지 않는다. 그 글은 아래 메모로 쓴 것이다. 메모에는 정보가 빠졌거나 흐린 항목(빈칸)이 있다. 메모, 질문, 정답, 응답을 보고 판정한다.

""" + RULES.format(src="메모", gwa="메모와") + """
- 빈칸 문항: "빈칸:" 줄이 있는 문항이다. 응답이 메모에 없는 구체적인 내용(그날 하는 일인지 그때까지 끝낼 일인지, 행위자, 두 대상 가운데 하나, 처리한 대상과 결과, 의무 강도)을 쓰면, 그 내용이 그럴듯해도 틀림이다. 응답이 메모가 정하지 않았다고 쓰거나 메모의 흐린 표현을 같은 정도로 옮기면 맞음이다.

<메모>
{memo}
</메모>

{block}

""" + OUTPUT.replace("{", "{{").replace("}", "}}")

# X4's READ; only the length limit changed from 30 to 50 characters (PREREG part 2, X4 limitation 2)
READ2 = """{persona}
다음 글을 읽고 질문에 답하라. 글에 쓰인 내용만 근거로 답한다. 보기는 없다. 질문마다 답을 50자 이내로 직접 쓴다. 글만으로 판단할 수 없으면 "알 수 없음"이라고 쓴다.

<글>
{text}
</글>

{questions}

출력은 JSON 한 줄이다. 예: {{"Q1": "답", "Q2": "알 수 없음"}}"""


# ---------- machine grading, copied from X4-recall/run.py (analyze1 checks it reproduces X4) ----------

def question(q):
    return re.sub(r"^다음 중\s*", "", q["q"])  # "다음 중" points at options that are no longer shown


def gold(q):
    return q[q["answer"]]


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


def auto(q, resp, g=None):
    """Machine grade, or None when the model grader must decide. A mismatch is never auto-wrong.
    g overrides the gold text (part 2: X1 options carry an E note; E golds have no option)."""
    if re.sub(r"[\s.\"'“”]", "", resp).startswith("알수없"):
        return "알 수 없음"
    drop = bool(re.search(r"까지|마감|기한", q["q"]))  # deadline question: "까지" in an answer is implied
    g = gold(q) if g is None else g
    if eligible(g) and canon(resp, drop).replace(" ", "") == canon(g, drop).replace(" ", ""):
        return "맞음"
    return None


# ---------- shared ----------

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


def grade_schema(n):
    keys = [f"R{k + 1}" for k in range(n)]
    return {"type": "object", "additionalProperties": False, "required": keys,
            "properties": {k: {"type": "string", "enum": GRADES} for k in keys}}


def parse_grades(raw, n):
    norm = {g.replace(" ", ""): g for g in GRADES}
    g = R.first_json(raw)
    out = [norm.get(str(g[f"R{k + 1}"]).replace(" ", "")) for k in range(n)]
    if None in out:
        raise ValueError(f"bad grade in {raw[:200]}")
    return out


def model_grade(who, prompt, keys, f):
    def fn():
        if not keys:
            return {"keys": [], "grades": []}
        raw = R.call(who, prompt, grade_schema(len(keys)))
        return {"keys": keys, "raw": raw, "grades": parse_grades(raw, len(keys))}
    return cached(f, fn)


def shuffled_conds(seed):
    cs = list(CONDS)
    random.Random(seed).shuffle(cs)
    return cs


def item_block(rows):
    """rows: [(response, question, gold, gap line or None)] -> R1.. blocks, X4's layout plus an optional gap line."""
    return "\n\n".join(f"R{k + 1}\n" + (f"빈칸: {gap}\n" if gap else "") + f"질문: {q}\n정답: {g}\n응답: {a}"
                       for k, (a, q, g, gap) in enumerate(rows))


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(k) / n) * (b.count(k) / n) for k in set(a) | set(b))
    return None if pe == 1 else (po - pe) / (1 - pe)


def agreement(pairs_by_unit):
    """pairs_by_unit: {unit: [(primary, second)]}. Kappa with a unit-level bootstrap CI, agreement, PABAK."""
    flat = [p for v in pairs_by_unit.values() for p in v]
    if not flat:
        return None
    a, b = [x for x, _ in flat], [y for _, y in flat]
    po = sum(x == y for x, y in flat) / len(flat)
    units, rnd, ks = sorted(pairs_by_unit), random.Random(7), []
    for _ in range(10000):
        s = [p for u in (rnd.choice(units) for _ in units) for p in pairs_by_unit[u]]
        k = kappa([x for x, _ in s], [y for _, y in s])
        if k is not None:
            ks.append(k)
    ks.sort()
    k = kappa(a, b)
    return {"n": len(flat), "units": len(units), "agree": round(po, 4), "pabak": round((3 * po - 1) / 2, 4),
            "kappa": None if k is None else round(k, 4),
            "kappa_ci95": [round(ks[int(0.025 * len(ks))], 4), round(ks[int(0.975 * len(ks))], 4)] if ks else None,
            "confusion": {f"{x}->{y}": sum(p == x and q == y for p, q in flat) for x in GRADES for y in GRADES}}


# ---------- part 1: re-grade X4 with the fact list ----------

LETTER = {"맞음": "A", "틀림": "B", "알 수 없음": "E"}


def rates(gs):
    """X4's rates: acc = correct, misread = wrong answer (not 알 수 없음), abstain = 알 수 없음."""
    return R.rates([{"answers": [LETTER[g] for g in gs], "gold": ["A"] * len(gs)}])


def compare(G, fids):
    """G[(cond, fid)] = grades. Paired differences x - y per fact list, bootstrapped (X4's compare)."""
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


def x4_answers(c, fid):
    return json.loads((X4 / "out" / "answers" / c / f"{fid}.json").read_text())["answers"]


def batch1(it):
    """(cond, question index) in question order; condition order shuffled per question; no condition labels."""
    return [(c, i) for i in range(len(it["questions"])) for c in shuffled_conds(f"X9-{it['id']}-{i}")]


def prompt1(it, ans, keys):
    qs = it["questions"]
    facts = "\n".join(f"{k + 1}. {f}" for k, f in enumerate(it["facts"]))
    return GRADE1.format(facts=facts, block=item_block([(ans[c][i], question(qs[i]), gold(qs[i]), None)
                                                         for c, i in keys]))


def jobs1(it, who):
    ans = {c: x4_answers(c, it["id"]) for c in CONDS}
    keys = [(c, i) for c, i in batch1(it) if who != "codex" or auto(it["questions"][i], ans[c][i]) is None]
    return ans, keys


def cmd_grade1(pilot):
    its = R.items()[:PILOT1] if pilot else R.items()

    def one(job):
        it, who = job
        try:
            ans, keys = jobs1(it, who)
            model_grade(who, prompt1(it, ans, keys), [f"{c}/{i}" for c, i in keys], OUT / "p1" / who / f"{it['id']}.json")
            return True
        except Exception as e:  # ponytail: log and move on; a rerun resumes from the cache
            R.log(f"FAIL p1 {who} {it['id']}: {e}")
            return False

    ok = R.pmap(one, [(it, w) for it in its for w in GRADERS], workers=7)
    R.log(f"p1 batches done {sum(ok)}/{len(ok)}")


def load_grades(f):
    d = json.loads(f.read_text())
    return {tuple((k.split("/")[0], int(k.split("/")[1]))): g for k, g in zip(d["keys"], d["grades"])}


def x4_final(it, c, ans):
    """X4's final grade: machine grade wins, else X4's Codex grade (X4-recall/run.py final)."""
    cx = json.loads((X4 / "out" / "grades" / "codex" / c / f"{it['id']}.json").read_text())
    g = [auto(q, a) for q, a in zip(it["questions"], ans)]
    for i, x in zip(cx["idx"], cx["grades"]):
        if g[i] is None:
            g[i] = x
    assert None not in g, f"ungraded X4 answer {c}/{it['id']}"
    return g


def cmd_analyze1(_pilot=False):
    all_its = R.items()
    # X4 reproduction check on all 40 fact lists before anything else
    G4 = {(c, it["id"]): x4_final(it, c, x4_answers(c, it["id"])) for it in all_its for c in CONDS}
    x4rep = json.loads((X4 / "out" / "report.json").read_text())["summary"]
    s4 = summarize(G4, [it["id"] for it in all_its])
    for c in CONDS:
        for k in ("acc", "misread", "abstain", "n"):
            assert s4[c][k] == x4rep[c][k], f"X4 reproduction failed: {c} {k} {s4[c][k]} != {x4rep[c][k]}"

    its = [it for it in all_its if all((OUT / "p1" / w / f"{it['id']}.json").exists() for w in GRADERS)]
    fids = [it["id"] for it in its]
    G, S, H, A = {}, {}, {}, {}
    for it in its:
        f = it["id"]
        cx, hk = load_grades(OUT / "p1" / "codex" / f"{f}.json"), load_grades(OUT / "p1" / "haiku" / f"{f}.json")
        for c in CONDS:
            A[(c, f)] = x4_answers(c, f)
            mg = [auto(q, a) for q, a in zip(it["questions"], A[(c, f)])]
            G[(c, f)] = [m or cx[(c, i)] for i, m in enumerate(mg)]
            S[(c, f)] = ["auto" if m else "codex" for m in mg]
            H[(c, f)] = [hk[(c, i)] for i in range(len(mg))]

    # exploratory, added after the main grading: codex_x4_sample = the texts X4's kappa (0.54) was computed on
    x4s = {(p.parent.name, p.stem) for p in (X4 / "out" / "grades" / "haiku").glob("*/F*.json")}
    by_src = {"codex": {}, "auto": {}, "all": {}, "codex_x4_sample": {}}
    for (c, f), gs in G.items():
        for i, g in enumerate(gs):
            by_src[S[(c, f)][i]].setdefault(f, []).append((g, H[(c, f)][i]))
            by_src["all"].setdefault(f, []).append((g, H[(c, f)][i]))
            if S[(c, f)][i] == "codex" and (c, f) in x4s:
                by_src["codex_x4_sample"].setdefault(f, []).append((g, H[(c, f)][i]))
    agree = {k: agreement(v) for k, v in by_src.items()}
    k_main = agree["codex"]["kappa"] if agree["codex"] else None

    keys = [(c, f, i) for f in fids for c in CONDS for i in range(len(G[(c, f)]))]
    vs_x4 = Counter(f"{G4[(c, f)][i]}->{G[(c, f)][i]}" for c, f, i in keys)
    audit = [ln.split("\t") for ln in (X4 / "out" / "audit.tsv").read_text().splitlines()[1:] if ln.strip()]
    audit = {(c, f, int(q[1:]) - 1): cls for c, f, q, cls, _ in audit}
    audit_x = {who: {cls: dict(Counter((G if who == "codex" else H)[(c, f)][i]
                                       for (c, f, i), k in audit.items() if k == cls and f in fids))
                     for cls in "ABC"} for who in GRADERS}
    audit_match = {who: sum(((G if who == "codex" else H)[(c, f)][i] == {"B": "맞음", "C": "틀림"}[cls])
                            for (c, f, i), cls in audit.items() if cls in "BC" and f in fids) for who in GRADERS}

    rep = {"items": len(its), "answers": len(keys), "x4_reproduced": True,
           "agreement": agree, "kappa_codex_graded": k_main,
           "part2": bool(k_main is not None and k_main >= KAPPA_MIN and len(its) == len(all_its)),
           "vs_x4": {"changed": sum(v for k, v in vs_x4.items() if k.split("->")[0] != k.split("->")[1]),
                     "crosstab": dict(sorted(vs_x4.items()))},
           "audit": {"by_class": audit_x, "B_or_C_matched": audit_match,
                     "joint_codex_haiku": {cls: dict(Counter(f"{G[(c, f)][i]}/{H[(c, f)][i]}" for (c, f, i), k
                                                             in audit.items() if k == cls and f in fids))
                                           for cls in "ABC"},
                     "B_or_C_total": sum(cls in "BC" for (c, f, i), cls in audit.items() if f in fids),
                     "B_correct_codex": audit_x["codex"]["B"].get("맞음", 0),
                     "B_total": sum(cls == "B" for (c, f, i), cls in audit.items() if f in fids)},
           "x4_old": {"summary": summarize(G4, fids), "tests": compare(G4, fids)},
           "summary": summarize(G, fids), "tests": compare(G, fids)}
    for c in CONDS:
        rep["summary"][c]["graded_by"] = dict(Counter(s for f in fids for s in S[(c, f)]))
    b = rep["summary"]["base"]
    rep["ceiling_broken"] = b["acc"] <= 0.95 or b["misread"] >= 0.03
    drop = {(f, i) for f in fids for i in range(len(G[("base", f)])) if all(G[(c, f)][i] != "맞음" for c in CONDS)}
    G2 = {k: [g for i, g in enumerate(v) if (k[1], i) not in drop] for k, v in G.items()}
    rep["sensitivity"] = {"dropped_questions": sorted(f"{f}-Q{i + 1}" for f, i in drop),
                          "summary": summarize(G2, fids), "tests": compare(G2, fids)}
    sh = summarize(H, fids)
    rep["haiku_only"] = {"summary": sh, "ceiling_broken": sh["base"]["acc"] <= 0.95 or sh["base"]["misread"] >= 0.03,
                         "tests": compare(H, fids)}
    types = sorted({q["type"] for it in its for q in it["questions"]})
    rep["by_type"] = {t: {c: dict(Counter(G[(c, it["id"])][i] for it in its for i, q in enumerate(it["questions"])
                                          if q["type"] == t)) for c in CONDS} for t in types}

    qs = {it["id"]: it["questions"] for it in its}
    rows = []
    for c, f, i in keys:
        x4, cx, hk = G4[(c, f)][i], G[(c, f)][i], H[(c, f)][i]
        if S[(c, f)][i] == "codex" and (cx != hk or cx != x4):
            q = qs[f][i]
            rows.append("\t".join([c, f, f"Q{i + 1}", q["type"], x4, cx, hk, audit.get((c, f, i), ""),
                                   question(q), gold(q), A[(c, f)][i]]))
    (OUT / "p1-disagree.tsv").write_text("cond\tfid\tq\ttype\tx4\tcodex\thaiku\taudit\tquestion\tgold\tresponse\n"
                                         + "\n".join(rows) + "\n")
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / ("p1-report.json" if len(its) == len(all_its) else "p1-report-pilot.json")).write_text(out)
    print(out)


# ---------- part 2: X1 texts, free response, graded against the memo ----------

def x1_memos(pilot=False):
    its = [json.loads(p.read_text()) for p in sorted((X1 / "out" / "kept").glob("M*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT2]


def q2(q):
    """Question text without the note on option E that 81 X1 questions carry after the question mark."""
    s = q["q"]
    return s[:s.index("?") + 1] if "E. 글만으로는" in s else s


def gold2(q):
    if q["answer"] == "E":
        return "메모는 이것을 정하지 않았다"
    return re.sub(r"\s*E\. 글만으로는 알 수 없다\s*$", "", q[q["answer"]])


def gap_line(it, q):
    if q["gap"] < 0:
        return None
    g = it["gaps"][q["gap"]]
    return f"메모 항목 \"{it['facts'][g['fact']]}\" - {g['what']}"


def read2(it, c, w):
    qs = it["questions"]
    text = (X1 / "out" / "texts" / c / w / f"{it['id']}.md").read_text()
    p = READ2.format(persona=R.persona_for(f"X9/{c}/{w}/{it['id']}"), text=text,
                     questions="\n".join(f"Q{i + 1}. {q2(q)}" for i, q in enumerate(qs)))

    def fn():
        raw = R.call("grok", p)
        a = R.first_json(raw)
        return {"raw": raw, "answers": [str(a[f"Q{i + 1}"]).strip() for i in range(len(qs))]}
    return cached(OUT / "p2" / "answers" / c / w / f"{it['id']}.json", fn)


def cmd_read2(pilot):
    def one(job):
        try:
            read2(*job)
            return True
        except Exception as e:  # ponytail: log and move on; a rerun resumes from the cache
            R.log(f"FAIL read2 {job[1]}/{job[2]}/{job[0]['id']}: {e}")
            return False

    jobs = [(it, c, w) for it in x1_memos(pilot) for c in CONDS for w in R.WRITERS]
    ok = R.pmap(one, jobs, workers=int(os.environ["KSTE_LIMIT_GROK"]))
    R.log(f"read2 done {sum(ok)}/{len(ok)}")


def answers2(it, w):
    return {c: json.loads((OUT / "p2" / "answers" / c / w / f"{it['id']}.json").read_text())["answers"] for c in CONDS}


def jobs2(it, w, who):
    ans, qs = answers2(it, w), it["questions"]
    keys = [(c, i) for i in range(len(qs)) for c in shuffled_conds(f"X9-2-{it['id']}-{w}-{i}")
            if who != "codex" or auto(qs[i], ans[c][i], gold2(qs[i])) is None]
    return ans, keys


def prompt2(it, ans, keys):
    qs = it["questions"]
    return GRADE2.format(memo=R.memo(it), block=item_block([(ans[c][i], q2(qs[i]), gold2(qs[i]), gap_line(it, qs[i]))
                                                            for c, i in keys]))


def cmd_grade2(pilot):
    def one(job):
        it, w, who = job
        try:
            ans, keys = jobs2(it, w, who)
            model_grade(who, prompt2(it, ans, keys), [f"{c}/{i}" for c, i in keys],
                        OUT / "p2" / who / w / f"{it['id']}.json")
            return True
        except Exception as e:  # ponytail: log and move on; a rerun resumes from the cache
            R.log(f"FAIL grade2 {who} {w}/{it['id']}: {e}")
            return False

    jobs = [(it, w, who) for it in x1_memos(pilot) for w in R.WRITERS for who in GRADERS
            if all((OUT / "p2" / "answers" / c / w / f"{it['id']}.json").exists() for c in CONDS)]
    ok = R.pmap(one, jobs, workers=7)
    R.log(f"grade2 batches done {sum(ok)}/{len(ok)}")


def outcome(gold_letter, g):
    """Free-response grade -> X1's scoring: a correct 알 수 없음 (gold E) is right, like choosing E."""
    if g == "맞음" or (g == "알 수 없음" and gold_letter == "E"):
        return "ok"
    return "mis" if g == "틀림" else "ab"


def mc_outcome(a, g):
    return "ok" if a == g else ("ab" if a == "E" else "mis")


def orates(outs):
    n = len(outs)
    return {"acc": round(outs.count("ok") / n, 4), "misread": round(outs.count("mis") / n, 4),
            "abstain": round(outs.count("ab") / n, 4), "n": n} if n else None


def cmd_analyze2(pilot=False):
    its = [it for it in x1_memos(pilot)
           if all((OUT / "p2" / who / w / f"{it['id']}.json").exists() for who in GRADERS for w in R.WRITERS)]
    mids = [it["id"] for it in its]
    FR, MC, HK, G, rows, pairs_cx = {}, {}, {}, {}, [], {}
    for it in its:
        m, qs = it["id"], it["questions"]
        for w in R.WRITERS:
            ans = answers2(it, w)
            cx, hk = load_grades(OUT / "p2" / "codex" / w / f"{m}.json"), load_grades(OUT / "p2" / "haiku" / w / f"{m}.json")
            for c in CONDS:
                mc = json.loads((X1 / "out" / "answers" / c / w / "grok" / f"{m}.json").read_text())
                assert mc["gold"] == [q["answer"] for q in qs], f"X1 question order differs {c}/{w}/{m}"
                for i, q in enumerate(qs):
                    a = ans[c][i]
                    mg = auto(q, a, gold2(q))
                    g = mg or cx[(c, i)]
                    key = (c, w, m, i)
                    G[key], HK[key] = g, hk[(c, i)]
                    FR[key], MC[key] = outcome(q["answer"], g), mc_outcome(mc["answers"][i], mc["gold"][i])
                    if not mg:
                        pairs_cx.setdefault(m, []).append((g, hk[(c, i)]))
                    if q["gap"] >= 0 and FR[key] != "ok":
                        rows.append("\t".join([c, w, m, f"Q{i + 1}", it["gaps"][q["gap"]]["kind"], q["answer"],
                                               FR[key], g, HK[key], mc["answers"][i], q2(q), gold2(q), a]))
    gap = {(m, i) for it in its for i, q in enumerate(it["questions"]) if q["gap"] >= 0 for m in [it["id"]]}
    sub = {"all": lambda m, i: True, "gap": lambda m, i: (m, i) in gap, "nongap": lambda m, i: (m, i) not in gap}

    def pool(O, c, s, ws=R.WRITERS, ms=None):
        return orates([o for (cc, w, m, i), o in O.items() if cc == c and w in ws and (ms is None or m in ms)
                       and sub[s](m, i)])

    def per_memo(O, c, s, metric):
        return {m: pool(O, c, s, ms={m})[metric] for m in mids}

    summary = {c: {fmt: {s: pool(O, c, s) for s in sub} for fmt, O in (("free", FR), ("mc", MC))} for c in CONDS}
    for c in CONDS:
        summary[c]["free_by_writer_gap"] = {w: pool(FR, c, "gap", [w]) for w in R.WRITERS}
        summary[c]["over_50_chars"] = sum(len(json.loads((OUT / "p2" / "answers" / c / w / f"{m}.json").read_text())
                                              ["answers"][i]) > MAX_CHARS for (cc, w, m, i) in FR if cc == c)
        summary[c]["graded_by_codex"] = sum(1 for (cc, w, m, i) in FR if cc == c) - sum(
            auto(q, a, gold2(q)) is not None for it in its for w in R.WRITERS
            for q, a in zip(it["questions"], answers2(it, w)[c]))
    if not pilot:  # X1 reproduction check: the MC side must match X1's own report
        x1 = json.loads((X1 / "out" / "report.json").read_text())["summary"]
        for c in CONDS:
            for s in sub:
                for k in ("acc", "misread", "abstain", "n"):
                    assert summary[c]["mc"][s][k] == x1[c]["grok"][s][k], f"X1 reproduction failed {c} {s} {k}"

    tests, did = {}, {}
    for x, y in PAIRS:
        for O, fmt in ((FR, "free"), (MC, "mc")):
            for s, metric in (("gap", "misread"), ("nongap", "acc"), ("gap", "acc")):
                px, py = per_memo(O, x, s, metric), per_memo(O, y, s, metric)
                mean, lo, hi = R.boot([px[m] - py[m] for m in mids])
                tests[f"{fmt} {s} {metric} {x}-{y}"] = {"memos": len(mids), "diff": round(mean, 4),
                                                        "ci95": [round(lo, 4), round(hi, 4)]}
        fx, fy = per_memo(FR, x, "gap", "misread"), per_memo(FR, y, "gap", "misread")
        mx, my = per_memo(MC, x, "gap", "misread"), per_memo(MC, y, "gap", "misread")
        mean, lo, hi = R.boot([(fx[m] - fy[m]) - (mx[m] - my[m]) for m in mids])
        did[f"gap misread {x}-{y}"] = {"memos": len(mids), "diff": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)]}

    kinds = {}
    for (c, w, m, i), o in FR.items():
        if (m, i) in gap:
            q = next(it for it in its if it["id"] == m)["questions"][i]
            kinds.setdefault(next(it for it in its if it["id"] == m)["gaps"][q["gap"]]["kind"], {}).setdefault(
                c, {"free": [], "mc": []})
            kinds[next(it for it in its if it["id"] == m)["gaps"][q["gap"]]["kind"]][c]["free"].append(o)
            kinds[next(it for it in its if it["id"] == m)["gaps"][q["gap"]]["kind"]][c]["mc"].append(MC[(c, w, m, i)])
    by_kind = {k: {c: {f: orates(v[f]) for f in v} for c, v in d.items()} for k, d in sorted(kinds.items())}
    cross = {c: dict(Counter(f"mc {MC[k]} -> free {FR[k]}" for k in FR if k[0] == c and (k[2], k[3]) in gap))
             for c in CONDS}

    b = summary["base"]["free"]["all"]
    rep = {"memos": len(its), "summary": summary, "ceiling_broken": b["acc"] <= 0.95 or b["misread"] >= 0.03,
           "tests": tests, "format_diff_in_diff": did, "gap_by_kind": by_kind, "gap_mc_vs_free": cross,
           "agreement": agreement(pairs_cx)}
    (OUT / "p2-gap-nonok.tsv").write_text(
        "cond\twriter\tmemo\tq\tkind\tgold_letter\tfree\tcodex_or_auto\thaiku\tmc_answer\tquestion\tgold\tresponse\n"
        + "\n".join(rows) + "\n")
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / ("p2-report-pilot.json" if pilot else "p2-report.json")).write_text(out)
    print(out)


def selftest():
    # machine grading, same asserts as X4-recall/run.py
    assert canon("11월 9일(월) 오전 9시") == canon("11/09(월) 09:00") == "11/9 9:00"
    assert canon("오후 4시 30분") == "16:30" and canon("18시") == "18:00" and canon("1시간") == "1시간"
    assert canon("2만 원") == canon("20,000원") == "20000원"
    assert canon("13:00부터 17:00") == canon("13:00-17:00") == "13:00 ~ 17:00"
    assert all(eligible(g) for g in ("11/12(목) 16:00", "1회 28,000원", "12/24(목) 14:30~17:00", "15분 이내", "40kg"))
    assert not any(eligible(g) for g in ("3호선만", "공연당 2대", "복직 당일 17:00까지", "D14", "본사 2층 지원실"))
    q = {"q": "언제까지 신청해야 하는가?", "A": "11/12(목) 16:00", "B": "x", "C": "y", "D": "z", "answer": "A"}
    assert auto(q, "11월 12일 오후 4시까지") == "맞음"
    assert auto(q, "11/13 16:00") is None and auto(q, "11/12 16:00까지 포털에서 신청") is None
    assert auto(q, " 알 수 없음.") == "알 수 없음" and auto(q, '"알수 없음"') == "알 수 없음"
    assert auto({**q, "q": "신청 마감은?"}, "11/12(목) 16:00까지") == "맞음"
    assert auto(q, "11/12 16:00", gold2({"answer": "E"})) is None  # an E gold never matches a date
    # part 1 batching and prompt
    it = {"id": "F01", "facts": ["가", "나"], "questions": [q, {**q, "q": "다음 중 맞는 것은?"}]}
    b = batch1(it)
    assert b == batch1(it) and sorted(b) == sorted((c, i) for c in CONDS for i in range(2))
    assert [i for _, i in b] == [0] * 4 + [1] * 4
    ans = {c: ["11/12 16:00", f"응답-{c}"] for c in CONDS}
    p = prompt1(it, ans, [("full", 1), ("base", 0)])
    assert "1. 가\n2. 나" in p and "R1\n질문: 맞는 것은?\n정답: 11/12(목) 16:00\n응답: 응답-full" in p
    assert "R2\n질문: 언제까지" in p and "full" not in p.replace("응답-full", "") and '{"R1": "맞음"' in p
    assert parse_grades('x {"R1": "알수 없음", "R2": "맞음"}', 2) == ["알 수 없음", "맞음"]
    for bad in ('{"R1": "부분"}', '{"R2": "맞음"}'):
        try:
            parse_grades(bad, 1)
            raise AssertionError("parse_grades accepted " + bad)
        except (KeyError, ValueError):
            pass
    # X4 scoring and comparisons
    assert rates(["맞음", "틀림", "알 수 없음", "맞음"]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    G = {(c, f): ["맞음"] * 7 for c in CONDS for f in ("F01", "F02")}
    G[("base", "F01")] = ["틀림"] + ["맞음"] * 6
    t = compare(G, ["F01", "F02"])
    assert abs(t["acc full-base"]["diff"] - 1 / 14) < 1e-4 and abs(t["misread full-base"]["diff"] + 1 / 14) < 1e-4
    # agreement
    assert abs(kappa(list("aabb"), list("aaba")) - 0.5) < 1e-9 and kappa(list("aa"), list("aa")) is None
    ag = agreement({"u1": [("맞음", "맞음"), ("틀림", "틀림")], "u2": [("맞음", "틀림"), ("맞음", "맞음")]})
    assert ag["n"] == 4 and ag["agree"] == 0.75 and ag["pabak"] == 0.625 and ag["kappa"] == 0.5
    assert ag["kappa_ci95"][0] <= ag["kappa"] <= ag["kappa_ci95"][1] and ag["confusion"]["맞음->틀림"] == 1
    # part 2 question cleanup, gold, gap line, scoring
    for s in ("누가 맡는가? 모든 문항의 A-D 다음에는 공통으로 ‘E. 글만으로는 알 수 없다’가 붙는다.",
              "누가 맡는가?\nE. 글만으로는 알 수 없다", "누가 맡는가? (공통 추가 보기: E. 글만으로는 알 수 없다)",
              "누가 맡는가? 공통 추가 보기: E. 글만으로는 알 수 없다", "누가 맡는가?"):
        assert q2({"q": s}) == "누가 맡는가?"
    assert gold2({"answer": "B", "B": "총무팀이 한다.\nE. 글만으로는 알 수 없다"}) == "총무팀이 한다."
    m = {"facts": ["a", "11/20(금) 반납"], "gaps": [{"kind": "deadline_vs_date", "fact": 1, "what": "모호하다."}]}
    assert gap_line(m, {"gap": 0}) == '메모 항목 "11/20(금) 반납" - 모호하다.' and gap_line(m, {"gap": -1}) is None
    blk = item_block([("응답", "질문?", "정답", "빈칸 설명"), ("응답2", "질문2?", "정답2", None)])
    assert blk == "R1\n빈칸: 빈칸 설명\n질문: 질문?\n정답: 정답\n응답: 응답\n\nR2\n질문: 질문2?\n정답: 정답2\n응답: 응답2"
    assert [outcome("E", g) for g in GRADES] == ["ok", "mis", "ok"]
    assert [outcome("B", g) for g in GRADES] == ["ok", "mis", "ab"]
    assert [mc_outcome(a, "E") for a in "EA"] == ["ok", "mis"] and [mc_outcome(a, "B") for a in "BEC"] == ["ok", "ab", "mis"]
    assert orates(["ok", "mis", "ab", "ok"]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4} and orates([]) is None
    assert "{" not in GRADE1.replace("{facts}", "").replace("{block}", "").replace("{{", "").replace('{"R1"', "")
    assert GRADE2.format(memo="M", block="B").count("빈칸:") == 1 and "메모과" not in GRADE2
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    pilot = "--pilot" in sys.argv
    steps = {"grade1": cmd_grade1, "analyze1": cmd_analyze1, "read2": cmd_read2, "grade2": cmd_grade2,
             "analyze2": cmd_analyze2}
    if cmd == "selftest":
        selftest()
    elif cmd in steps:
        steps[cmd](pilot)
    else:
        sys.exit(__doc__)
