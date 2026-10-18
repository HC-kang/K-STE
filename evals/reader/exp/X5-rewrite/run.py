#!/usr/bin/env python3
"""X5-rewrite: phase 2 (rewrite) redesign. Codex and Haiku select questions on the original; Grok evaluates.

Design: PREREG.md. Usage: python3 run.py <samplesize|passages|items|write|read|classify|analyze|selftest> [--n N]
--n limits every stage to the first N candidate passages (pilot). Outputs are cached under out/;
a call is skipped when its output file exists, so a rerun resumes.
"""
import argparse
import hashlib
import json
import os
import random
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import reader as R  # noqa: E402

OUT = HERE / "out"
K8S = Path(os.environ.get("X5_K8S", "/private/tmp/claude-501/-Users-ford-projects-personal-K-STE/"
                                    "3e5b9cac-c5a0-4db3-acce-43b1016927b2/scratchpad/k8s/content/ko"))
N_TARGET = 100  # PREREG.md, sample size
POOL = 115      # candidates sent to question generation first; +5 at a time until N_TARGET qualify
BATCH = 5       # passages per Codex generation / open-book call
CLOSED_BATCH = 10
MIN_Q = 4
MARGIN = -0.03
FLAG = re.compile(r"확인이?\s*필요")  # pilot: a rewrite wrote "확인이 필요한 부분"
CONDS = R.CONDITIONS
ALL = ["original"] + CONDS
CAUSES = ["silent_change", "flag_E", "other"]


def jdump(f, obj):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


# ---------- sample size ----------

def sample_size(sd_rewrite, p_orig, k=6, margin=0.03, alpha=0.025, power=0.80):
    """Passages needed so the 95% CI lower bound clears -margin when the true difference is 0."""
    z = statistics.NormalDist().inv_cdf
    sd = (sd_rewrite ** 2 + p_orig * (1 - p_orig) / k) ** 0.5
    return sd, ((z(1 - alpha) + z(power)) * sd / margin) ** 2


def cmd_samplesize(a):
    rw = R.OUT / "rewrite" / "answers"
    acc = lambda r: sum(x == g for x, g in zip(r["answers"], r["gold"])) / len(r["gold"])
    orig = R.load(rw, "original", "grok")
    errs = n = 0
    out = {}
    for c in CONDS:
        recs = R.load(rw, c, "grok")
        d = [acc(recs[i]) - acc(orig[i]) for i in sorted(recs)]
        errs += sum(len(r["gold"]) - round(acc(r) * len(r["gold"])) for r in recs.values())
        n += sum(len(r["gold"]) for r in recs.values())
        out[c] = {"passages": len(d), "mean": round(statistics.mean(d), 4), "sd": round(statistics.stdev(d), 4)}
    p = errs / n
    worst = max(v["sd"] for v in out.values())
    sd, need = sample_size(worst, p)
    res = {"phase2_grok": out, "pooled_rewrite_error": round(p, 4), "orig_acc_phase2": round(
        statistics.mean(acc(r) for r in orig.values()), 4), "sd_diff_worst_with_orig": round(sd, 4),
        "passages_needed": round(need, 1)}
    jdump(OUT / "samplesize.json", res)
    print(json.dumps(res, ensure_ascii=False, indent=1))


# ---------- passages ----------

GLOSS = re.compile(r'\{\{<\s*glossary_tooltip\b[^>]*?\btext="([^"]*)"[^>]*?>\}\}')
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
BAD = re.compile(r"```|\{\{|\{%|<[a-zA-Z/!]|^\s*\||!\[", re.M)


