#!/usr/bin/env python3
"""X2-long: long documents with confusable targets. Design and criteria: PREREG.md.

Usage: python3 run.py <gen|verify|write|read|analyze|selftest> [--pilot]
Outputs are cached under out/; a call is skipped when its output file exists.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import reader as R  # noqa: E402

OUT = HERE / "out"
GENRES = [("운영 절차(런북)", "아래 메모로 당직 엔지니어가 따라 할 운영 절차 문서를 써 줘."),
          ("사내 규정 변경 안내", "아래 메모로 전 직원에게 보낼 사내 규정 변경 안내 문서를 써 줘."),
          ("프로젝트 일정 공지", "아래 메모로 프로젝트 참여자 전원에게 보낼 일정 공지 문서를 써 줘."),
          ("장애 회고", "아래 메모로 개발 조직 전체가 읽을 장애 회고 문서를 써 줘.")]
PER_CALL = 4
CONDITIONS = R.CONDITIONS
READERS = ["grok", "haiku", "haiku-600"]
SKIM_CHARS = 600
COMPARISONS = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]
METRICS = [("grok", "acc", False), ("grok", "misread", False), ("grok", "misread", True), ("grok", "acc", True),
           ("haiku-600", "acc", False), ("haiku", "acc", False)]
DEMONSTRATIVE = re.compile(r"해당\s(?!없)")
ENV = ["KSTE_CODEX_HOME", "KSTE_CODEX_AUTH", "KSTE_LIMIT_GROK", "KSTE_LIMIT_CODEX", "KSTE_LIMIT_CLAUDE"]
R._run.__defaults__ = (None, None, 1200)  # ponytail: long texts and 4-list Codex calls outlive the 420 s default

_q = R.ITEM_SCHEMA["properties"]["items"]["items"]["properties"]["questions"]["items"]
Q_SCHEMA = {**_q, "required": _q["required"] + ["pair", "swap"],
            "properties": {**_q["properties"], "pair": {"type": "integer"},
                           "swap": {"type": "string", "enum": ["A", "B", "C", "D", "none"]}}}
GEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["audience", "request", "facts", "pairs", "questions"],
                  "properties": {
                      "audience": {"type": "string"}, "request": {"type": "string"},
                      "facts": {"type": "array", "items": {"type": "string"}},
                      "pairs": {"type": "array", "items": {
                          "type": "object", "additionalProperties": False, "required": ["a", "b", "kind"],
                          "properties": {"a": {"type": "string"}, "b": {"type": "string"},
                                         "kind": {"type": "string",
                                                  "enum": ["target", "date", "exception", "backref"]}}}},
                      "questions": {"type": "array", "items": Q_SCHEMA}}}}}}

GEN_PROMPT = """너는 독해 평가 문항 출제자다. 장르 "{genre}"의 긴 업무 문서 {n}개를 위한 메모와 독해 문항을 만든다. 각 메모는 바쁜 직원이 AI에게 문서를 맡기며 건네는 사실 목록이다.

