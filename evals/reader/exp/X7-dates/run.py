#!/usr/bin/env python3
"""X7-dates: does a scheduled-date vs deadline rule in the short prompt stop writers from picking a side?

Design and pre-registration: PREREG.md.
Usage: python3 run.py <items|filter|write|read|judge|rep-write|rep-read|analyze|all|selftest> [--pilot]
Every model response is cached under out/; a rerun skips calls whose file exists.
The replication arm reads X1's memos, questions, texts and answers by path (../X1-ambiguous/out); it copies nothing.
"""
import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP.parent.parent))
import reader as R  # noqa: E402

OUT = EXP / "out"
X1 = EXP.parent / "X1-ambiguous" / "out"
PER_GENRE = 3
PILOT = ["D01", "D02"]
REP_PILOT = ["M01"]
CONDS = ["base", "short", "short+k15", "short+k15u", "full", "full+u"]
REP_NEW = ["short+k15", "short+k15u", "full+u"]  # base, short, full come from X1
READERS = ["grok", "haiku"]
CATS = ["invent", "keep", "flag", "omit"]
JUDGES = ["codex", "grok"]  # primary first; X1 found Grok too slow to judge 8 texts in one call
JUDGE_SAMPLE = [f"D{i:02d}" for i in range(1, 25, 4)]  # 25% re-judged by Grok
PRIMARY = ("short+k15u", "short")
COMPARE = [PRIMARY, ("short+k15", "short"), ("short+k15u", "short+k15"), ("full+u", "full"),
           ("short+k15u", "full"), ("short", "base")]
FLAG_RE = re.compile(r"확인\s*필요|확인이\s*필요")
E_DUP = re.compile(r"\s*\n?\s*E\.\s*글만으로는 알 수 없다\.?")

# ---------- writer prompts (exact text is in PREREG.md) ----------

K15_LINE = ('14. 날짜와 시각은 그때 하는 일(실행일)인지 그때까지 끝낼 일(기한)인지 구분해서 쓴다. '
            '주어진 글의 "에"와 "까지"를 서로 바꾸지 않고, 실행일과 기한을 "~부터 ~까지" 한 기간으로 묶지 않는다.')
U = '주어진 글이 날짜에 붙은 일을 실행일인지 기한인지 밝히지 않았으면 한쪽으로 정하지 말고 "확인 필요:"로 묻는다.'
FULL_K15_END = '재작성에서는 원문의 "에"와 "까지"를 그대로 둔다.\n\n## 의무 표현'


def system_for(c):
    if c in ("base", "short", "full"):
        return R.system_for(c)
    if c == "short+k15":
        return R.system_for("short") + K15_LINE + "\n"
    if c == "short+k15u":
        return R.system_for("short") + K15_LINE + " " + U + "\n"
    if c == "full+u":
        s = R.system_for("full")
        assert s.count(FULL_K15_END) == 1, "full block changed: K15 end not found once"
        return s.replace(FULL_K15_END, FULL_K15_END.replace("둔다.\n", "둔다. " + U + "\n"))
    raise ValueError(c)


# ---------- items ----------

DATE = r"\d{1,2}/\d{1,2}\([월화수목금토일]\)"
NUM_T = r"\d{1,2}(?::\d{2})?(?:시(?:\s*\d{1,2}분|\s*반)?)?"
TIME = r"(?:\s*(?:오전|오후)?\s*" + NUM_T + r"(?:\s*[~-]\s*" + NUM_T + r")?)?"  # e.g. " 오후 3시", " 10:00-12:00"
GAP_BAD = re.compile(r"까지|부터|마감|기한|당일|예정|이내|목표|데드라인|이전|이후|~|" + DATE + TIME +
                     r"\s*(?:에|전|후|중|내)(?![가-힣])")
ON_OK = re.compile(DATE + TIME + r"\s*에(?![가-힣])")

Q_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["q", "A", "B", "C", "D", "answer", "kind", "ref", "facts"],
    "properties": {"q": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"},
                   "C": {"type": "string"}, "D": {"type": "string"},
                   "answer": {"type": "string", "enum": list("ABCDE")},
                   "kind": {"type": "string", "enum": ["gap", "clear", "other"]},
                   "ref": {"type": "integer"}, "facts": {"type": "array", "items": {"type": "integer"}}}}
ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["audience", "request", "facts", "gaps", "clear", "questions"],
        "properties": {
            "audience": {"type": "string"}, "request": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "string"}},
            "gaps": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["fact", "date", "what"],
                "properties": {"fact": {"type": "integer"}, "date": {"type": "string"}, "what": {"type": "string"}}}},
            "clear": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["fact", "date", "kind"],
                "properties": {"fact": {"type": "integer"}, "date": {"type": "string"},
                               "kind": {"type": "string", "enum": ["on", "by"]}}}},
            "questions": {"type": "array", "items": Q_SCHEMA}}}}}}