def sections(md):
    md = re.sub(r"\A---\n.*?\n---\n", "", md, flags=re.S)
    parts = re.split(r"^(#{2,4} .*)$", md, flags=re.M)
    return [(parts[i].lstrip("#").strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def clean(body):
    t = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return LINK.sub(r"\1", GLOSS.sub(r"\1", t)).strip()


def picks(md):
    """Sections that read as Korean prose: 400-900 chars, no code, shortcodes, HTML, or tables."""
    out = []
    for h, body in sections(md):
        t = clean(body)
        if 400 <= len(t) <= 900 and not BAD.search(t) and R.hangul_ratio(t) >= 0.5 and len(re.findall(r"다\.", t)) >= 3:
            out.append((h, t))
    return out


def cmd_passages(a):
    used = {json.loads(f.read_text())["source"] for f in (R.OUT / "rewrite" / "src").glob("K*.json")}
    tiers = [[], []]  # one section per file first; a file's second section only after every file's first
    for f in sorted((K8S / "docs").rglob("*.md")):
        src = "kubernetes/website content/ko/" + str(f.relative_to(K8S))
        if src in used:
            continue
        for tier, (h, t) in zip(tiers, picks(f.read_text())):
            tier.append({"source": src, "license": "CC BY 4.0", "heading": h, "text": t})
    for i, tier in enumerate(tiers):
        random.Random(5 + i).shuffle(tier)
    cands = tiers[0] + tiers[1]
    for i, c in enumerate(cands):
        jdump(OUT / "src" / f"P{i + 1:03d}.json", {"id": f"P{i + 1:03d}", **c})
    R.log(f"candidates: {len(tiers[0])} + {len(tiers[1])} (excluded phase 2 sources: {len(used)})")


def candidates():
    return [json.loads(f.read_text()) for f in sorted((OUT / "src").glob("P*.json"))]


# ---------- questions and selection ----------

QG_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["passages"],
             "properties": {"passages": {"type": "array", "items": {
                 "type": "object", "additionalProperties": False, "required": ["id", "questions"],
                 "properties": {"id": {"type": "string"}, "questions": R.RQ_SCHEMA["properties"]["questions"]}}}}}

_head = R.RQ_PROMPT.split("\n\n<글>")[0]
assert "아래 글을 읽은 독자가" in _head and "{" not in _head
QG_PROMPT = (_head.replace("아래 글을 읽은 독자가", "아래 글 각각에 대해, 그 글을 읽은 독자가")
             + "\n- 글마다 id를 그대로 쓴다. 문항은 그 글만 근거로 만들고, 다른 글의 내용을 섞지 않는다.\n\n{texts}")

SEL_PROMPT = """다음 글들을 읽고 각 글의 질문에 답하라. 각 질문은 그 질문이 붙은 글에 쓰인 내용만 근거로 고른다. 글만으로 판단할 수 없으면 E를 고른다.

{blocks}

출력은 JSON이다. 글 id마다 답을 쓴다. 예: {{"P001": {{"Q1": "A", "Q2": "E"}}}}"""


def tagged(ps):
    return "\n\n".join(f'<글 id="{p["id"]}">\n{p["text"]}\n</글>' for p in ps)


def sel_schema(groups):
    return {"type": "object", "additionalProperties": False, "required": [g for g, _ in groups],
            "properties": {g: R.answer_schema(n) for g, n in groups}}


def sel_blocks(ps, qs_by, open_book):
    out = []
    for p in ps:
        body = f'<글 id="{p["id"]}">\n{p["text"]}\n</글>\n\n' if open_book else f'<글 id="{p["id"]}">\n(글 없음)\n</글>\n\n'
        out.append(body + f"{p['id']}의 질문:\n" + R.qblock(qs_by[p["id"]]))
    return "\n\n".join(out)


def codex_answers(f, ps, qs_by, open_book):
    if not f.exists():
        prompt = SEL_PROMPT.format(blocks=sel_blocks(ps, qs_by, open_book))
        raw = R.call("codex", prompt, sel_schema([(p["id"], len(qs_by[p["id"]])) for p in ps]))
        jdump(f, json.loads(raw))
    ans = json.loads(f.read_text())
    return {p["id"]: [ans[p["id"]].get(f"Q{i + 1}", "E") for i in range(len(qs_by[p["id"]]))] for p in ps}


def keep(qs, opened, closed):
    """Phase 2 rule: every selector right with the text, and not every selector right without it."""
    return [i for i, q in enumerate(qs) if all(opened[w][i] == q["answer"] for w in opened)
            and not all(closed[w][i] == q["answer"] for w in closed)]


def gen_questions(ps):
    qs_by = {}
    for b in chunks(ps, BATCH):
        f = OUT / "qgen" / f"{b[0]['id']}-{b[-1]['id']}.json"
        if not f.exists():
            raw = R.call("codex", QG_PROMPT.format(texts=tagged(b)), QG_SCHEMA)
            jdump(f, json.loads(raw))
        got = {x["id"]: x["questions"] for x in json.loads(f.read_text())["passages"]}
        for p in b:
            qs_by[p["id"]] = got.get(p["id"], [])
    return qs_by


def select(ps):
    """Generate questions for ps and run both selectors; return qualified items in candidate order."""
    gb = {}
    for g in R.pmap(gen_questions, chunks(ps, BATCH), workers=2):
        gb.update(g)
    ps = [p for p in ps if gb[p["id"]]]

    def open_codex(b):
        return codex_answers(OUT / "select" / "codex-open" / f"{b[0]['id']}-{b[-1]['id']}.json", b, gb, True)

    def closed_codex(b):
        return codex_answers(OUT / "select" / "codex-closed" / f"{b[0]['id']}-{b[-1]['id']}.json", b, gb, False)

    def haiku(p):
        f = OUT / "select" / "haiku" / f"{p['id']}.json"
        if not f.exists():
            qs = gb[p["id"]]
            jdump(f, {"open": R.ask("haiku", p["text"], qs), "closed": R.ask("haiku", "(글 없음)", qs)})
        return json.loads(f.read_text())

    co, cc = {}, {}
    with ThreadPoolExecutor(3) as ex:  # Codex and Haiku have separate limits, so run them side by side
        fo = ex.submit(R.pmap, open_codex, chunks(ps, BATCH), 2)
        fc = ex.submit(R.pmap, closed_codex, chunks(ps, CLOSED_BATCH), 2)
        hk = dict(zip([p["id"] for p in ps], R.pmap(haiku, ps, workers=3)))
        for d in fo.result():
            co.update(d)
        for d in fc.result():
            cc.update(d)
    out, log = [], {}
    for p in ps:
        qs = gb[p["id"]]
        kept = keep(qs, {"codex": co[p["id"]], "haiku": hk[p["id"]]["open"]},
                    {"codex": cc[p["id"]], "haiku": hk[p["id"]]["closed"]})
        log[p["id"]] = {"generated": len(qs), "kept": len(kept)}
        if len(kept) >= MIN_Q:
            out.append({**p, "questions": [R.shuffle_options(qs[i], f"{p['id']}-{i}") for i in kept]})
    return out, log


def cmd_items(a):
    cands = candidates()
    if a.n:
        sel, log = select(cands[:a.n])
    else:
        k = POOL
        while True:
            sel, log = select(cands[:k])
            if len(sel) >= N_TARGET or k >= len(cands):
                break
            k += BATCH
        sel = sel[:N_TARGET]
    for it in sel:
        jdump(OUT / "items" / f"{it['id']}.json", it)
    jdump(OUT / ("selection-pilot.json" if a.n else "selection.json"),
          {"qualified": [it["id"] for it in sel], "per_passage": log})
    R.log(f"qualified {len(sel)} of {len(log)} generated passages")


def items(a):
    f = OUT / ("selection-pilot.json" if a.n else "selection.json")
    ids = json.loads(f.read_text())["qualified"]
    return [json.loads((OUT / "items" / f"{i}.json").read_text()) for i in ids]


# ---------- rewrite and read ----------

def text(it, c):
    return it["text"] if c == "original" else (OUT / "texts" / c / f"{it['id']}.md").read_text()


def cmd_write(a):
    def one(job):
        it, c = job
        f = OUT / "texts" / c / f"{it['id']}.md"
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(R.call("sonnet", R.REWRITE_REQ + it["text"], system=R.system_for(c)))
    sp = (R.REPO / "prompts/system-prompt.md").read_bytes()
    jdump(OUT / "writer-prompt.json", {"prompts/system-prompt.md sha256": hashlib.sha256(sp).hexdigest()})
    R.pmap(one, [(it, c) for it in items(a) for c in CONDS], workers=3)


def cmd_read(a):
    # only passages whose four rewrites exist, so read can run while write is still going
    its = [it for it in items(a) if all((OUT / "texts" / c / f"{it['id']}.md").exists() for c in CONDS)]
    jobs = [(it, text(it, c), "grok", OUT / "answers" / c / "grok" / f"{it['id']}.json") for it in its for c in ALL]
    R.pmap(lambda j: R.read_one(*j), jobs, workers=2)
    R.log(f"answers: {len(jobs)} ({len(its)} of {len(items(a))} passages ready)")


# ---------- cause classification ----------

CLS_PROMPT = """너는 글 다듬기 평가에서 독자 오답의 원인을 분류한다. 사례마다 원문, 원문을 다듬은 글, 그리고 독자가 다듬은 글만 읽고 틀린 객관식 문항이 있다. 정답은 원문을 기준으로 정했다. 보기 E는 "글만으로는 알 수 없다"이다.

사례마다 cause를 아래 셋 가운데 하나로 고른다. 위에서부터 차례로 따져서 처음 맞는 것을 고른다.
- flag_E: 독자가 E를 골랐고, 다듬은 글이 이 문항의 답과 관련된 곳에 "확인 필요"처럼 원문의 뜻이 분명하지 않다는 표시를 달았다.
- silent_change: 다듬은 글이 이 문항의 정답에 필요한 원문의 뜻을 표시 없이 바꾸거나, 빼거나, 흐렸다. 그래서 다듬은 글만으로는 정답을 고를 수 없거나 다른 보기가 맞아 보인다.
- other: 다듬은 글에도 정답에 필요한 뜻이 그대로 있다(독자의 실수, 문항의 모호함 등).
reason에는 판단 근거를 한두 문장으로 쓴다.

{cases}

출력은 JSON이다. 예: {{"cases": [{{"id": "c1a2b3c4", "cause": "other", "reason": "..."}}]}}"""

CLS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["cases"],
              "properties": {"cases": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["id", "cause", "reason"],
                  "properties": {"id": {"type": "string"}, "cause": {"type": "string", "enum": CAUSES},
                                 "reason": {"type": "string"}}}}}}


