#!/usr/bin/env python3
"""X6-mt: Grok reads a Haiku English translation of the phase-1 Sonnet texts and answers the Korean questions.

Design and pre-registered criteria: PREREG.md. Control: phase-1 Grok answers on the Korean originals.
Usage: python3 run.py <pilot|run|analyze|selftest>
Outputs are cached under out/; a call is skipped when its output file exists.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # evals/reader
import reader as R  # noqa: E402

OUT = HERE / "out"
WRITER, TRANSLATOR, READER = "sonnet", "haiku", "grok"
MT_SYS = "Translate the Korean text into English. Output only the translation."
PILOT = ["F01", "F11", "F21", "F31"]  # 4 of 40 fact lists x 4 conditions = 16 texts (10%)
PAIRS = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]


def src_path(c, fid):
    return R.OUT / "texts" / c / WRITER / f"{fid}.md"


def ctrl_path(c, fid):
    return R.OUT / "answers" / c / WRITER / READER / f"{fid}.json"


def translate(c, fid):
    f = OUT / "translations" / c / f"{fid}.md"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(R.call(TRANSLATOR, src_path(c, fid).read_text(), system=MT_SYS))
    return f.read_text()


def read_mt(job):
    it, c = job
    f = OUT / "answers" / c / f"{it['id']}.json"
    if f.exists():
        return
    text = translate(c, it["id"])
    # same persona key as the phase-1 control answer, so only the translation differs
    ans = R.ask(READER, text, it["questions"], R.persona_for(str(ctrl_path(c, it["id"]))))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"answers": ans, "gold": [q["answer"] for q in it["questions"]]}))


def cmd_read(ids):
    its = [it for it in R.items() if ids is None or it["id"] in ids]
    jobs = [(it, c) for it in its for c in R.CONDITIONS]
    R.pmap(read_mt, jobs, workers=5)  # reader.LIMITS caps the real concurrency (KSTE_LIMIT_*)
    R.log(f"mt answers: {len(jobs)}")
    for c, fid, h in mt_flags():
        R.log(f"check translation {c}/{fid}: hangul ratio {h:.3f}")


def mt_flags():
    return [(p.parent.name, p.stem, h) for p in sorted((OUT / "translations").glob("*/F*.md"))
            if (h := R.hangul_ratio(p.read_text())) >= 0.05]


# ---------- analysis ----------

def acc_per_item(recs):
    return {fid: R.rates([r])["acc"] for fid, r in recs.items()}


def paired(mx, my):
    """mx, my: {fid: value}. Mean of per-fact-list differences x - y with a bootstrap 95% CI."""
    ids = sorted(set(mx) & set(my))
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"items": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def flips(mt, ctrl, its):
    """Questions right on the Korean original but wrong after translation (lost), and the reverse (gained)."""
    out = {"lost": 0, "gained": 0, "lost_by_type": {}, "lost_to_E": 0}
    for fid, rec in mt.items():
        for i, (a, g) in enumerate(zip(rec["answers"], rec["gold"])):
            o = ctrl[fid]["answers"][i] == g
            if o and a != g:
                out["lost"] += 1
                out["lost_to_E"] += a == "E"
                t = its[fid]["questions"][i]["type"]
                out["lost_by_type"][t] = out["lost_by_type"].get(t, 0) + 1
            out["gained"] += (not o) and a == g
    return out


def analyze(mt, ctrl, its, chars=None):
    """mt, ctrl: {cond: {fid: {"answers", "gold"}}}; only fact lists present in both are used."""
    for c in mt:
        assert all(ctrl[c][f]["gold"] == mt[c][f]["gold"] for f in mt[c]), f"gold mismatch in {c}"
        ctrl = {**ctrl, c: {f: ctrl[c][f] for f in mt[c]}}
    summary = {c: {"mt": R.rates(list(mt[c].values())), "original": R.rates(list(ctrl[c].values())),
                   **flips(mt[c], ctrl[c], its), **((chars or {}).get(c, {}))} for c in mt}
    acc = {c: acc_per_item(mt[c]) for c in mt}
    mis = {c: {f: R.rates([r])["misread"] for f, r in mt[c].items()} for c in mt}
    loss = {c: {f: v - acc[c][f] for f, v in acc_per_item(ctrl[c]).items()} for c in mt}
    tests = {}
    for x, y in PAIRS:
        if x in mt and y in mt:
            tests[f"mt acc {x}-{y}"] = paired(acc[x], acc[y])
            tests[f"mt misread {x}-{y}"] = paired(mis[x], mis[y])
            tests[f"loss {x}-{y}"] = paired(loss[x], loss[y])
    for c in mt:
        tests[f"loss {c}"] = paired(loss[c], {f: 0.0 for f in loss[c]})
    base = summary.get("base", {}).get("mt")
    ceiling_broken = bool(base) and (base["acc"] <= 0.95 or base["misread"] >= 0.03)
    return {"summary": summary, "tests": tests, "ceiling_broken": ceiling_broken}


def cmd_analyze():
    its = {it["id"]: it for it in R.items()}
    mt = {c: R.load(OUT, "answers", c) for c in R.CONDITIONS}
    mt = {c: v for c, v in mt.items() if v}
    ctrl = {c: R.load(R.OUT, "answers", c, WRITER, READER) for c in mt}
    chars = {}
    for c in mt:
        ko = [len(src_path(c, f).read_text()) for f in mt[c]]
        en = [len((OUT / "translations" / c / f"{f}.md").read_text()) for f in mt[c]]
        chars[c] = {"ko_chars_mean": round(sum(ko) / len(ko)), "en_chars_mean": round(sum(en) / len(en))}
    rep = analyze(mt, ctrl, its, chars)
    rep["translation_flags"] = [f"{c}/{f}: {h:.3f}" for c, f, h in mt_flags()]
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / "report.json").write_text(out)
    print(out)


def selftest():
    its = {"F01": {"questions": [{"type": "who"}, {"type": "deadline"}]},
           "F02": {"questions": [{"type": "who"}, {"type": "number"}]}}
    rec = lambda *a: {"answers": list(a), "gold": ["A", "B"]}  # noqa: E731
    ctrl = {"base": {"F01": rec("A", "B"), "F02": rec("A", "B")},
            "full": {"F01": rec("A", "B"), "F02": rec("A", "E")}}
    mt = {"base": {"F01": rec("C", "B"), "F02": rec("A", "E")},  # lost: who (misread), number (to E)
          "full": {"F01": rec("A", "B"), "F02": rec("A", "B")}}  # gained: F02 Q2
    rep = analyze(mt, ctrl, its)
    s = rep["summary"]
    assert s["base"]["mt"] == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert s["base"]["lost"] == 2 and s["base"]["lost_to_E"] == 1 and s["base"]["gained"] == 0
    assert s["base"]["lost_by_type"] == {"who": 1, "number": 1}
    assert s["full"]["lost"] == 0 and s["full"]["gained"] == 1
    t = rep["tests"]
    assert t["mt acc full-base"]["diff"] == 0.5  # full 1.0 vs base 0.5, both lists
    assert t["mt misread full-base"]["diff"] == -0.25  # base F01 misread 0.5, F02 0
    assert t["loss base"]["diff"] == 0.5 and t["loss full"]["diff"] == -0.25
    assert t["loss full-base"]["diff"] == -0.75
    assert rep["ceiling_broken"] is True
    hi = {c: {f: rec("A", "B") for f in its} for c in ("base", "full")}
    assert analyze(hi, hi, its)["ceiling_broken"] is False
    # partial run: control is restricted to the fact lists the mt arm has
    part = analyze({"base": {"F01": rec("A", "B")}}, ctrl, its)
    assert part["summary"]["base"]["original"]["n"] == 2 and part["tests"]["loss base"]["items"] == 1
    try:
        analyze({"base": {"F01": {"answers": ["A", "B"], "gold": ["B", "B"]}}}, ctrl, its)
        caught = False
    except AssertionError:
        caught = True
    assert caught, "gold mismatch not caught"
    print("selftest ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"pilot": lambda: cmd_read(set(PILOT)), "run": lambda: cmd_read(None), "analyze": cmd_analyze,
     "selftest": selftest}[cmd]()
