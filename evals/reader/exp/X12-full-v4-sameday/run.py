#!/usr/bin/env python3
"""X12-full-v4-sameday: full-v4 against full-v3 written in the same run, the two conditions interleaved.

Part 1 (p1): X8 memos and questions; Grok trap misreads (X10 criterion 5 again, same day).
Part 2 (p2): X10's 19 kept memos written once more; clear-date accuracy pooled with X10's own texts (X10 criterion 2).
Design and pre-registration: PREREG.md.
Usage: python3 run.py <freeze|texts|judge|analyze|all|selftest|power> [--pilot]
Every model response is cached under out/; a rerun skips calls whose file exists.
X8 and X10 memos, questions, prompt blocks, texts and answers are read by path; nothing is copied or written there.
"""
import argparse
import ast
import datetime
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP.parent.parent))
import reader as R  # noqa: E402

OUT = EXP / "out"
X8 = EXP.parent / "X8-referents"
X10 = EXP.parent / "X10-dates-v4"
CONDS = ["full-v3", "full-v4"]
PROMPT_SHA = {"full-v3": "dbb1b6fbb548888ad6224aacd7c9edd012863907101f394cac49135a99af2fe4",
              "full-v4": "0f11300d1293890f63d6167dcdf1b787f46aa4bb0a04180dac4ac55dd0b3bc24"}  # X10 run.py PROMPT_SHA
KEPT = {"p1": X8 / "out" / "kept", "p2": X10 / "out" / "kept"}
PILOT = {"p1": ["M01", "M02"], "p2": ["V02"]}
FIELDS = {"p1": ("kind", "qid"), "p2": ("kind", "ref", "qid")}
READERS = ["grok", "haiku"]
TODAY = {"full-v3": "v3-x12", "full-v4": "v4-x12"}
# (part, group) -> (texts dir, answers dir); groups other than *-x12 are earlier runs, read by path
SRC = {("p1", "v3-x12"): (OUT / "texts/p1/full-v3", OUT / "answers/p1/full-v3"),
       ("p1", "v4-x12"): (OUT / "texts/p1/full-v4", OUT / "answers/p1/full-v4"),
       ("p1", "v3-x8"): (X8 / "out/texts/full", X8 / "out/answers/full"),
       ("p1", "v4-x10"): (X10 / "out/rep/X8/texts/full-v4", X10 / "out/rep/X8/answers/full-v4"),
       ("p2", "v3-x12"): (OUT / "texts/p2/full-v3", OUT / "answers/p2/full-v3"),
       ("p2", "v4-x12"): (OUT / "texts/p2/full-v4", OUT / "answers/p2/full-v4"),
       ("p2", "v3-x10"): (X10 / "out/texts/full-v3", X10 / "out/answers/full-v3"),
       ("p2", "v4-x10"): (X10 / "out/texts/full-v4", X10 / "out/answers/full-v4")}
GROUPS = {p: [g for q, g in SRC if q == p] for p in KEPT}
KINDS = ["deixis", "shared_name", "alias", "abbrev"]
CATS = ["invent", "keep", "flag", "omit"]
JUDGE_SAMPLE = [f"M{i:02d}" for i in range(1, 25, 4)]  # 25% re-judged by Grok, as in X8
MARGIN = {"A": 0.10, "B": -0.03, "C": 0.0}
FLAG_RE = re.compile(r"확인\s*필요|확인이\s*필요")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def block_file(c):
    return X10 / "out" / "prompts" / f"{c}.txt"


def system_for(c):
    """Same construction as X10's run.py: R.BASE_SYS, a blank line, the frozen block."""
    b = block_file(c).read_text()
    assert sha(b) == PROMPT_SHA[c], f"{c} block differs from X10's frozen one"
    return R.BASE_SYS + "\n\n" + b


def prompt_hashes():
    return {c: {"path": str(block_file(c).relative_to(R.REPO)), "chars": len(block_file(c).read_text()),
                "sha256": sha(block_file(c).read_text())} for c in CONDS}


def stamp(name):
    f = OUT / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), **prompt_hashes()},
                            ensure_ascii=False, indent=1))


def cmd_freeze(_pilot=False):
    """Record the block hashes once, before the first text is written."""
    for c in CONDS:
        system_for(c)
    if not (OUT / "prompt-sha-before.json").exists():
        stamp("prompt-sha-before.json")
    print((OUT / "prompt-sha-before.json").read_text())


# ---------- caches (from X10's run.py) ----------

def cached(f, make, tries=3):
    """JSON cache: return f's content, else call make() (which validates and may raise) and store it."""
    if f.exists():
        return json.loads(f.read_text())
    assert OUT in f.parents, f"refusing to write outside {OUT}: {f}"
    for i in range(tries):
        try:
            v = make()
            break
        except Exception as e:  # ponytail: plain retry; R.call already retries CLI failures
            log(f"retry {f.relative_to(OUT)} {i + 1}/{tries}: {e}")
    else:
        raise RuntimeError(f"{f} failed {tries} times")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(v, ensure_ascii=False, indent=1))
    return v