ITEM_PROMPT = """너는 독해 평가 문항 출제자다. 장르 "{genre}"의 업무 상황 {n}개를 만든다. 각 상황은 바쁜 직원이 AI에게 글을 맡기며 건네는 메모다. 메모에는 날짜가 5개 있다. 그중 3개는 실제 업무 메모처럼, 그날 하는 일(실행일)인지 그때까지 끝낼 일(기한)인지 밝히지 않는다. 평가는 글쓴이가 이 3개를 한쪽으로 정해서 쓰는지, 그 글을 읽은 독자가 정해진 쪽을 믿는지 본다.

- audience: 이 글을 읽을 사람.
- request: AI에게 하는 요청 한 문장. 장르와 독자를 밝힌다. 날짜의 모호함은 언급하지 않는다. 예: "아래 내용으로 전 직원에게 보낼 사내 메신저 공지를 써 줘."
- facts: 8-12개. 실제 직원이 쓰는 짧은 메모 말투(개조식, 조사 생략)로 쓴다. 회사, 사람, 시스템, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 월/일(요일)로 쓴다. 날짜에 시각을 붙여도 된다.
- 날짜는 아래 5개 항목에만 쓴다. 5개 날짜는 서로 다르다. 다섯 항목은 서로 다른 일이다.
  - 흐린 날짜 3개: 날짜와 일을 붙여 쓰되, 그날 하는 일인지 그때까지 끝낼 일인지 정하지 않는다. 그 항목에는 "에", "까지", "부터", "당일", "마감", "기한", "예정", "이내", "목표", "전", "후", "~"를 쓰지 않는다. 예: "11/20(금) 보고서 제출", "12/4(금) 정산 파일 업로드". 두 해석이 모두 그럴듯해야 하고, 다른 facts 항목으로 정할 수 없어야 한다.
  - 분명한 날짜 2개: 하나는 그날 하는 일을 "~에"로 밝힌다(on). 예: "11/24(화) 10:00에 점검 시작". 다른 하나는 그때까지 끝낼 일을 "~까지"로 밝힌다(by). 예: "11/27(금)까지 신청서 제출".
- 날짜가 없는 facts는 오해할 여지가 없게 쓴다. 다른 종류의 빈칸(행위자 생략, 두 대상을 뭉뚱그린 이름, 흐린 의무 강도, 대상 없는 "처리함")을 넣지 않는다. "미정", "확인 필요", "?", "TBD" 같은 표시를 붙이지 않는다.
- 독자가 행동하는 데 필요한 정보를 고루 담는다: 누가, 무엇을, 어디서, 어떤 조건과 예외에서, 의무 강도, 수치와 단위, 문의처.
- gaps: 흐린 날짜마다 fact(facts 번호, 0부터), date(그 항목의 날짜, facts와 같은 표기), what(무엇이 모호한지 한 문장)을 쓴다. 3개다.
- clear: 분명한 날짜마다 fact, date, kind("on" 또는 "by")를 쓴다. 2개이고, on 하나와 by 하나다.
- questions: 7개. 독자에게는 보기 A-D 뒤에 "E. 글만으로는 알 수 없다"가 자동으로 붙는다. 그래서 문항과 보기에 E 보기를 쓰지 않는다. 독자는 메모가 아니라 메모로 쓴 글을 읽는다. 그래서 문항과 보기에 "메모"라는 말을 쓰지 않는다. 문항의 facts에는 근거가 되는 facts 번호를 쓴다.
  - 흐린 날짜 문항 3개: gaps마다 하나씩 쓴다. kind는 "gap", ref는 gaps 번호(0-2)다. 그 날짜에 독자가 무엇을 언제 해야 하는지 묻는다. answer는 E다. A-D에는 그 날짜를 그날 하는 일로 읽은 보기(예: "11/20(금) 당일에 제출한다"), 그 날짜를 기한으로 읽은 보기(예: "11/20(금)까지 제출을 끝낸다"), 그리고 다른 날짜나 다른 해석의 보기 2개를 넣는다. A-D에 "정해지지 않았다", "알 수 없다" 같은 보기를 넣지 않는다.
  - 분명한 날짜 문항 2개: clear마다 하나씩 쓴다. kind는 "clear", ref는 clear 번호(0-1)다. answer는 그 날짜와 그 종류(그날 한다, 또는 그때까지 끝낸다)를 맞게 쓴 보기(A-D)다. 오답 보기에는 같은 날짜를 반대 종류로 읽은 보기를 하나 꼭 넣고, 나머지는 다른 날짜로 만든다.
  - 날짜가 아닌 문항 2개: kind는 "other", ref는 -1이다. 날짜가 없는 facts(사람, 수치, 조건, 장소, 의무 강도 등)를 묻는다. answer는 A-D 가운데 하나이고, facts만으로 하나로 정해지며, 상식이나 추측으로 맞힐 수 없어야 한다. 오답 보기는 같은 메모의 다른 사람, 수치, 조건처럼 헷갈릴 만한 것으로 만든다.
- {n}개 상황은 회사, 업무 영역, 독자가 서로 달라야 한다. 상황마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다."""


def gap_ok(fact, date):
    return date in fact and not GAP_BAD.search(fact)


def clear_ok(fact, date, kind):
    if date not in fact:
        return False
    return "까지" in fact if kind == "by" else bool(ON_OK.search(fact)) and "까지" not in fact