def wrong_cases(its):
    """Rewritten-text errors of the primary reader. The case id hides the condition from the classifier."""
    out = []
    for it in its:
        o = json.loads((OUT / "answers" / "original" / "grok" / f"{it['id']}.json").read_text())
        for c in CONDS:
            rec = json.loads((OUT / "answers" / c / "grok" / f"{it['id']}.json").read_text())
            for i, (x, g) in enumerate(zip(rec["answers"], rec["gold"])):
                if x != g:
                    cid = hashlib.md5(f"{c}|{it['id']}|{i}".encode()).hexdigest()[:8]
                    out.append({"id": cid, "cond": c, "pid": it["id"], "q": i, "answer": x,
                                "orig_wrong": o["answers"][i] != g})
    return sorted(out, key=lambda x: x["id"])


def case_block(k, its_by):
    it = its_by[k["pid"]]
    q = it["questions"][k["q"]]
    return (f'<사례 id="{k["id"]}">\n<원문>\n{it["text"]}\n</원문>\n<다듬은 글>\n{text(it, k["cond"])}\n</다듬은 글>\n'
            f'문항: {q["q"]}\nA. {q["A"]}\nB. {q["B"]}\nC. {q["C"]}\nD. {q["D"]}\nE. {R.E_TEXT}\n'
            f'정답: {q["answer"]}\n독자의 답: {k["answer"]}\n</사례>')