def once(f, make, tries=3):
    """Text cache: write make()'s non-empty output to f unless f exists."""
    if f.exists():
        return
    assert OUT in f.parents, f"refusing to write outside {OUT}: {f}"
    for i in range(tries):
        try:
            t = make()
            if not t.strip():
                raise RuntimeError("empty text")
            break
        except Exception as e:
            log(f"retry {f.relative_to(OUT)} {i + 1}/{tries}: {e}")
    else:
        raise RuntimeError(f"{f} failed {tries} times")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(t)


def need_env():
    missing = [k for k in ("KSTE_CODEX_HOME", "KSTE_CODEX_AUTH", "KSTE_LIMIT_GROK", "KSTE_LIMIT_CODEX",
                           "KSTE_LIMIT_CLAUDE") if not os.environ.get(k)]
    if missing:
        sys.exit(f"set {missing} first (BRIEF.md)")
    if "X12" not in os.environ["KSTE_CODEX_HOME"]:
        sys.exit("KSTE_CODEX_HOME must be this experiment's own folder (BRIEF.md)")


def limit(who):
    return int(os.environ.get(f"KSTE_LIMIT_{'CLAUDE' if who in R.WRITERS else who.upper()}", 2))


# ---------- texts and reading ----------

def memos(part, pilot=False):
    its = [json.loads(p.read_text()) for p in sorted(KEPT[part].glob("[MV][0-9]*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT[part]]


def text_f(part, g, w, mid):
    return SRC[(part, g)][0] / w / f"{mid}.md"


def ans_f(part, g, w, r, mid):
    return SRC[(part, g)][1] / w / r / f"{mid}.json"


def persona(part, w, r, mid):
    """The same persona for both conditions of a (memo, writer, reader): the pair differs only in the prompt."""
    return R.persona_for(f"X12/{part}/{w}/{r}/{mid}")


def job_order(pilot=False):
    """Memo by memo and writer by writer; within each pair the condition order is a fixed coin flip."""
    jobs = []
    for part in KEPT:
        for it in memos(part, pilot):
            for w in R.WRITERS:
                pair = list(CONDS)
                random.Random(f"X12-order-{part}-{it['id']}-{w}").shuffle(pair)
                jobs += [(part, it, c, w) for c in pair]
    return jobs


def text_job(job):
    """Write one text, then let Haiku and Grok read it. Provider limits are R.LIMITS, so many jobs can wait."""
    part, it, c, w = job
    g, qs = TODAY[c], it["questions"]
    f = text_f(part, g, w, it["id"])
    once(f, lambda: R.call(w, R.memo(it), system=system_for(c)))
    for r in ("haiku", "grok"):
        cached(ans_f(part, g, w, r, it["id"]),
               lambda r=r: {"answers": R.ask(r, f.read_text(), qs, persona(part, w, r, it["id"])),
                            "gold": [q["answer"] for q in qs], **{k: [q[k] for q in qs] for k in FIELDS[part]}})


def cmd_texts(pilot):
    cmd_freeze()
    jobs = job_order(pilot)
    log(f"text jobs: {len(jobs)}")
    R.pmap(text_job, jobs, workers=32)
    stamp("prompt-sha-after-pilot.json" if pilot else "prompt-sha-after.json")


# ---------- judging (part 1, X8's prompt) ----------

def x8_const(name):
    """A string constant of X8's run.py, read from its source so the judge prompt is X8's own."""
    for n in ast.parse((X8 / "run.py").read_text()).body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name:
            return ast.literal_eval(n.value)
    raise KeyError(name)


JUDGE_SCHEMA = {  # X8's JUDGE_SCHEMA
    "type": "object", "additionalProperties": False, "required": ["texts"],
    "properties": {"texts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "traps", "extra_flags"],
        "properties": {"id": {"type": "string"},
                       "traps": {"type": "array", "items": {"type": "string", "enum": CATS}},
                       "extra_flags": {"type": "integer"}}}}}}


def judge_order(mid):
    """8 texts per memo, as in X8: today's two conditions and the two earlier runs, shuffled, names hidden."""
    order = [(g, w) for g in GROUPS["p1"] for w in R.WRITERS]
    random.Random(f"X12-judge-{mid}").shuffle(order)
    return order


def judge_prompt(it, order):
    traps = "\n".join(f"{i}. ({t['kind']}) 메모 항목 \"{it['facts'][t['fact']]}\": {t['what']}"
                      for i, t in enumerate(it["traps"]))
    texts = "\n\n".join(f"<글 T{i + 1}>\n{text_f('p1', g, w, it['id']).read_text()}\n</글 T{i + 1}>"
                        for i, (g, w) in enumerate(order))
    return x8_const("JUDGE_PROMPT").format(k=len(it["traps"]), memo=R.memo(it), traps=traps, texts=texts,
                                           n=len(order), example=", ".join('"keep"' for _ in it["traps"]))


def parse_judge(raw, order, k):
    """Map T1..Tn back to (group, writer); raise unless every text has k valid categories."""
    got = {t["id"].strip(): t for t in R.first_json(raw)["texts"]}
    out = {}
    for i, (g, w) in enumerate(order):
        t = got[f"T{i + 1}"]
        if len(t["traps"]) != k or any(x not in CATS for x in t["traps"]) or int(t["extra_flags"]) < 0:
            raise ValueError(f"bad judgment T{i + 1}: {t}")
        out[f"{g}/{w}"] = {"traps": t["traps"], "extra_flags": int(t["extra_flags"])}
    return out


def grok_long(prompt, timeout=1200):
    """R.grok with a longer timeout, as in X8 and X10."""
    with R.LIMITS["grok"]:
        return R._run(["grok", "-p", prompt, "-m", R.GROK_MODEL, "--system-prompt-override",
                       "You are a careful reader. Follow the user message only.", "--tools", "", "--no-subagents",
                       "--disable-web-search", "--max-turns", "1", "--output-format", "plain"], timeout=timeout)


def cmd_judge(pilot):
    def one(job):
        it, who = job
        mid, order, k = it["id"], judge_order(it["id"]), len(it["traps"])
        if who == "codex":
            cached(OUT / "judge" / "codex" / f"{mid}.json",
                   lambda: parse_judge(R.call("codex", judge_prompt(it, order), JUDGE_SCHEMA), order, k))
            return
        out = {}
        for i, part in enumerate((order[:4], order[4:])):  # 4 texts per Grok call to stay under the timeout
            out.update(cached(OUT / "judge" / "grok-parts" / f"{mid}-{i}.json",
                              lambda: parse_judge(grok_long(judge_prompt(it, part)), part, k)))
        f = OUT / "judge" / "grok" / f"{mid}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    its = memos("p1", pilot)
    sample = PILOT["p1"][:1] if pilot else JUDGE_SAMPLE
    jobs = [(it, "codex") for it in its] + [(it, "grok") for it in its if it["id"] in sample]
    R.pmap(one, jobs, workers=limit("codex") + limit("grok"))


# ---------- analysis ----------

def rates(pairs):
    """pairs: [(answer, gold)]. A correct E counts as correct only; abstain is E when the gold is not E."""
    n = len(pairs)
    if not n:
        return None
    ok = sum(a == g for a, g in pairs)
    mis = sum(a != g and a != "E" for a, g in pairs)
    ab = sum(a == "E" and g != "E" for a, g in pairs)
    return {"acc": ok / n, "misread": mis / n, "abstain": ab / n, "n": n}


def r9(x):
    """Round before comparing with a criterion: R.boot can return -1e-18 for an exact 0 (X8 H1)."""
    return round(x, 9)


def r4(d):
    return None if d is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def paired(mx, my):
    ids = sorted(i for i in set(mx) & set(my) if mx[i] is not None and my[i] is not None)
    if not ids:
        return None
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"memos": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def x8_balance(its):
    """X8 PREREG filtering step 3, as X8's and X10's run.py apply it at analysis time."""
    trap = [q for it in its for q in it["questions"] if q["kind"] != "none"]
    e = sorted(q["qid"] for q in trap if q["answer"] == "E")
    random.Random("X8-balance").shuffle(e)
    n_e, n_t, drop = len(e), len(trap), []
    while 2 * n_e > n_t:
        drop.append(e.pop())
        n_e, n_t = n_e - 1, n_t - 1
    return set(drop)


def selectors(part, its):
    """sel(rec) -> [(answer, gold)] for one subset of questions."""
    def pick(want, drop=frozenset()):
        return lambda rec: [(a, g) for a, g, k, q in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
                            if q not in drop and want(k)]
    if part == "p2":
        return {k: pick(lambda x, k=k: k in ("all", x)) for k in ("all", "gap", "clear", "other")}
    drop = x8_balance(its)
    return {"all": pick(lambda k: True, drop), "trap": pick(lambda k: k != "none", drop),
            "nontrap": pick(lambda k: k == "none", drop), **{k: pick(lambda x, k=k: x == k, drop) for k in KINDS}}


def load_answers(part, mids):
    """{(group, w, r): {mid: rec}} for the files that exist."""
    return {(g, w, r): {m: json.loads(ans_f(part, g, w, r, m).read_text()) for m in mids
                        if ans_f(part, g, w, r, m).exists()}
            for g in GROUPS[part] for w in R.WRITERS for r in READERS}


def per_memo(ans, gs, r, mids, sel, metric):
    """Per-memo rate over every (group in gs, writer) record of that memo."""
    out = {}
    for mid in mids:
        ps = [x for g in gs for w in R.WRITERS if mid in ans[(g, w, r)] for x in sel(ans[(g, w, r)][mid])]
        out[mid] = rates(ps)[metric] if ps else None
    return out


def pooled(ans, gs, r, sel, ws=R.WRITERS):
    return r4(rates([x for g in gs for w in ws for rec in ans[(g, w, r)].values() for x in sel(rec)]))


def text_stats(texts):
    n = len(texts)
    return {"texts": n, "chars_mean": round(sum(map(len, texts)) / n) if n else None,
            "texts_with_kakunin": sum(bool(FLAG_RE.search(t)) for t in texts),
            "kakunin_per_text": round(sum(len(FLAG_RE.findall(t)) for t in texts) / n, 3) if n else None}


def write_order(part):
    """Completion order of today's texts (file mtimes): evidence that the two conditions were interleaved."""
    fs = sorted(((f.stat().st_mtime, c) for c in CONDS for f in SRC[(part, TODAY[c])][0].glob("*/*.md")))
    if not fs:
        return None
    runs, longest = 1, 1
    for (_, a), (_, b) in zip(fs, fs[1:]):
        runs = runs + 1 if a == b else 1
        longest = max(longest, runs)
    t = lambda x: datetime.datetime.fromtimestamp(x).isoformat(timespec="seconds")  # noqa: E731
    return {"texts": len(fs), "longest_same_condition_run": longest,
            **{c: {"first": t(min(m for m, x in fs if x == c)), "last": t(max(m for m, x in fs if x == c))}
               for c in CONDS if any(x == c for _, x in fs)}}


def summarize(part, mids, ans, sels):
    out = {}
    for g in GROUPS[part]:
        texts = [text_f(part, g, w, m).read_text() for w in R.WRITERS for m in mids if text_f(part, g, w, m).exists()]
        out[g] = {r: {k: pooled(ans, [g], r, f) for k, f in sels.items()} for r in READERS}
        out[g]["grok_by_writer"] = {w: {k: pooled(ans, [g], "grok", f, [w]) for k, f in sels.items() if k != "all"}
                                    for w in R.WRITERS}
        out[g].update(text_stats(texts))
    return out


def tests_for(ans, mids, sels, comps, metrics):
    """comps: [(name, gs_x, gs_y)], metrics: [(subset, metric, readers)]."""
    return {f"{r} {k} {m} {name}": paired(per_memo(ans, x, r, mids, sels[k], m), per_memo(ans, y, r, mids, sels[k], m))
            for name, x, y in comps for k, m, rs in metrics for r in rs}


def load_judge(who, d=OUT / "judge"):
    return {p.stem: json.loads(p.read_text()) for p in sorted((d / who).glob("M*.json"))}


def handling(judged, its, groups):
    out = {}
    for g in groups:
        cells = [(mid, j[f"{g}/{w}"]) for mid, j in judged.items() for w in R.WRITERS if f"{g}/{w}" in j]
        if not cells:
            continue
        by_kind = {k: [cell["traps"][i] for mid, cell in cells for i, t in enumerate(its[mid]["traps"]) if t["kind"] == k]
                   for k in KINDS}
        cats = [x for v in by_kind.values() for x in v]
        nonalias = [x for k, v in by_kind.items() if k != "alias" for x in v]
        out[g] = {"texts": len(cells), "dist": {k: round(cats.count(k) / len(cats), 3) for k in CATS},
                  "by_kind": {k: {x: v.count(x) for x in CATS} for k, v in by_kind.items()},
                  "nonalias_invent": [nonalias.count("invent"), len(nonalias)],
                  "extra_flags_total": sum(cell["extra_flags"] for _, cell in cells),
                  "extra_flags_per_text": round(sum(cell["extra_flags"] for _, cell in cells) / len(cells), 3)}
    return out


def agreement(j1, j2, keys=None):
    """Category agreement of two judgments of the same texts (keys: which 'group/writer' cells)."""
    both = sorted(set(j1) & set(j2))
    ks = [(m, k) for m in both for k in j2[m] if k in j1[m] and (keys is None or k.split("/")[0] in keys)]
    cp = [(a, b) for m, k in ks for a, b in zip(j1[m][k]["traps"], j2[m][k]["traps"])]
    ep = [(j1[m][k]["extra_flags"], j2[m][k]["extra_flags"]) for m, k in ks]
    if not cp:
        return None
    return {"memos": len(both), "texts": len(ks), "trap_cells": len(cp),
            "category": round(sum(a == b for a, b in cp) / len(cp), 3),
            "flag": round(sum((a == "flag") == (b == "flag") for a, b in cp) / len(cp), 3),
            "invent": round(sum((a == "invent") == (b == "invent") for a, b in cp) / len(cp), 3),
            "extra_flags_exact": round(sum(a == b for a, b in ep) / len(ep), 3),
            "extra_flags_total": [sum(a for a, _ in ep), sum(b for _, b in ep)]}


def analyze_p1(pilot):
    its = {it["id"]: it for it in memos("p1", pilot)}
    mids, sels = sorted(its), selectors("p1", list(memos("p1")))  # the balance rule always sees all 24 memos
    ans = load_answers("p1", mids)
    comps = [("v4-x12 - v3-x12", ["v4-x12"], ["v3-x12"]),  # criterion A
             ("v3-x12 - v3-x8", ["v3-x12"], ["v3-x8"]), ("v4-x12 - v4-x10", ["v4-x12"], ["v4-x10"]),
             ("v4-x10 - v3-x8", ["v4-x10"], ["v3-x8"]),  # X10 criterion 5, recomputed
             ("v4 both runs - v3 both runs", ["v4-x12", "v4-x10"], ["v3-x12", "v3-x8"])]
    metrics = [("trap", "misread", READERS), ("nontrap", "acc", ["grok"]), ("alias", "acc", ["grok"])]
    j1, drop = load_judge("codex"), x8_balance(memos("p1"))
    by_cat = {}  # exploratory: judged handling of a trap x Grok's answer on that trap's question, today's texts
    for mid, j in j1.items():
        if mid not in its:
            continue
        q_trap = {q["qid"]: q["trap"] for q in its[mid]["questions"]}
        for key, cell in j.items():
            g, w = key.split("/")
            rec = ans[(g, w, "grok")].get(mid)
            for a, gold, k, qid in (zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
                                    if rec and g.endswith("x12") else ()):
                if k != "none" and qid not in drop:
                    by_cat.setdefault(k, {}).setdefault(cell["traps"][q_trap[qid]], []).append((a, gold))
    def extra(g):  # judged extra flags per text, mean of the two writers
        return {mid: sum(j[f"{g}/{w}"]["extra_flags"] for w in R.WRITERS) / len(R.WRITERS) for mid, j in j1.items()}

    v3_x8_orig = load_judge("codex", X8 / "out" / "judge")
    relabel = {m: {k.replace("full/", "v3-x8/"): v for k, v in j.items() if k.startswith("full/")}
               for m, j in v3_x8_orig.items()}
    return {"memos": len(mids), "summary": summarize("p1", mids, ans, sels),
            "tests": tests_for(ans, mids, sels, comps, metrics),
            "grok_trap_by_kind": {g: {k: pooled(ans, [g], "grok", sels[k]) for k in KINDS} for g in GROUPS["p1"]},
            "judge_handling": handling(j1, its, GROUPS["p1"]),
            "judge_agreement": {"grok_vs_codex": agreement(j1, load_judge("grok")),
                                "codex_x12_vs_codex_x8_on_v3_x8_texts": agreement(j1, relabel, {"v3-x8"})},
            "exploratory": {"grok_trap_by_kind_and_judged_handling_x12":
                            {k: {x: r4(rates(v)) for x, v in sorted(d.items())} for k, d in sorted(by_cat.items())},
                            "judged_extra_flags_per_text": {f"{x} - {y}": paired(extra(x), extra(y)) for x, y in
                                                            (("v4-x12", "v3-x12"), ("v4-x10", "v3-x8"))}},
            "write_order": write_order("p1"),
            "ceiling_broken_v3_x12": (lambda b: bool(b and (b["acc"] <= 0.95 or b["misread"] >= 0.03)))(
                pooled(ans, ["v3-x12"], "grok", sels["all"]))}


def analyze_p2(pilot):
    its = {it["id"]: it for it in memos("p2", pilot)}
    mids, sels = sorted(its), selectors("p2", None)
    ans = load_answers("p2", mids)
    comps = [("v4 both runs - v3 both runs", ["v4-x10", "v4-x12"], ["v3-x10", "v3-x12"]),  # criteria B and C
             ("v4-x12 - v3-x12", ["v4-x12"], ["v3-x12"]), ("v4-x10 - v3-x10", ["v4-x10"], ["v3-x10"]),
             ("v3-x12 - v3-x10", ["v3-x12"], ["v3-x10"]), ("v4-x12 - v4-x10", ["v4-x12"], ["v4-x10"])]
    metrics = [("gap", "misread", READERS), ("clear", "acc", READERS), ("other", "acc", ["grok"])]
    wrong = []  # today's wrong answers on clear-date questions, for the RESULTS table
    for g in ("v3-x12", "v4-x12"):
        for w in R.WRITERS:
            for mid, rec in ans[(g, w, "grok")].items():
                for a, gold, k, ref, qid in zip(rec["answers"], rec["gold"], rec["kind"], rec["ref"], rec["qid"]):
                    if k == "clear" and a != gold:
                        c = its[mid]["clear"][ref]
                        wrong.append({"group": g, "writer": w, "qid": qid, "answer": a, "gold": gold,
                                      "marker": c["marker"], "fact": its[mid]["facts"][c["fact"]]})
    summary = summarize("p2", mids, ans, sels)
    summary["v3 both runs"] = {r: {k: pooled(ans, ["v3-x10", "v3-x12"], r, f) for k, f in sels.items()} for r in READERS}
    summary["v4 both runs"] = {r: {k: pooled(ans, ["v4-x10", "v4-x12"], r, f) for k, f in sels.items()} for r in READERS}
    return {"memos": len(mids), "summary": summary, "tests": tests_for(ans, mids, sels, comps, metrics),
            "grok_clear_wrong_x12": wrong, "write_order": write_order("p2")}


def verdict(p1, p2):
    a = p1["tests"]["grok trap misread v4-x12 - v3-x12"]
    b = p2["tests"]["grok clear acc v4 both runs - v3 both runs"]
    c = p2["tests"]["grok gap misread v4 both runs - v3 both runs"]
    if not all((a, b, c)):
        return None
    v = {"A_x8_trap_upper_below_10pp": r9(a["ci95"][1]) < MARGIN["A"],
         "B_clear_lower_above_minus_3pp": r9(b["ci95"][0]) > MARGIN["B"],
         "C_gap_upper_below_0_confirmatory": r9(c["ci95"][1]) < MARGIN["C"]}
    v["adopt"] = v["A_x8_trap_upper_below_10pp"] and v["B_clear_lower_above_minus_3pp"]  # C is not used
    return v


def cmd_analyze(pilot=False):
    p1, p2 = analyze_p1(pilot), analyze_p2(pilot)
    after = OUT / ("prompt-sha-after-pilot.json" if pilot else "prompt-sha-after.json")
    rep = {"verdict": verdict(p1, p2), "part1_x8": p1, "part2_x10": p2,
           "prompt_sha256": PROMPT_SHA, "prompt_now": prompt_hashes(),
           "prompt_before": json.loads((OUT / "prompt-sha-before.json").read_text()),
           "prompt_after": json.loads(after.read_text()) if after.exists() else None, "margins": MARGIN}
    assert all(rep["prompt_now"][c]["sha256"] == PROMPT_SHA[c] for c in CONDS)
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / ("report-pilot.json" if pilot else "report.json")).write_text(out)
    print(json.dumps(rep["verdict"], indent=1))
    for name, p in (("p1", p1), ("p2", p2)):
        for k, v in p["tests"].items():
            print(name, k, v)