def problems(it):
    p = []
    facts = it["facts"]
    if not 8 <= len(facts) <= 12:
        p.append(f"facts {len(facts)}")
    if len(it["gaps"]) != 3:
        p.append(f"gaps {len(it['gaps'])}")
    if sorted(c["kind"] for c in it["clear"]) != ["by", "on"]:
        p.append(f"clear {[c['kind'] for c in it['clear']]}")
    refs = it["gaps"] + it["clear"]
    if any(not 0 <= x["fact"] < len(facts) for x in refs):
        return p + ["fact index"]
    if len({x["fact"] for x in refs}) != len(refs) or len({x["date"] for x in refs}) != len(refs):
        p.append("dates or facts not distinct")
    p += [f"gap {i} marked: {facts[g['fact']]}" for i, g in enumerate(it["gaps"]) if not gap_ok(facts[g["fact"]], g["date"])]
    p += [f"clear {i} unmarked: {facts[c['fact']]}" for i, c in enumerate(it["clear"])
          if not clear_ok(facts[c["fact"]], c["date"], c["kind"])]
    used = {x["fact"] for x in refs}
    p += [f"extra date in fact {i}" for i, f in enumerate(facts) if i not in used and re.search(DATE, f)]
    kinds = [q["kind"] for q in it["questions"]]
    if (kinds.count("gap"), kinds.count("clear"), kinds.count("other")) != (3, 2, 2):
        p.append(f"question kinds {kinds}")
    return p


def valid_q(q, it):
    """Keep a question only if its kind, answer and reference fit, and the referenced date passed the marker check."""
    facts = it["facts"]
    if q["kind"] == "gap":
        return (q["answer"] == "E" and 0 <= q["ref"] < len(it["gaps"])
                and gap_ok(facts[it["gaps"][q["ref"]]["fact"]], it["gaps"][q["ref"]]["date"]))
    if q["kind"] == "clear":
        if q["answer"] == "E" or not 0 <= q["ref"] < len(it["clear"]):
            return False
        c = it["clear"][q["ref"]]
        return clear_ok(facts[c["fact"]], c["date"], c["kind"])
    return q["kind"] == "other" and q["answer"] in "ABCD" and q["ref"] == -1


def clean_q(q):
    """Strip a duplicated E option from the stem and options (X1 limitation 4)."""
    return {**q, **{k: E_DUP.sub("", q[k]).strip() for k in ("q", "A", "B", "C", "D")}}


def shuffle(q, key):
    """Shuffle A-D with a fixed seed; E stays E."""
    opts = [q[k] for k in "ABCD"]
    gold = None if q["answer"] == "E" else q[q["answer"]]
    random.Random(key).shuffle(opts)
    return {**q, **dict(zip("ABCD", opts)), "answer": "E" if gold is None else "ABCD"[opts.index(gold)]}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def cached(f, make, tries=3):
    """JSON cache: return f's content, else call make() (which validates and may raise) and store it."""
    if f.exists():
        return json.loads(f.read_text())
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


def need_env():
    missing = [k for k in ("KSTE_CODEX_HOME", "KSTE_CODEX_AUTH", "KSTE_LIMIT_GROK", "KSTE_LIMIT_CODEX",
                           "KSTE_LIMIT_CLAUDE") if not os.environ.get(k)]
    if missing:
        sys.exit(f"set {missing} first (BRIEF.md)")
    if "X7" not in os.environ["KSTE_CODEX_HOME"]:
        sys.exit("KSTE_CODEX_HOME must be this experiment's own folder (BRIEF.md)")


def limit(who):
    return int(os.environ.get(f"KSTE_LIMIT_{'CLAUDE' if who in R.WRITERS else who.upper()}", 2))


def cmd_items(pilot):
    def one(gi):
        raw = cached(OUT / "items" / f"batch{gi}.json",
                     lambda: json.loads(R.call("codex", ITEM_PROMPT.format(genre=R.GENRES[gi], n=PER_GENRE,
                                                                           batch=gi + 1), ITEM_SCHEMA)))
        for k, it in enumerate(raw["items"][:PER_GENRE]):
            it = json.loads(R.fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=f"D{gi * PER_GENRE + k + 1:02d}", genre=R.GENRES[gi])
            (OUT / "items" / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))

    R.pmap(one, [0] if pilot else range(len(R.GENRES)), workers=limit("codex"))