def classify(who, batch, its_by):
    key = hashlib.md5(",".join(k["id"] for k in batch).encode()).hexdigest()[:10]
    f = OUT / "classify" / who / f"{key}.json"
    if not f.exists():
        prompt = CLS_PROMPT.format(cases="\n\n".join(case_block(k, its_by) for k in batch))
        raw = R.call(who, prompt, CLS_SCHEMA)
        jdump(f, {"ids": [k["id"] for k in batch], "out": R.first_json(raw)})
    got = {x["id"]: x for x in json.loads(f.read_text())["out"]["cases"]}
    return {k["id"]: got.get(k["id"], {}).get("cause") for k in batch}


def cmd_classify(a):
    its = items(a)
    by = {it["id"]: it for it in its}
    cases = wrong_cases(its)
    res = {}
    for who in ("codex", "grok"):  # codex is the registered classifier; grok is the agreement check
        res[who] = {}
        for d in R.pmap(lambda b: classify(who, b, by), chunks(cases, 8), workers=2):
            res[who].update(d)
    jdump(OUT / ("causes-pilot.json" if a.n else "causes.json"),
          [{**k, "codex": res["codex"].get(k["id"]), "grok": res["grok"].get(k["id"])} for k in cases])
    R.log(f"classified {len(cases)} cases")