# ---------- power (PREREG numbers, from X8 and X10 files only) ----------

def cmd_power(_pilot=False):
    def boot_bound(d, side):
        return r9(R.boot(d, n=2000)[side])

    # A: X10's per-memo differences (full-v4 run of 10-19 13h - full-v3 run of 10-19 9h), centred, then shifted
    its = memos("p1")
    sel, mids = selectors("p1", its)["trap"], sorted(it["id"] for it in its)
    ans = load_answers("p1", mids)
    x, y = (per_memo(ans, [g], "grok", mids, sel, "misread") for g in ("v4-x10", "v3-x8"))
    d = [x[m] - y[m] for m in mids]
    mu = sum(d) / len(d)
    rnd, reps, a_pass = random.Random(1), 400, {}
    for delta in (0.0, 0.02, 0.047):
        c = [v - mu + delta for v in d]
        a_pass[f"true_diff={delta}"] = sum(boot_bound([rnd.choice(c) for _ in c], 2) < MARGIN["A"]
                                           for _ in range(reps)) / reps
    # B: X10's round is fixed (observed); round 2 is simulated with X10's pooled error rate for both conditions
    its2 = {it["id"]: it for it in memos("p2")}
    mids2 = sorted(its2)
    ans2 = load_answers("p2", mids2)
    csel = selectors("p2", None)["clear"]
    obs = {g: {m: [x for w in R.WRITERS for x in csel(ans2[(g, w, "grok")][m])] for m in mids2}
           for g in ("v3-x10", "v4-x10")}
    p = sum(a != gl for g in obs for v in obs[g].values() for a, gl in v) / sum(len(v) for g in obs for v in obs[g].values())
    b_pass = {}
    for extra in (0.0, 0.01, 0.02):
        rnd, ok = random.Random(3), 0
        for _ in range(200):
            diff = []
            for m in mids2:
                n = len(obs["v3-x10"][m])  # 2 writers x clear questions; round 2 has the same count
                e3 = sum(a != gl for a, gl in obs["v3-x10"][m]) + sum(rnd.random() < p for _ in range(n))
                e4 = sum(a != gl for a, gl in obs["v4-x10"][m]) + sum(rnd.random() < p + extra for _ in range(n))
                diff.append((e3 - e4) / (2 * n))
            ok += boot_bound(diff, 1) > MARGIN["B"]
        b_pass[f"v4_extra={extra}"] = ok / 200
    out = {"A": {"memos": len(d), "x10_observed": paired(x, y), "pass_rate": a_pass},
           "B": {"memos": len(mids2), "x10_error_rate": round(p, 4),
                 "clear_answers_per_condition_x10": sum(len(v) for v in obs["v3-x10"].values()),
                 "x10_observed": paired(*(per_memo(ans2, [g], "grok", mids2, csel, "acc") for g in ("v4-x10", "v3-x10"))),
                 "pass_rate_given_x10_round": b_pass}}
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------- selftest ----------

