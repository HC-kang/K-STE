#!/usr/bin/env python3
"""X3-budget: reading-budget curve and summary relay on the phase-1 Sonnet texts.

Design and pre-registered hypotheses: PREREG.md.
Usage: python3 run.py <selftest|run|analyze> [--items N]
Outputs are cached under out/; a call is skipped when its output file exists.
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for k, v in (("KSTE_LIMIT_GROK", "2"), ("KSTE_LIMIT_CODEX", "2"), ("KSTE_LIMIT_CLAUDE", "3")):
    os.environ.setdefault(k, v)  # BRIEF caps; reader.py reads them at import
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
import reader as R  # noqa: E402

OUT = HERE / "out"
WRITER = "sonnet"
SUFFIX = "\n…(바빠서 여기까지만 읽었다)"  # same marker as phase-1 haiku-skim
ARMS = {"haiku-100": ("haiku", 100), "haiku-500": ("haiku", 500), "haiku-800": ("haiku", 800),
        "grok-250": ("grok", 250), "grok-500": ("grok", 500), "grok-summary": ("grok", "summary")}
REUSED = {"haiku-250": ("haiku-skim", 250), "haiku-full": ("haiku", None), "grok-full": ("grok", None)}
CURVE = ["haiku-100", "haiku-250", "haiku-500", "haiku-800", "haiku-full", "grok-250", "grok-500", "grok-full",
         "grok-summary"]
PRIMARY = ["grok-250", "grok-500", "grok-summary"]
SUM_PROMPT = """아래 글을 팀 채널에 옮길 세 문장 요약으로 써 줘. 요약만 출력한다.