# ---------- analysis ----------

def acc(rec):
    return sum(x == g for x, g in zip(rec["answers"], rec["gold"])) / len(rec["gold"])


def paired(recs, x, y):
    ids = sorted(set(recs[x]) & set(recs[y]))
    d = [acc(recs[x][i]) - acc(recs[y][i]) for i in ids]
    m, lo, hi = R.boot(d)
    return {"passages": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "sd": round(statistics.stdev(d), 4)}


def kappa(xs, ys):
    n = len(xs)
    po = sum(a == b for a, b in zip(xs, ys)) / n
    pe = sum((xs.count(c) / n) * (ys.count(c) / n) for c in set(xs) | set(ys))
    return po, (po - pe) / (1 - pe) if pe < 1 else 1.0


def cmd_analyze(a):
    its = items(a)
    recs = {c: {} for c in ALL}
    for it in its:
        fs = {c: OUT / "answers" / c / "grok" / f"{it['id']}.json" for c in ALL}
        if all(f.exists() for f in fs.values()):  # only passages with every condition read
            for c, f in fs.items():
                recs[c][it["id"]] = json.loads(f.read_text())
    by = {it["id"]: it for it in its}
    ids = sorted(recs["original"])
    summ = {}
    for c in ALL:
        r = R.rates(list(recs[c].values()))
        ts = [text(by[i], c) for i in ids]
        summ[c] = {**{k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()},
                   "chars_mean": round(statistics.mean(len(t) for t in ts)),
                   "texts_with_flag": sum(bool(FLAG.search(t)) for t in ts)}
    tests = {}
    for c in CONDS:
        t = paired(recs, c, "original")
        tests[f"acc {c}-original"] = {**t, "noninferior_3pp": t["ci95"][0] > MARGIN}
    tests["acc full-base"] = paired(recs, "full", "base")
    tests["acc short-base"] = paired(recs, "short", "base")
    base = summ["base"]
    rep = {"passages": len(ids), "questions": sum(len(by[i]["questions"]) for i in ids), "summary": summ,
           "tests": tests, "ceiling_broken": base["acc"] <= 0.95 or base["misread"] >= 0.03,
           "original_below_100": summ["original"]["acc"] < 1.0}
    cf = OUT / ("causes-pilot.json" if a.n else "causes.json")
    if cf.exists():
        cases = [k for k in json.loads(cf.read_text()) if k["pid"] in recs["original"]]
        causes = {c: {x: sum(k["cond"] == c and k["codex"] == x for k in cases) for x in CAUSES + [None]}
                  for c in CONDS}
        both = [k for k in cases if k["codex"] and k["grok"]]
        po, kp = kappa([k["codex"] for k in both], [k["grok"] for k in both]) if both else (None, None)
        rep["causes_codex"] = {c: {str(k): v for k, v in d.items()} for c, d in causes.items()}
        rep["orig_also_wrong"] = {c: sum(k["cond"] == c and k["orig_wrong"] for k in cases) for c in CONDS}
        rep["cause_agreement_codex_grok"] = {"cases": len(both), "agreement": po and round(po, 3),
                                             "kappa": kp and round(kp, 3)}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / ("report-pilot.json" if a.n else "report.json")).write_text(out)
    print(out)