def selftest():
    assert rates([("E", "E"), ("A", "E"), ("E", "B"), ("C", "C")]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert rates([]) is None
    assert r9(-1.2e-18) == 0 and not r9(-1.2e-18) < 0
    assert paired({"M01": 0.5, "M02": None}, {"M01": 0.25, "M02": 0.0}) == {"memos": 1, "diff": 0.25, "ci95": [0.25, 0.25]}
    # prompts: X10's frozen blocks, X10's construction
    for c in CONDS:
        assert system_for(c) == R.BASE_SYS + "\n\n" + block_file(c).read_text()
    assert [len(block_file(c).read_text()) for c in CONDS] == [5462, 5611]
    # memos and questions: X8 24 memos (balance drops 17), X10 19 kept memos
    p1, p2 = memos("p1"), memos("p2")
    assert len(p1) == 24 and len(p2) == 19 and len(x8_balance(p1)) == 17
    assert [it["id"] for it in memos("p1", True)] == ["M01", "M02"] and [it["id"] for it in memos("p2", True)] == ["V02"]
    s1, s2 = selectors("p1", p1), selectors("p2", None)
    assert sum(len(s1["trap"]({"answers": [q["answer"] for q in it["questions"]], "gold": [q["answer"] for q in it["questions"]],
                                "kind": [q["kind"] for q in it["questions"]], "qid": [q["qid"] for q in it["questions"]]}))
               for it in p1) == 60  # X8 RESULTS: 60 trap questions after the balance rule
    rec = {"answers": ["E", "B", "A", "C"], "gold": ["E", "C", "A", "C"], "kind": ["gap", "gap", "clear", "other"],
           "qid": ["V01-q0", "V01-q1", "V01-q2", "V01-q3"]}
    assert s2["gap"](rec) == [("E", "E"), ("B", "C")] and s2["clear"](rec) == [("A", "A")] and len(s2["all"](rec)) == 4
    drop = sorted(x8_balance(p1))[0]
    rec8 = {"answers": ["A", "E", "B", "C"], "gold": ["E", "E", "B", "C"], "kind": ["deixis", "abbrev", "none", "alias"],
            "qid": [drop, "Mxx-q1", "Mxx-q2", "Mxx-q3"]}
    assert s1["trap"](rec8) == [("E", "E"), ("C", "C")] and s1["nontrap"](rec8) == [("B", "B")]
    assert s1["deixis"](rec8) == [] and s1["alias"](rec8) == [("C", "C")]
    # pooling: per_memo pools every listed group and writer of a memo
    ans = {(g, w, "grok"): {} for g in ("a", "b") for w in R.WRITERS}
    ans[("a", "sonnet", "grok")]["V01"] = {**rec, "answers": ["A", "B", "A", "C"]}  # gap: 2 misreads of 2
    ans[("b", "haiku", "grok")]["V01"] = rec  # gap: 1 misread of 2
    assert per_memo(ans, ["a", "b"], "grok", ["V01", "V02"], s2["gap"], "misread") == {"V01": 0.75, "V02": None}
    assert per_memo(ans, ["b"], "grok", ["V01"], s2["clear"], "acc") == {"V01": 1.0}
    # paths: today's files here, earlier runs by path
    assert text_f("p1", "v3-x8", "sonnet", "M01") == X8 / "out/texts/full/sonnet/M01.md"
    assert ans_f("p1", "v4-x10", "haiku", "grok", "M01") == X10 / "out/rep/X8/answers/full-v4/haiku/grok/M01.json"
    assert ans_f("p2", "v3-x10", "haiku", "grok", "V02") == X10 / "out/answers/full-v3/haiku/grok/V02.json"
    assert text_f("p2", "v4-x12", "sonnet", "V02") == OUT / "texts/p2/full-v4/sonnet/V02.md"
    for (part, g), (td, ad) in SRC.items():
        if not g.endswith("x12"):
            mids = [it["id"] for it in (p1 if part == "p1" else p2)]
            assert all(text_f(part, g, w, m).exists() and ans_f(part, g, w, r, m).exists()
                       for w in R.WRITERS for r in READERS for m in mids), (part, g)
    # interleaving: every (part, memo, writer) pair is adjacent, both conditions, order varies
    jobs = job_order()
    assert len(jobs) == 2 * 2 * (24 + 19)
    pairs = [jobs[i:i + 2] for i in range(0, len(jobs), 2)]
    assert all({j[2] for j in pr} == set(CONDS) and len({(j[0], j[1]["id"], j[3]) for j in pr}) == 1 for pr in pairs)
    firsts = [pr[0][2] for pr in pairs]
    assert 0.3 < firsts.count("full-v3") / len(firsts) < 0.7
    assert persona("p1", "sonnet", "grok", "M01") == persona("p1", "sonnet", "grok", "M01")
    # judging: X8's prompt, 8 texts per memo, names hidden
    jp = x8_const("JUDGE_PROMPT")
    assert jp.startswith("아래 메모로 AI 글쓴이 여러 명이") and "{texts}" in jp
    assert sorted(judge_order("M01")) == sorted((g, w) for g in GROUPS["p1"] for w in R.WRITERS)
    prompt = judge_prompt(p1[0], [x for x in judge_order("M01") if not x[0].endswith("x12")])  # earlier runs only
    assert prompt.count("<글 T") == 4 and not any(g in prompt for g in GROUPS["p1"]) and "full-v" not in prompt
    order = [("v3-x12", "sonnet"), ("v4-x12", "haiku")]
    raw = 'x {"texts": [{"id": "T2", "traps": ["flag"], "extra_flags": 1}, {"id": "T1", "traps": ["invent"], "extra_flags": 0}]}'
    assert parse_judge(raw, order, 1) == {"v3-x12/sonnet": {"traps": ["invent"], "extra_flags": 0},
                                          "v4-x12/haiku": {"traps": ["flag"], "extra_flags": 1}}
    for bad in ('{"texts": [{"id": "T1", "traps": ["invent"], "extra_flags": 0}]}',
                '{"texts": [{"id": "T1", "traps": ["guess"], "extra_flags": 0}, {"id": "T2", "traps": ["flag"], "extra_flags": 0}]}'):
        try:
            parse_judge(bad, order, 1)
            raise AssertionError("parse_judge accepted " + bad)
        except (KeyError, ValueError):
            pass
    j = {"M01": {"v3-x8/sonnet": {"traps": ["flag", "keep"], "extra_flags": 1}, "v4-x12/haiku": {"traps": ["invent", "keep"], "extra_flags": 0}}}
    j2 = {"M01": {"v3-x8/sonnet": {"traps": ["flag", "invent"], "extra_flags": 1}}}
    assert agreement(j, j2)["category"] == 0.5 and agreement(j, j2)["flag"] == 1.0 and agreement(j, j2, {"v4-x12"}) is None
    # verdict: A and B decide, C does not
    t = lambda lo, hi: {"memos": 1, "diff": 0, "ci95": [lo, hi]}  # noqa: E731
    mk = lambda a, b, c: ({"tests": {"grok trap misread v4-x12 - v3-x12": a}},  # noqa: E731
                          {"tests": {"grok clear acc v4 both runs - v3 both runs": b, "grok gap misread v4 both runs - v3 both runs": c}})
    assert verdict(*mk(t(-0.05, 0.099), t(-0.029, 0.03), t(-0.5, 0.1)))["adopt"]
    assert not verdict(*mk(t(-0.05, 0.10), t(-0.029, 0.03), t(-0.5, -0.1)))["adopt"]
    assert not verdict(*mk(t(-0.05, 0.05), t(-0.03, 0.03), t(-0.5, -0.1)))["adopt"]
    print("selftest ok")


STEPS = {"freeze": cmd_freeze, "texts": cmd_texts, "judge": cmd_judge, "analyze": cmd_analyze}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=list(STEPS) + ["all", "selftest", "power"])
    ap.add_argument("--pilot", action="store_true", help="X8 M01-M02 and X10 V02 through the pipeline")
    a = ap.parse_args()
    if a.cmd in ("selftest", "power"):
        (selftest if a.cmd == "selftest" else cmd_power)()
        sys.exit()
    if a.cmd not in ("analyze", "freeze"):
        need_env()
    for step in (list(STEPS) if a.cmd == "all" else [a.cmd]):
        log(f"== {step}")
        STEPS[step](a.pilot)