<글>
{text}
</글>"""


def clip(text, n):
    return text if len(text) <= n else text[:n] + SUFFIX


def source(cond, fid):
    return (R.OUT / "texts" / cond / WRITER / f"{fid}.md").read_text()


def summary(cond, fid):
    f = OUT / "summaries" / cond / f"{fid}.md"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(R.call("haiku", SUM_PROMPT.format(text=source(cond, fid))).strip())
    return f.read_text()


def shown(arm, cond, fid):
    budget = ARMS[arm][1]
    return summary(cond, fid) if budget == "summary" else clip(source(cond, fid), budget)


def read(job):
    arm, cond, it = job
    f = OUT / "answers" / arm / cond / f"{it['id']}.json"
    if f.exists():
        return True
    try:
        text = shown(arm, cond, it["id"])
        ans = R.ask(ARMS[arm][0], text, it["questions"], R.persona_for(f"{arm}-{it['id']}"))
    except Exception as e:  # ponytail: log and move on; a rerun fills the gap from cache
        R.log(f"fail {arm} {cond} {it['id']}: {e}")
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"answers": ans, "gold": [q["answer"] for q in it["questions"]], "shown_chars": len(text)}))
    return True


def make_summary(job):
    cond, fid = job
    try:
        summary(cond, fid)
        return True
    except Exception as e:
        R.log(f"fail summary {cond} {fid}: {e}")
        return False


def cmd_run(a):
    its = R.items()[:a.items] if a.items else R.items()
    conds = R.CONDITIONS
    # Claude and Grok have separate caps, so give each its own pool; summaries go first so Grok finds them ready.
    claude_jobs = [(make_summary, (c, it["id"])) for it in its for c in conds]
    claude_jobs += [(read, (arm, c, it)) for arm in ARMS if ARMS[arm][0] == "haiku" for it in its for c in conds]
    grok_jobs = [(read, (arm, c, it)) for arm in ARMS if ARMS[arm][0] == "grok" for it in its for c in conds]
    with ThreadPoolExecutor(2) as ex:
        runs = [ex.submit(R.pmap, lambda j: j[0](j[1]), jobs, n)
                for jobs, n in ((claude_jobs, int(os.environ["KSTE_LIMIT_CLAUDE"])),
                                (grok_jobs, int(os.environ["KSTE_LIMIT_GROK"])))]
        oks = [ok for r in runs for ok in r.result()]
    R.log(f"jobs {len(oks)}, failed {oks.count(False)}")
    if not all(oks):
        sys.exit(1)


# ---------- analysis ----------

def load_arm(arm, cond):
    """{fid: record} for one arm and condition; reused phase-1 arms get shown_chars from the source text."""
    if arm in ARMS:
        return R.load(OUT, "answers", arm, cond)
    sub, budget = REUSED[arm]
    recs = R.load(R.OUT, "answers", cond, WRITER, sub)
    for fid, rec in recs.items():
        rec["shown_chars"] = len(source(cond, fid) if budget is None else clip(source(cond, fid), budget))
    return recs


def compare(res, x, y, metric="acc"):
    """Paired by fact list: mean of per-item metric(x) - metric(y), with bootstrap 95% CI."""
    ids = sorted(set(res[x]) & set(res[y]))
    if not ids:
        return None
    m, lo, hi = R.boot([R.rates([res[x][i]])[metric] - R.rates([res[y][i]])[metric] for i in ids])
    return {"items": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def ceiling_broken(r):
    return r["acc"] <= 0.95 or r["misread"] >= 0.03


def sentences(s):
    # ponytail: counts terminal punctuation; bullets without a period count as zero
    return len(re.findall(r"[.!?。](?=\s|$)", s.strip()))


def by_type(recs, its):
    out = {}
    for fid, rec in recs.items():
        for q, a, g in zip(its[fid]["questions"], rec["answers"], rec["gold"]):
            t = out.setdefault(q["type"], [0, 0])
            t[0] += a == g
            t[1] += 1
    return out


def share_bin(budget, length, bins=5):
    """Bin index of the share of the source text a reader got; share 1.0 falls in the last bin."""
    return min(bins - 1, int(min(1, budget / length) * bins))


def by_share(arms):
    """Exploratory: correct/total and mean share by 20% share-of-text bin, pooled over budget arms."""
    out = {}
    for arm in arms:
        b = (ARMS.get(arm) or REUSED[arm])[1]
        for c in R.CONDITIONS:
            for fid, rec in load_arm(arm, c).items():
                n = len(source(c, fid))
                t = out.setdefault(c, [[0, 0, 0.0] for _ in range(5)])[share_bin(b, n)]
                t[0] += sum(x == g for x, g in zip(rec["answers"], rec["gold"]))
                t[1] += len(rec["gold"])
                t[2] += min(1, b / n) * len(rec["gold"])
    return out


def cmd_analyze(a):
    its = {it["id"]: it for it in R.items()}
    rep = {"arms": {}, "tests": {}, "ceiling": {}, "by_type": {}, "summaries": {},
           "by_share": {"haiku": by_share(["haiku-100", "haiku-250", "haiku-500", "haiku-800"]),
                        "grok": by_share(["grok-250", "grok-500"])}}
    for arm in CURVE:
        res = {c: load_arm(arm, c) for c in R.CONDITIONS}
        b = (ARMS.get(arm) or REUSED[arm])[1]
        rep["arms"][arm] = {c: {**R.rates(list(r.values())), "texts": len(r),
                                "shown_chars_mean": round(sum(x["shown_chars"] for x in r.values()) / len(r)),
                                "clipped": sum(x["shown_chars"] > b for x in r.values()) if isinstance(b, int) else None}
                            for c, r in res.items() if r}
        rep["tests"][arm] = {f"acc {x}-base": compare(res, x, "base") for x in ("full", "short", "clarity")}
        if arm.startswith("grok"):
            rep["tests"][arm]["misread base-full"] = compare(res, "base", "full", "misread")
            if res["base"]:
                rep["ceiling"][arm] = ceiling_broken(R.rates(list(res["base"].values())))
        if arm in PRIMARY:
            rep["by_type"][arm] = {c: by_type(res[c], its) for c in ("base", "full")}
    for c in R.CONDITIONS:
        ss = [p.read_text() for p in sorted((OUT / "summaries" / c).glob("F*.md"))]
        if ss:
            rep["summaries"][c] = {"n": len(ss), "chars_mean": round(sum(map(len, ss)) / len(ss)),
                                   "sentences_mean": round(sum(map(sentences, ss)) / len(ss), 2),
                                   "three_sentences": sum(sentences(s) == 3 for s in ss),
                                   "with_check_needed": sum("확인 필요" in s for s in ss)}
    OUT.mkdir(exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    (OUT / "tables.md").write_text(tables(rep))
    print(tables(rep))


def pct(x):
    return f"{x * 100:.1f}%"


def ci(t):
    return "-" if t is None else f"{t['diff'] * 100:+.1f}%p ({t['ci95'][0] * 100:.1f}%p에서 {t['ci95'][1] * 100:.1f}%p)"


def tables(rep):
    """Markdown tables for RESULTS.md, built from report.json only."""
    L = ["| 팔 | 조건 | 정답률 | 오독률 | 정보 누락률 | 받은 글자 수 | 잘린 글 |", "|---|---|---:|---:|---:|---:|---:|"]
    for arm, cs in rep["arms"].items():
        for c, r in cs.items():
            clipped = "-" if r["clipped"] is None else f"{r['clipped']}/{r['texts']}"
            L.append(f"| {arm} | {c} | {pct(r['acc'])} | {pct(r['misread'])} | {pct(r['abstain'])} | "
                     f"{r['shown_chars_mean']:,}자 | {clipped} |")
    L += ["", "| 팔 | full - base | short - base | clarity - base | 오독률 base - full |", "|---|---|---|---|---|"]
    for arm, t in rep["tests"].items():
        L.append(f"| {arm} | {ci(t['acc full-base'])} | {ci(t['acc short-base'])} | {ci(t['acc clarity-base'])} | "
                 f"{ci(t.get('misread base-full'))} |")
    L += ["", "| 조건 | 요약 수 | 평균 길이 | 평균 문장 수(추정) | 세 문장 요약 | \"확인 필요\" 포함 |", "|---|---:|---:|---:|---:|---:|"]
    for c, s in rep["summaries"].items():
        L.append(f"| {c} | {s['n']} | {s['chars_mean']:,}자 | {s['sentences_mean']} | {s['three_sentences']} | "
                 f"{s['with_check_needed']} |")
    for who, cs in rep["by_share"].items():
        L += ["", f"{who} 예산 팔의 받은 글 비율 구간별 정답 수(탐색)", "",
              "| 조건 | " + " | ".join(f"{i * 20}-{i * 20 + 20}%" for i in range(5)) + " |", "|---|" + "---:|" * 5]
        for c, bs in cs.items():
            L.append(f"| {c} | " + " | ".join(f"{k}/{n} ({pct(k / n)}, 평균 비율 {pct(s / n)})" if n else "-"
                                          for k, n, s in bs) + " |")
    for arm, cs in rep["by_type"].items():
        L += ["", f"{arm} 문항 종류별 정답 수", "", "| 종류 | base | full |", "|---|---:|---:|"]
        for t in sorted(cs["base"]):
            L.append(f"| {t} | {cs['base'][t][0]}/{cs['base'][t][1]} | {cs['full'].get(t, [0, 0])[0]}/"
                     f"{cs['full'].get(t, [0, 0])[1]} |")
    return "\n".join(L) + "\n"


def selftest():
    assert clip("가" * 10, 10) == "가" * 10
    assert clip("가" * 11, 10) == "가" * 10 + SUFFIX
    rec = lambda ans, gold: {"answers": list(ans), "gold": list(gold), "shown_chars": 1}  # noqa: E731
    res = {"base": {"F01": rec("AE", "AB"), "F02": rec("EE", "AB")},
           "full": {"F01": rec("AB", "AB"), "F02": rec("AC", "AB"), "F03": rec("AB", "AB")}}
    c = compare(res, "full", "base")  # F01: 1-.5, F02: .5-0; F03 unpaired, dropped
    assert c["items"] == 2 and c["diff"] == 0.5 and c["ci95"] == [0.5, 0.5]
    m = compare(res, "full", "base", "misread")  # full F02 picked C (misread), base never misread
    assert m["diff"] == 0.25
    assert compare({"base": {}, "full": {}}, "full", "base") is None
    assert ceiling_broken({"acc": 0.95, "misread": 0}) and ceiling_broken({"acc": 0.99, "misread": 0.03})
    assert not ceiling_broken({"acc": 0.951, "misread": 0.029})
    assert sentences("가다. 나다! 다인가? 끝") == 3 and sentences("- 항목\n- 항목") == 0
    its = {"F01": {"questions": [{"type": "when"}, {"type": "who"}]}}
    assert by_type({"F01": rec("AE", "AB")}, its) == {"when": [1, 1], "who": [0, 1]}
    assert [share_bin(b, 1000) for b in (100, 199, 200, 999, 1000, 1500)] == [0, 0, 1, 4, 4, 4]
    assert set(ARMS) | set(REUSED) == set(CURVE) and set(PRIMARY) <= set(ARMS)
    assert ci({"diff": 0.05, "ci95": [-0.01, 0.1]}) == "+5.0%p (-1.0%p에서 10.0%p)" and ci(None) == "-"
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["selftest", "run", "analyze"])
    ap.add_argument("--items", type=int, default=0, help="first N fact lists only (trial run)")
    a = ap.parse_args()
    {"selftest": lambda _: selftest(), "run": cmd_run, "analyze": cmd_analyze}[a.cmd](a)