def selftest():
    md = ("---\ntitle: x\n---\n## 짧다\n한 줄이다.\n## 본문\n" + "파드는 노드에서 실행된다. " * 30
          + "\n### 코드\n" + "```\nkubectl get\n```\n" + "가나다라마바사. " * 60)
    ps = picks(md)
    assert len(ps) == 1 and ps[0][0] == "본문" and ps[0][1].startswith("파드는") and "```" not in ps[0][1]
    assert clean('{{< glossary_tooltip text="파드" term_id="pod" >}}와 [문서](/docs/x)') == "파드와 문서"
    assert picks("## a\n" + "{{< note >}}노드가 있다. " * 40) == []
    qs = [{"answer": "A"}, {"answer": "B"}, {"answer": "C"}]
    opened = {"codex": ["A", "B", "D"], "haiku": ["A", "B", "C"]}
    closed = {"codex": ["A", "E", "E"], "haiku": ["A", "B", "E"]}
    assert keep(qs, opened, closed) == [1]  # Q1 guessable closed-book, Q3 codex wrong open-book
    s = sel_schema([("P001", 2)])
    assert s["required"] == ["P001"] and s["properties"]["P001"]["required"] == ["Q1", "Q2"]
    recs = {"original": {"P1": {"answers": list("AB"), "gold": list("AB")}, "P2": {"answers": list("AE"), "gold": list("AB")}},
            "full": {"P1": {"answers": list("AE"), "gold": list("AB")}, "P2": {"answers": list("AE"), "gold": list("AB")}}}
    t = paired(recs, "full", "original")
    assert t["passages"] == 2 and abs(t["diff"] + 0.25) < 1e-9
    po, kp = kappa(["a", "a", "b", "b"], ["a", "a", "b", "b"])
    assert po == 1 and kp == 1
    po, kp = kappa(["a", "b", "a", "b"], ["a", "a", "b", "b"])
    assert po == 0.5 and abs(kp) < 1e-9
    sd, need = sample_size(0.0, 0.0)
    assert sd == 0 and need == 0
    sd, need = sample_size(0.09, 0.02)
    assert 60 < need < 120, need
    assert FLAG.search("확인이 필요한 부분") and FLAG.search("확인 필요:") and not FLAG.search("확인했다")
    assert "{texts}" in QG_PROMPT and "그 글을 읽은 독자가" in QG_PROMPT
    QG_PROMPT.format(texts="x"), SEL_PROMPT.format(blocks="x"), CLS_PROMPT.format(cases="x")
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["samplesize", "passages", "items", "write", "read", "classify", "analyze", "selftest"])
    ap.add_argument("--n", type=int, default=0, help="pilot: first N candidates only")
    a = ap.parse_args()
    if a.cmd in ("items", "classify"):
        R._codex_home()  # once, before threads: concurrent first calls race on the auth symlink
    {"samplesize": cmd_samplesize, "passages": cmd_passages, "items": cmd_items, "write": cmd_write,
     "read": cmd_read, "classify": cmd_classify, "analyze": cmd_analyze, "selftest": lambda _: selftest()}[a.cmd](a)