def cmd_filter(pilot):
    flog_f = OUT / "filter-log.json"
    flog = json.loads(flog_f.read_text()) if flog_f.exists() else {}

    def one(f):
        it = json.loads(f.read_text())
        if pilot and it["id"] not in PILOT:
            return
        qs = [shuffle(clean_q(q), f"{it['id']}-{i}") for i, q in enumerate(it["questions"]) if valid_q(q, it)]
        ans = cached(OUT / "filter" / f"{it['id']}.json", lambda: R.ask("grok", R.memo(it), qs))
        keep = [q for q, a in zip(qs, ans) if a == q["answer"]]
        flog[it["id"]] = {"problems": problems(it), "generated": len(it["questions"]), "valid": len(qs),
                          "kept": len(keep), "e_dup_stripped": sum(clean_q(q) != q for q in it["questions"]),
                          "says_memo": sum("메모" in q["q"] + q["A"] + q["B"] + q["C"] + q["D"] for q in keep),
                          **{f"{k}_valid": sum(q["kind"] == k for q in qs) for k in ("gap", "clear", "other")},
                          **{f"{k}_kept": sum(q["kind"] == k for q in keep) for k in ("gap", "clear", "other")}}
        if any(q["kind"] == "gap" for q in keep):
            (OUT / "kept").mkdir(exist_ok=True)
            (OUT / "kept" / f.name).write_text(json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        else:
            log(f"drop memo {it['id']}: no gap question left")

    R.pmap(one, sorted((OUT / "items").glob("D*.json")), workers=limit("grok"))
    flog_f.write_text(json.dumps(flog, ensure_ascii=False, indent=1, sort_keys=True))


def memos(pilot=False):
    its = [json.loads(p.read_text()) for p in sorted((OUT / "kept").glob("D*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT]


# ---------- texts and reading ----------

def text_f(c, w, mid):
    return OUT / "texts" / c / w / f"{mid}.md"


def write_all(jobs, path):
    def one(job):
        it, c, w = job
        f = path(c, w, it["id"])
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(R.call(w, R.memo(it), system=system_for(c)))

    R.pmap(one, jobs, workers=limit("claude"))


def cmd_write(pilot):
    write_all([(it, c, w) for it in memos(pilot) for c in CONDS for w in R.WRITERS], text_f)


def read_all(jobs, read_one):
    """jobs: {reader: [args]}; Grok and Haiku run side by side, each under its own limit."""
    with ThreadPoolExecutor(len(jobs)) as ex:
        for f in [ex.submit(R.pmap, lambda j: read_one(*j), js, limit(r)) for r, js in jobs.items()]:
            f.result()


def read_main(it, c, w, r):
    qs = it["questions"]
    cached(OUT / "answers" / c / w / r / f"{it['id']}.json",
           lambda: {"answers": R.ask(r, text_f(c, w, it["id"]).read_text(), qs,
                                     R.persona_for(f"X7/{c}/{w}/{r}/{it['id']}")),
                    "gold": [q["answer"] for q in qs], "kind": [q["kind"] for q in qs], "ref": [q["ref"] for q in qs]})


def cmd_read(pilot):
    read_all({r: [(it, c, w, r) for it in memos(pilot) for c in CONDS for w in R.WRITERS] for r in READERS}, read_main)


# ---------- replication on X1's deadline_vs_date memos ----------

def rep_memos(pilot=False):
    """X1 kept memos that still have a deadline_vs_date question (read by path, not copied)."""
    out = []
    for p in sorted((X1 / "kept").glob("M*.json")):
        it = json.loads(p.read_text())
        gis = {gi for gi, g in enumerate(it["gaps"]) if g["kind"] == "deadline_vs_date"}
        if any(q["gap"] in gis for q in it["questions"]) and (not pilot or it["id"] in REP_PILOT):
            out.append(it)
    return out


def rep_text_f(c, w, mid):
    return (OUT / "rep" / "texts" if c in REP_NEW else X1 / "texts") / c / w / f"{mid}.md"


def rep_ans_f(c, w, r, mid):
    return (OUT / "rep" / "answers" if c in REP_NEW else X1 / "answers") / c / w / r / f"{mid}.json"


def cmd_rep_write(pilot):
    write_all([(it, c, w) for it in rep_memos(pilot) for c in REP_NEW for w in R.WRITERS], rep_text_f)


def read_rep(it, c, w, r):
    qs = it["questions"]  # X1's kept questions as X1's readers saw them
    cached(rep_ans_f(c, w, r, it["id"]),
           lambda: {"answers": R.ask(r, rep_text_f(c, w, it["id"]).read_text(), qs,
                                     R.persona_for(f"X1/{c}/{w}/{r}/{it['id']}")),
                    "gold": [q["answer"] for q in qs], "gap": [q["gap"] for q in qs]})


def cmd_rep_read(pilot):
    read_all({r: [(it, c, w, r) for it in rep_memos(pilot) for c in REP_NEW for w in R.WRITERS] for r in READERS},
             read_rep)


# ---------- judging ----------

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["texts"],
    "properties": {"texts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "gaps", "extra_flags"],
        "properties": {"id": {"type": "string"},
                       "gaps": {"type": "array", "items": {"type": "string", "enum": CATS}},
                       "extra_flags": {"type": "integer"}}}}}}

JUDGE_PROMPT = """아래 메모로 AI 글쓴이 여러 명이 각각 글을 썼다. 메모에는 그날 하는 일(실행일)인지 그때까지 끝낼 일(기한)인지 밝히지 않은 날짜가 {k}개 있다. 글마다 그 날짜 하나하나를 어떻게 다뤘는지 판정한다.

범주:
- invent: 메모에 없는 해석으로 정했다. 예: 날짜에 붙은 일을 "까지", "마감", "기한", "그 전에"(기한)로 쓰거나, "에", "당일", "예정", "진행", 시작·종료 시각(그날 하는 일)으로 써서 한쪽으로 정했다. 날짜를 바꾼 것도 invent다.
- keep: 메모처럼 날짜와 일만 옮겼고, 실행일인지 기한인지 정하지 않았고, 정해지지 않았다고 표시하지도 않았다.
- flag: 실행일인지 기한인지 정해지지 않았다고 글에 드러냈다. 예: "확인 필요", 요청자에게 묻는 질문, 자리 표시, "추후 안내". 드러내면서 후보를 함께 써도 flag다.
- omit: 그 항목을 글에서 뺐다.

extra_flags: 아래 목록의 날짜와 관계없는 내용에 붙은 표시("확인 필요", 요청자에게 묻는 질문, 자리 표시, "미정")의 수다. 메모가 "에"나 "까지"로 밝힌 날짜에 붙은 표시도 여기에 센다. 목록의 날짜에 붙은 표시는 세지 않는다.

<메모>
{memo}
</메모>

<밝히지 않은 날짜>
{gaps}
</밝히지 않은 날짜>

{texts}

글 {n}편 모두를 판정한다. 출력은 JSON 하나다. 형식: {{"texts": [{{"id": "T1", "gaps": [{example}], "extra_flags": 0}}]}}. gaps에는 목록 번호 순서대로 범주를 하나씩 쓴다."""


def judge_gaps(it):
    """Gaps whose memo line passed the marker check; only these are judged and counted."""
    return [g for g in it["gaps"] if gap_ok(it["facts"][g["fact"]], g["date"])]


def judge_order(mid):
    order = [(c, w) for c in CONDS for w in R.WRITERS]
    random.Random(f"judge-{mid}").shuffle(order)
    return order


def judge_prompt(it, order):
    gs = judge_gaps(it)
    gaps = "\n".join(f"{i}. 메모 항목 \"{it['facts'][g['fact']]}\": {g['what']}" for i, g in enumerate(gs))
    texts = "\n\n".join(f"<글 T{i + 1}>\n{text_f(c, w, it['id']).read_text()}\n</글 T{i + 1}>"
                        for i, (c, w) in enumerate(order))
    return JUDGE_PROMPT.format(k=len(gs), memo=R.memo(it), gaps=gaps, texts=texts, n=len(order),
                               example=", ".join('"keep"' for _ in gs))


def parse_judge(raw, order, k):
    """Map T1..Tn back to (condition, writer); raise unless every text has k valid categories."""
    got = {t["id"].strip(): t for t in R.first_json(raw)["texts"]}
    out = {}
    for i, (c, w) in enumerate(order):
        t = got[f"T{i + 1}"]
        if len(t["gaps"]) != k or any(g not in CATS for g in t["gaps"]) or int(t["extra_flags"]) < 0:
            raise ValueError(f"bad judgment T{i + 1}: {t}")
        out[f"{c}/{w}"] = {"gaps": t["gaps"], "extra_flags": int(t["extra_flags"])}
    return out


def grok_long(prompt, timeout=1200):
    """R.grok with a longer timeout: judging is slower than reading while other experiments share Grok."""
    with R.LIMITS["grok"]:
        return R._run(["grok", "-p", prompt, "-m", R.GROK_MODEL, "--system-prompt-override",
                       "You are a careful reader. Follow the user message only.", "--tools", "", "--no-subagents",
                       "--disable-web-search", "--max-turns", "1", "--output-format", "plain"], timeout=timeout)


def cmd_judge(pilot):
    def one(job):
        it, who = job
        mid, order, k = it["id"], judge_order(it["id"]), len(judge_gaps(it))
        if who == "codex":
            cached(OUT / "judge" / "codex" / f"{mid}.json",
                   lambda: parse_judge(R.call("codex", judge_prompt(it, order), JUDGE_SCHEMA), order, k))
            return
        out = {}
        for i in range(0, len(order), 4):  # 4 texts per Grok call to stay under the timeout
            part = order[i:i + 4]
            out.update(cached(OUT / "judge" / "grok-parts" / f"{mid}-{i // 4}.json",
                              lambda: parse_judge(grok_long(judge_prompt(it, part)), part, k)))
        f = OUT / "judge" / "grok" / f"{mid}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    its = [it for it in memos(pilot) if judge_gaps(it)]
    sample = JUDGE_SAMPLE[:1] if pilot else JUDGE_SAMPLE
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


def pairs(rec, subset):
    """subset: a question kind ("gap", "clear", "other") or "all"."""
    return [(a, g) for a, g, k in zip(rec["answers"], rec["gold"], rec["kind"]) if subset in ("all", k)]


def paired(mx, my):
    ids = sorted(i for i in set(mx) & set(my) if mx[i] is not None and my[i] is not None)
    if not ids:
        return None
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"memos": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def r4(d):
    return None if d is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def load_answers(path, conds, mids):
    """{(c, w, r): {mid: rec}} for the files that exist."""
    out = {}
    for c in conds:
        for w in R.WRITERS:
            for r in READERS:
                out[(c, w, r)] = {m: json.loads(path(c, w, r, m).read_text()) for m in mids if path(c, w, r, m).exists()}
    return out


def per_memo(ans, c, r, mids, select, metric):
    out = {}
    for mid in mids:
        ps = [x for w in R.WRITERS if mid in ans[(c, w, r)] for x in select(ans[(c, w, r)][mid], mid)]
        out[mid] = rates(ps)[metric] if ps else None
    return out


def pooled(ans, c, r, select, ws=R.WRITERS):
    return r4(rates([x for w in ws for mid, rec in ans[(c, w, r)].items() for x in select(rec, mid)]))


def text_stats(texts):
    return {"texts": len(texts), "chars_mean": round(sum(map(len, texts)) / len(texts)) if texts else None,
            "texts_with_kakunin": sum(bool(FLAG_RE.search(t)) for t in texts),
            "kakunin_per_text": round(sum(len(FLAG_RE.findall(t)) for t in texts) / len(texts), 3) if texts else None}


def analyze_main():
    its = {it["id"]: it for it in memos()}
    mids = sorted(its)
    ans = load_answers(lambda c, w, r, m: OUT / "answers" / c / w / r / f"{m}.json", CONDS, mids)
    sel = {s: (lambda s: lambda rec, mid: pairs(rec, s))(s) for s in ("all", "gap", "clear", "other")}

    summary = {}
    for c in CONDS:
        texts = [text_f(c, w, m).read_text() for w in R.WRITERS for m in mids if text_f(c, w, m).exists()]
        summary[c] = {r: {s: pooled(ans, c, r, sel[s]) for s in sel} for r in READERS}
        summary[c]["grok_by_writer"] = {w: {s: pooled(ans, c, "grok", sel[s], [w]) for s in ("gap", "clear", "other")}
                                        for w in R.WRITERS}
        summary[c].update(text_stats(texts))
        summary[c]["system_prompt_chars"] = len(system_for(c)) - len(R.BASE_SYS) - 2 if c != "base" else 0

    judge = {who: {p.stem: json.loads(p.read_text()) for p in sorted((OUT / "judge" / who).glob("D*.json"))}
             for who in JUDGES}
    j1 = judge[JUDGES[0]]

    def extra_per_memo(c):
        return {mid: sum(j[f"{c}/{w}"]["extra_flags"] for w in R.WRITERS) / len(R.WRITERS) for mid, j in j1.items()}

    tests = {}
    for x, y in COMPARE:
        for r in READERS:
            tests[f"{r} gap misread {x} - {y}"] = paired(per_memo(ans, x, r, mids, sel["gap"], "misread"),
                                                         per_memo(ans, y, r, mids, sel["gap"], "misread"))
        for s in ("clear", "other"):
            tests[f"grok {s} acc {x} - {y}"] = paired(per_memo(ans, x, "grok", mids, sel[s], "acc"),
                                                      per_memo(ans, y, "grok", mids, sel[s], "acc"))
        tests[f"judged extra_flags per text {x} - {y}"] = paired(extra_per_memo(x), extra_per_memo(y))

    handling = {}
    for c in CONDS:
        cells = [j[f"{c}/{w}"] for j in j1.values() for w in R.WRITERS]
        cats = [g for cell in cells for g in cell["gaps"]]
        handling[c] = {"texts": len(cells), "gap_cells": len(cats),
                       "dist": {k: round(cats.count(k) / len(cats), 3) for k in CATS} if cats else None,
                       "texts_flagging_a_gap": sum("flag" in cell["gaps"] for cell in cells),
                       "extra_flags_total": sum(cell["extra_flags"] for cell in cells),
                       "extra_flags_per_text": round(sum(cell["extra_flags"] for cell in cells) / len(cells), 3)
                       if cells else None}

    # exploratory (not pre-registered): judged handling of a gap x Grok's answer on that gap's question
    by_cat = {}
    for mid, j in j1.items():
        for key, cell in j.items():
            c, w = key.split("/")
            rec = ans[(c, w, "grok")].get(mid)
            for a, g, k, ref in zip(rec["answers"], rec["gold"], rec["kind"], rec["ref"]) if rec else ():
                if k == "gap" and ref < len(cell["gaps"]):
                    by_cat.setdefault(cell["gaps"][ref], []).append((a, g))
    # exploratory: wrong answers on clear-date and other questions, by kind of wrong answer
    errors = {c: {s: {"E": sum(a == "E" for w in R.WRITERS for rec in ans[(c, w, "grok")].values()
                                for a, g in pairs(rec, s) if a != g),
                      "other_option": sum(a != "E" for w in R.WRITERS for rec in ans[(c, w, "grok")].values()
                                          for a, g in pairs(rec, s) if a != g)} for s in ("clear", "other")}
              for c in CONDS}

    j2 = judge[JUDGES[1]]
    both = sorted(set(j1) & set(j2))
    cat_pairs = [(a, b) for mid in both for key in j1[mid] for a, b in zip(j1[mid][key]["gaps"], j2[mid][key]["gaps"])]
    ext_pairs = [(j1[mid][key]["extra_flags"], j2[mid][key]["extra_flags"]) for mid in both for key in j1[mid]]
    agreement = {"memos": len(both), "gap_cells": len(cat_pairs),
                 "category_agreement": round(sum(a == b for a, b in cat_pairs) / len(cat_pairs), 3) if cat_pairs else None,
                 "flag_agreement": round(sum((a == "flag") == (b == "flag") for a, b in cat_pairs) / len(cat_pairs), 3)
                 if cat_pairs else None,
                 "extra_flags_exact": round(sum(a == b for a, b in ext_pairs) / len(ext_pairs), 3) if ext_pairs else None,
                 "extra_flags_total": [sum(a for a, _ in ext_pairs), sum(b for _, b in ext_pairs)]}

    base = summary["base"]["grok"]["all"]
    p, cl, ot = (tests[f"grok gap misread {PRIMARY[0]} - {PRIMARY[1]}"], tests[f"grok clear acc {PRIMARY[0]} - {PRIMARY[1]}"],
                 tests[f"grok other acc {PRIMARY[0]} - {PRIMARY[1]}"])
    verdict = None
    if p and cl and ot:
        verdict = {"primary_upper_below_0": p["ci95"][1] < 0, "clear_noninferior_3pp": cl["ci95"][0] > -0.03,
                   "other_noninferior_3pp": ot["ci95"][0] > -0.03}
        verdict["adopt"] = all(verdict.values())
    flog = json.loads((OUT / "filter-log.json").read_text())
    return {"memos": len(its), "items_generated": len(list((OUT / "items").glob("D*.json"))), "filter": flog,
            "kept_questions": {k: sum(len([q for q in it["questions"] if q["kind"] == k]) for it in its.values())
                               for k in ("gap", "clear", "other")},
            "ceiling_broken": bool(base and (base["acc"] <= 0.95 or base["misread"] >= 0.03)),
            "verdict": verdict, "summary": summary, "tests": tests, "judge_handling": handling,
            "judge_agreement": agreement,
            "exploratory": {"grok_gap_by_judged_handling": {k: r4(rates(v)) for k, v in sorted(by_cat.items())},
                            "grok_wrong_answers": errors}}


def analyze_rep():
    its = {it["id"]: it for it in rep_memos()}
    mids = sorted(its)
    conds = ["base", "short", "full"] + REP_NEW
    ans = load_answers(rep_ans_f, conds, mids)

    def dl(rec, mid):
        gis = {gi for gi, g in enumerate(its[mid]["gaps"]) if g["kind"] == "deadline_vs_date"}
        return [(a, g) for a, g, gp in zip(rec["answers"], rec["gold"], rec["gap"]) if gp in gis]

    def other_gap(rec, mid):
        gis = {gi for gi, g in enumerate(its[mid]["gaps"]) if g["kind"] == "deadline_vs_date"}
        return [(a, g) for a, g, gp in zip(rec["answers"], rec["gold"], rec["gap"]) if gp >= 0 and gp not in gis]

    def nongap(rec, mid):
        return [(a, g) for a, g, gp in zip(rec["answers"], rec["gold"], rec["gap"]) if gp < 0]

    sel = {"deadline": dl, "other_gap": other_gap, "nongap": nongap}
    summary = {}
    for c in conds:
        texts = [rep_text_f(c, w, m).read_text() for w in R.WRITERS for m in mids if rep_text_f(c, w, m).exists()]
        summary[c] = {r: {s: pooled(ans, c, r, f) for s, f in sel.items()} for r in READERS}
        summary[c].update(text_stats(texts))
    tests = {}
    for x, y in COMPARE:
        for r in READERS:
            tests[f"{r} deadline misread {x} - {y}"] = paired(per_memo(ans, x, r, mids, dl, "misread"),
                                                              per_memo(ans, y, r, mids, dl, "misread"))
        tests[f"grok nongap acc {x} - {y}"] = paired(per_memo(ans, x, "grok", mids, nongap, "acc"),
                                                     per_memo(ans, y, "grok", mids, nongap, "acc"))
        tests[f"grok other_gap misread {x} - {y} (exploratory)"] = paired(
            per_memo(ans, x, "grok", mids, other_gap, "misread"), per_memo(ans, y, "grok", mids, other_gap, "misread"))
    return {"memos": len(mids), "summary": summary, "tests": tests}


def cmd_analyze(_pilot=False):
    rep = {"main": analyze_main() if (OUT / "kept").exists() else None,
           "replication": analyze_rep() if (OUT / "rep" / "answers").exists() else None}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / "report.json").write_text(out)
    print(out)