- audience: 이 문서를 읽을 사람.
- request: AI에게 하는 요청 한 문장. 장르와 독자를 밝힌다. 예: "{example}"
- facts: 35-45개. 실제 직원이 쓰는 짧은 메모 말투(개조식, 조사 생략)로 쓰되, 메모 자체는 오해할 여지가 없게 쓴다. 대상은 늘 이름으로 쓰고 "해당", "이", "위", "그", "앞의" 같은 지시어로 가리키지 않는다. 회사, 사람, 시스템, 서버, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 요일을 붙인다.
- 헷갈리기 쉬운 대상 쌍을 3개 이상 넣는다. 종류를 섞는다: 이름이나 역할이 비슷한 서버·시스템·팀·사람 둘(target), 같은 일의 실행일과 기한처럼 가까운 날짜 둘(date), 본 규칙과 예외 조건(exception), 앞 단계나 앞 절에서 만든 대상을 뒤에서 다시 가리키는 경우(backref, 예: 1단계에서 만든 백업과 4단계에서 만든 백업). 쌍의 두 대상에는 서로 다른 날짜, 수치, 담당자, 조건을 붙이고, 메모의 여러 곳에 흩어 놓는다.
- pairs: 넣은 쌍마다 a와 b(두 대상의 이름)와 kind를 쓴다.
- questions: 10개. 문서를 읽은 독자가 실제로 알아야 하는 것을 묻는다. 각 문항의 정답은 facts만으로 하나로 정해져야 하고, 상식이나 추측으로 맞힐 수 없어야 한다. 보기 A-D 가운데 정답은 하나다.
- 10개 가운데 5개 이상은 헷갈리는 쌍을 구분해야 맞히는 문항이다. 이런 문항은 pair에 pairs의 번호(0부터)를 쓰고, 오답 보기 하나에 쌍의 다른 대상의 값(다른 서버의 날짜, 예외가 아닌 경우의 규칙 등)을 넣는다. swap에는 그 오답 보기의 글자를 쓴다. 쌍과 관계없는 문항은 pair에 -1, swap에 "none"을 쓴다.
- 나머지 오답 보기도 같은 메모의 다른 날짜, 다른 사람, 다른 수치, 다른 의무 강도처럼 헷갈릴 만한 것으로 만든다. 정답 위치를 A-D에 고르게 섞는다.
- 문항의 facts에는 정답 근거가 되는 facts의 번호(0부터)를 쓴다. type은 문항이 묻는 정보의 종류다.
- {n}개 문서는 회사, 업무 영역, 독자가 서로 달라야 한다. 문서마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다."""


def lists(sub):
    return [json.loads(p.read_text()) for p in sorted((OUT / sub).glob("L[0-9]*.json"))]


def pick(its, a):
    return its[:1] if a.pilot else its


def save(f, s):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(s)


def cmd_gen(a):
    def one(gi):
        f = OUT / "gen" / f"batch{gi}.json"
        if not f.exists():
            g, ex = GENRES[gi]
            save(f, R.call("codex", GEN_PROMPT.format(genre=g, example=ex, n=PER_CALL, batch=gi + 1), GEN_SCHEMA))
        return gi, json.loads(f.read_text())["items"]

    for gi, its in R.pmap(one, range(1 if a.pilot else len(GENRES)), workers=2):
        for k, it in enumerate(its[:PER_CALL]):
            it = json.loads(R.fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=f"L{gi * PER_CALL + k + 1:02d}", genre=GENRES[gi][0])
            save(OUT / "items" / f"{it['id']}.json", json.dumps(it, ensure_ascii=False, indent=1))
            R.log(f"{it['id']}: facts {len(it['facts'])}, pairs {len(it['pairs'])}, "
                  f"pair questions {sum(q['pair'] >= 0 for q in it['questions'])}/{len(it['questions'])}")


def prepare(it):
    """Shuffle options with a fixed seed; drop questions whose options collide; normalize pair and swap."""
    out = []
    for i, q in enumerate(it["questions"]):
        if len({q[k] for k in "ABCD"}) < 4:
            continue
        s = R.shuffle_options(q, f"{it['id']}-{i}")
        pair = q["pair"] if 0 <= q["pair"] < len(it["pairs"]) else -1
        swap = q["swap"] if pair >= 0 and q["swap"] in ("A", "B", "C", "D") and q["swap"] != q["answer"] else None
        s["pair"] = pair
        s["swap"] = "ABCD"[[s[k] for k in "ABCD"].index(q[swap])] if swap else "none"
        out.append(s)
    return out


def cmd_verify(a):
    def one(it):
        f = OUT / "verify" / f"{it['id']}.json"
        qs = prepare(it)
        if not f.exists():
            save(f, json.dumps({"answers": R.ask("grok", R.memo(it), qs), "gold": [q["answer"] for q in qs]}))
        ans = json.loads(f.read_text())["answers"]
        keep = [q for q, x in zip(qs, ans) if x == q["answer"]]
        if len(keep) >= 5:
            save(OUT / "verified" / f"{it['id']}.json", json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        return it["id"], len(it["questions"]), len(qs), len(keep), sum(q["pair"] >= 0 for q in keep)

    for lid, n, valid, k, kp in R.pmap(one, pick(lists("items"), a), workers=2):
        R.log(f"{lid}: questions {n}, valid options {valid}, kept {k} (pair questions {kp})"
              + ("" if k >= 5 else " -> list dropped"))


def cmd_write(a):
    def one(job):
        it, c = job
        f = OUT / "texts" / c / f"{it['id']}.md"
        if not f.exists():
            save(f, R.call("sonnet", R.memo(it), system=R.system_for(c)))

    R.pmap(one, [(it, c) for it in pick(lists("verified"), a) for c in CONDITIONS], workers=3)


def skim(text):
    return text[:SKIM_CHARS] + "\n…(바빠서 여기까지만 읽었다)"


def cmd_read(a):
    def one(job):
        it, c, r = job
        f = OUT / "answers" / c / r / f"{it['id']}.json"
        if f.exists():
            return
        text = (OUT / "texts" / c / f"{it['id']}.md").read_text()
        qs = it["questions"]
        ans = R.ask("haiku" if r == "haiku-600" else r, skim(text) if r == "haiku-600" else text, qs,
                    R.persona_for(f"{c}/{r}/{it['id']}"))
        save(f, json.dumps({"answers": ans, "gold": [q["answer"] for q in qs],
                            "pair": [q["pair"] for q in qs], "swap": [q["swap"] for q in qs]}))

    R.pmap(one, [(it, c, r) for it in pick(lists("verified"), a) for c in CONDITIONS for r in READERS], workers=6)


# ---------- analysis ----------

def conf(rec):
    """Restrict a record to the confusable-pair questions."""
    idx = [i for i, p in enumerate(rec["pair"]) if p >= 0]
    return {k: [rec[k][i] for i in idx] for k in ("answers", "gold", "pair", "swap")}


def swap_rate(recs):
    """Share of confusable questions (with a marked swap option) where the reader picked the swapped target."""
    hits = [a == s for r in recs for a, p, s in zip(r["answers"], r["pair"], r["swap"]) if p >= 0 and s != "none"]
    return sum(hits) / len(hits) if hits else None


def per_list(res, c, r, metric, confusable):
    out = {}
    for lid, rec in res.get((c, r), {}).items():
        rec = conf(rec) if confusable else rec
        if rec["gold"]:
            out[lid] = R.rates([rec])[metric]
    return out


def compare(res, x, y, r, metric, confusable):
    mx, my = per_list(res, x, r, metric, confusable), per_list(res, y, r, metric, confusable)
    ids = sorted(set(mx) & set(my))
    if not ids:
        return None
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"lists": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def ceiling_broken(grok):
    return grok["acc"] <= 0.95 or grok["misread"] >= 0.03


def cmd_analyze(a):
    res = {(c, r): {p.stem: json.loads(p.read_text()) for p in sorted((OUT / "answers" / c / r).glob("L*.json"))}
           for c in CONDITIONS for r in READERS}
    summary = {}
    for c in CONDITIONS:
        texts = [(OUT / "texts" / c / f"{lid}.md").read_text() for lid in res[(c, "grok")]]
        row = {}
        for r in READERS:
            recs = list(res[(c, r)].values())
            row[r] = R.rates(recs) if recs else None
            cr = [conf(x) for x in recs if conf(x)["gold"]]
            row[r + " confusable"] = R.rates(cr) if cr else None
            row[r + " swap_rate"] = swap_rate(recs)
        row["texts"] = len(texts)
        row["chars_mean"] = round(sum(map(len, texts)) / len(texts)) if texts else None
        row["haedang_mean"] = round(sum(len(re.findall(r"해당\s", t)) for t in texts) / len(texts), 2) if texts else None
        # added after the main run: "해당 없음" (not applicable) is not a demonstrative
        row["haedang_demonstrative"] = sum(len(DEMONSTRATIVE.findall(t)) for t in texts)
        row["check_needed_texts"] = sum("확인 필요" in t for t in texts)
        summary[c] = row
    tests = {}
    for x, y in COMPARISONS:
        for r, metric, cf in METRICS:
            t = compare(res, x, y, r, metric, cf)
            if t:
                tests[f"{r}{' confusable' if cf else ''} {metric} {x}-{y}"] = t
    base = summary["base"]["grok"]
    rep = {"summary": summary, "tests": tests,
           "ceiling_broken": ceiling_broken(base) if base else None,
           "items": {"generated": len(lists("items")), "verified": len(lists("verified")),
                     "questions": sum(len(it["questions"]) for it in lists("verified")),
                     "pair_questions": sum(q["pair"] >= 0 for it in lists("verified") for q in it["questions"])}}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    save(OUT / "report.json", out)
    print(out)


def selftest():
    assert skim("가" * 700).count("가") == SKIM_CHARS and skim("짧다").startswith("짧다\n")
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "C", "facts": [], "type": "other",
         "pair": 0, "swap": "A"}
    it = {"id": "L99", "pairs": [{"a": "x", "b": "y", "kind": "target"}],
          "questions": [q, {**q, "B": "a"}, {**q, "pair": 5}, {**q, "swap": "C"}]}
    qs = prepare(it)
    assert len(qs) == 3  # colliding options dropped
    assert qs[0][qs[0]["answer"]] == "c" and qs[0][qs[0]["swap"]] == "a" and qs[0]["pair"] == 0
    assert qs[1]["pair"] == -1 and qs[1]["swap"] == "none"  # pair index out of range
    assert qs[2]["pair"] == 0 and qs[2]["swap"] == "none"  # swap equals the answer
    rec = {"answers": ["A", "E", "C", "B"], "gold": ["A", "B", "B", "C"], "pair": [0, 0, -1, 1],
           "swap": ["B", "C", "A", "B"]}
    assert R.rates([conf(rec)]) == {"acc": 1 / 3, "misread": 1 / 3, "abstain": 1 / 3, "n": 3}
    assert swap_rate([rec]) == 1 / 3 and swap_rate([{**rec, "pair": [-1] * 4}]) is None
    ok = {"answers": ["A", "B"], "gold": ["A", "B"], "pair": [0, -1], "swap": ["C", "none"]}
    bad = {"answers": ["C", "B"], "gold": ["A", "B"], "pair": [0, -1], "swap": ["C", "none"]}
    res = {("full", "grok"): {"L01": ok, "L02": ok}, ("base", "grok"): {"L01": bad, "L02": ok, "L03": bad}}
    t = compare(res, "full", "base", "grok", "misread", False)
    assert t["lists"] == 2 and abs(t["diff"] + 0.25) < 1e-9  # L03 has no pair in full
    assert compare(res, "full", "base", "grok", "misread", True)["diff"] == -0.5
    assert compare(res, "full", "clarity", "grok", "acc", False) is None
    assert ceiling_broken({"acc": 0.95, "misread": 0.0}) and ceiling_broken({"acc": 0.99, "misread": 0.03})
    assert not ceiling_broken({"acc": 0.96, "misread": 0.02})
    assert len(DEMONSTRATIVE.findall("해당 서버는 해당 없음, 해당하는 값, 해당 **묶음")) == 2
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "verify", "write", "read", "analyze", "selftest"])
    ap.add_argument("--pilot", action="store_true", help="genre 1 and list L01 only")
    a = ap.parse_args()
    if a.cmd in ("gen", "verify", "write", "read") and not all(os.environ.get(k) for k in ENV):
        sys.exit("set " + ", ".join(ENV) + " as in ../BRIEF.md")
    {"gen": cmd_gen, "verify": cmd_verify, "write": cmd_write, "read": cmd_read, "analyze": cmd_analyze,
     "selftest": lambda _: selftest()}[a.cmd](a)