def selftest():
    assert rates([("E", "E"), ("A", "E"), ("E", "B"), ("C", "C")]) == {
        "acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert rates([]) is None
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "E", "kind": "gap", "ref": 0}
    sq = shuffle(q, "k")
    assert sq["answer"] == "E" and sorted(sq[k] for k in "ABCD") == list("abcd")
    sq = shuffle({**q, "answer": "C", "kind": "other", "ref": -1}, "k")
    assert sq[sq["answer"]] == "c"
    assert clean_q({**q, "A": "그날 반납한다.\nE. 글만으로는 알 수 없다"})["A"] == "그날 반납한다."
    # marker checks on memo lines
    assert gap_ok("11/20(금) 보고서 제출", "11/20(금)") and gap_ok("12/4(금) 14:00 배포 건", "12/4(금)")
    for bad in ("11/20(금)까지 보고서 제출", "11/20(금)에 보고서 제출", "11/20(금) 14:00에 배포", "11/20(금) 마감 보고서",
                "11/20(금) 배포 예정", "11/20(금) 전 제출", "11/16(월)~11/18(수) 수령"):
        assert not gap_ok(bad, bad[:bad.index(")") + 1]), bad
    assert gap_ok("11/20(금) 전사 보고서 제출", "11/20(금)")  # 전사 is a word, not a "before" marker
    assert gap_ok("11/20(금) 오후 3시 보고서 제출", "11/20(금)")  # the 후 in 오후 is not a marker
    assert clear_ok("11/24(화) 오전 10시에 점검", "11/24(화)", "on") and clear_ok("11/24(화) 10:00-12:00에 점검", "11/24(화)", "on")
    assert clear_ok("11/27(금)까지 신청서 제출", "11/27(금)", "by") and not clear_ok("11/27(금) 신청서 제출", "11/27(금)", "by")
    assert clear_ok("11/24(화) 10:00에 점검 시작", "11/24(화)", "on") and clear_ok("11/24(화)에 점검", "11/24(화)", "on")
    assert not clear_ok("11/24(화) 점검 시작", "11/24(화)", "on") and not clear_ok("11/24(화)에서 11/25(수)까지", "11/24(화)", "on")
    it = {"facts": ["11/20(금) 보고서 제출", "12/1(화) 회의록 공유", "12/4(금) 정산 파일 업로드", "11/24(화) 10:00에 점검 시작",
                    "11/27(금)까지 신청서 제출", "문의 총무팀", "대상 전 직원", "수량 1인 1장"],
          "gaps": [{"fact": i, "date": d} for i, d in ((0, "11/20(금)"), (1, "12/1(화)"), (2, "12/4(금)"))],
          "clear": [{"fact": 3, "date": "11/24(화)", "kind": "on"}, {"fact": 4, "date": "11/27(금)", "kind": "by"}],
          "questions": [{"kind": k} for k in ("gap", "gap", "gap", "clear", "clear", "other", "other")]}
    assert problems(it) == [], problems(it)
    bad = {**it, "facts": ["11/20(금)까지 보고서 제출"] + it["facts"][1:]}
    assert problems(bad) == ["gap 0 marked: 11/20(금)까지 보고서 제출"]
    assert valid_q({"kind": "gap", "answer": "E", "ref": 1}, it) and not valid_q({"kind": "gap", "answer": "E", "ref": 0}, bad)
    assert not valid_q({"kind": "gap", "answer": "A", "ref": 1}, it) and not valid_q({"kind": "clear", "answer": "E", "ref": 0}, it)
    assert valid_q({"kind": "clear", "answer": "B", "ref": 1}, it) and valid_q({"kind": "other", "answer": "A", "ref": -1}, it)
    assert judge_gaps(bad) == bad["gaps"][1:]
    # writer prompts: each variant adds exactly its sentence, in the stated place
    s, k, ku, f, fu = (system_for(c) for c in ("short", "short+k15", "short+k15u", "full", "full+u"))
    assert k == s + K15_LINE + "\n" and ku == s + K15_LINE + " " + U + "\n"
    assert fu.replace(" " + U, "") == f and fu.count(U) == 1
    k15 = next(line for line in fu.splitlines() if line.startswith("- K15:"))
    assert k15.endswith(U)
    assert U not in s and "K15" not in s and "실행일" not in s
    # analysis helpers
    rec = {"answers": ["E", "B", "A", "C"], "gold": ["E", "C", "A", "C"], "kind": ["gap", "gap", "clear", "other"]}
    assert pairs(rec, "gap") == [("E", "E"), ("B", "C")] and pairs(rec, "clear") == [("A", "A")]
    assert paired({"D01": 0.5, "D02": None}, {"D01": 0.25, "D02": 0.0}) == {"memos": 1, "diff": 0.25,
                                                                           "ci95": [0.25, 0.25]}
    order = [("base", "sonnet"), ("full+u", "haiku")]
    raw = 'x {"texts": [{"id": "T2", "gaps": ["flag"], "extra_flags": 1}, {"id": "T1", "gaps": ["invent"], "extra_flags": 0}]}'
    assert parse_judge(raw, order, 1) == {"base/sonnet": {"gaps": ["invent"], "extra_flags": 0},
                                          "full+u/haiku": {"gaps": ["flag"], "extra_flags": 1}}
    for bad_raw in ('{"texts": [{"id": "T1", "gaps": ["invent"], "extra_flags": 0}]}',
                    '{"texts": [{"id": "T1", "gaps": ["guess"], "extra_flags": 0}, {"id": "T2", "gaps": ["flag"], "extra_flags": 0}]}'):
        try:
            parse_judge(bad_raw, order, 1)
            raise AssertionError("parse_judge accepted " + bad_raw)
        except (KeyError, ValueError):
            pass
    assert judge_order("D01") == judge_order("D01") and sorted(judge_order("D01")) == sorted(
        (c, w) for c in CONDS for w in R.WRITERS)
    assert JUDGE_SAMPLE == ["D01", "D05", "D09", "D13", "D17", "D21"]
    assert rep_text_f("short", "sonnet", "M01") == X1 / "texts/short/sonnet/M01.md"
    assert rep_ans_f("full+u", "haiku", "grok", "M01") == OUT / "rep/answers/full+u/haiku/grok/M01.json"
    assert len(rep_memos()) == 16 and rep_memos(pilot=True)[0]["id"] == "M01"
    print("selftest ok")


STEPS = {"items": cmd_items, "filter": cmd_filter, "write": cmd_write, "read": cmd_read, "judge": cmd_judge,
         "rep-write": cmd_rep_write, "rep-read": cmd_rep_read, "analyze": cmd_analyze}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=list(STEPS) + ["all", "selftest"])
    ap.add_argument("--pilot", action="store_true", help="genre 0 items; D01-D02 and X1's M01 through the pipeline")
    a = ap.parse_args()
    if a.cmd == "selftest":
        selftest()
        sys.exit()
    if a.cmd != "analyze":
        need_env()
    for step in (list(STEPS) if a.cmd == "all" else [a.cmd]):
        log(f"== {step}")
        STEPS[step](a.pilot)
