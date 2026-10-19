#!/usr/bin/env python3
"""X10-dates-v4: does the v4 date rule cut date misreadings on memos shaped unlike X7's, without new misreadings?

Design and pre-registration: PREREG.md.
Usage: python3 run.py <freeze|items|filter|texts|judge|analyze|all|selftest|power> [--pilot]
Every model response is cached under out/; a rerun skips calls whose file exists.
The regression arm reads X7, X1 and X8 memos, questions, texts and answers by path; it copies nothing.
"""
import argparse
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP.parent.parent))
import reader as R  # noqa: E402

OUT = EXP / "out"
SRC = {"X7": EXP.parent / "X7-dates" / "out", "X1": EXP.parent / "X1-ambiguous" / "out",
       "X8": EXP.parent / "X8-referents" / "out"}
PFX = {"new": "X10", "X7": "X7", "X1": "X1", "X8": "X8"}  # persona keys, in each experiment's own form
FIELDS = {"new": ("kind", "ref", "qid"), "X7": ("kind", "ref"), "X1": ("gap",), "X8": ("kind", "qid")}
V3_COMMIT = "98db878"  # HEAD when v4 was frozen; X1, X7 and X8 wrote short and full with these blocks
PROMPT_SHA = {"short-v3": "ffe3fb4c9b6c2183313716848205c857e2d24a95668326f6a488bbfcc44f1818",
              "full-v3": "dbb1b6fbb548888ad6224aacd7c9edd012863907101f394cac49135a99af2fe4",
              "short-v4": "74ef1680498e8e5b7739f177dc0f0752dcb0961a76ff56871fabe67f57d47b3d",  # v4.1 (PREREG change log)
              "full-v4": "0f11300d1293890f63d6167dcdf1b787f46aa4bb0a04180dac4ac55dd0b3bc24"}  # from freeze (PREREG.md)
PER_GENRE = 3
GAPS_PER_SLOT = [1, 2, 2]  # fuzzy dates in the 1st, 2nd and 3rd memo of a genre
PILOT = {"new": ["V01", "V02"], "X7": ["D01"], "X1": ["M01"], "X8": ["M01"]}
CONDS = ["base", "short-v3", "short-v4", "full-v3", "full-v4"]
NEW = ["short-v4", "full-v4"]  # the only conditions written for the regression memos
OLD = {"short-v3": "short", "full-v3": "full"}  # their names in X1, X7 and X8
REP_CONDS = {"X7": ["base", "short-v3", "short+k15", "short+k15u", "full-v3", "full+u"] + NEW,
             "X1": ["base", "short-v3", "full-v3"] + NEW, "X8": ["base", "short-v3", "full-v3"] + NEW}
X7_JUDGED = ["short-v3", "short+k15u", "short-v4", "full-v3", "full+u", "full-v4"]
READERS = ["grok", "haiku"]
CATS = ["invent", "keep", "flag", "omit"]
CLEAR_CATS = ["keep", "flip", "drop", "flag", "omit"]
MARKERS = {"에": "on", "실시": "on", "시작": "on", "까지": "by", "마감": "by"}
CONTEXTS = ["step", "decision", "notice", "incident", "reschedule"]
JUDGE_SAMPLE = [f"V{i:02d}" for i in range(1, 25, 4)]  # 25% re-judged by Grok
VERDICTS = {"short": ("short-v4", "short-v3"), "full": ("full-v4", "full-v3")}
MARGIN = {"X1": 0.08, "X8": 0.10}  # regression margins (PREREG.md, from `run.py power`)
COMPARE = [("short-v4", "short-v3"), ("full-v4", "full-v3"), ("short-v3", "base"), ("short-v4", "base"),
           ("full-v3", "base"), ("full-v4", "base"), ("short-v4", "full-v4")]
REP_COMPARE = {"X7": [("short-v4", "short-v3"), ("full-v4", "full-v3"), ("short-v4", "short+k15u"),
                      ("full-v4", "full+u")],
               "X1": [("short-v4", "short-v3"), ("full-v4", "full-v3")],
               "X8": [("short-v4", "short-v3"), ("full-v4", "full-v3")]}
FLAG_RE = re.compile(r"확인\s*필요|확인이\s*필요")
HEADER_RE = re.compile(r"^#{1,6}\s", re.M)
BOLD_LINE_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*\s*:?\s*$", re.M)
E_DUP = re.compile(r"\s*\n?\s*E\.\s*글만으로는 알 수 없다\.?")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- writer prompts: frozen blocks ----------

def block(src, c):
    return re.search(rf"<!-- {c}:start -->\n(.*?)<!-- {c}:end -->", src, re.S).group(1)


def v3_source():
    return subprocess.run(["git", "-C", str(R.REPO), "show", f"{V3_COMMIT}:prompts/system-prompt.md"],
                          capture_output=True, text=True, check=True).stdout


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def block_file(c):
    return OUT / "prompts" / f"{c}.txt"


def cmd_freeze(_pilot=False):
    """Copy the four blocks into out/prompts once: v3 from V3_COMMIT, v4 from the working tree at freeze time."""
    v3, v4 = v3_source(), (R.REPO / "prompts/system-prompt.md").read_text()
    for c, src in (("short-v3", v3), ("full-v3", v3), ("short-v4", v4), ("full-v4", v4)):
        f = block_file(c)
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(block(src, c.split("-")[0]))
        print(c, len(f.read_text()), sha(f.read_text()))


def system_for(c):
    if c == "base":
        return R.BASE_SYS
    b = block_file(c).read_text()
    assert sha(b) == PROMPT_SHA[c], f"{c} block differs from the frozen one"
    return R.BASE_SYS + "\n\n" + b


# ---------- items ----------

DATE = r"\d{1,2}/\d{1,2}\([월화수목금토일]\)"
NUM_T = r"\d{1,2}(?::\d{2})?(?:시(?:\s*\d{1,2}분|\s*반)?)?"
TIME = r"(?:\s*(?:오전|오후)?\s*" + NUM_T + r"(?:\s*[~-]\s*" + NUM_T + r")?)?"  # e.g. " 오후 3시", " 10:00-12:00"
GAP_BAD = re.compile(r"까지|부터|마감|기한|당일|예정|이내|목표|데드라인|이전|이후|실시|시작|개시|진행|완료|종료|~|"
                     + DATE + TIME + r"\s*(?:에|전|후|중|내)(?![가-힣])")
ON_AT = re.compile(DATE + TIME + r"\s*에(?![가-힣])")

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
                "type": "object", "additionalProperties": False, "required": ["fact", "date", "context", "what"],
                "properties": {"fact": {"type": "integer"}, "date": {"type": "string"},
                               "context": {"type": "string", "enum": CONTEXTS}, "what": {"type": "string"}}}},
            "clear": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["fact", "date", "kind", "marker"],
                "properties": {"fact": {"type": "integer"}, "date": {"type": "string"},
                               "kind": {"type": "string", "enum": ["on", "by"]},
                               "marker": {"type": "string", "enum": list(MARKERS)}}}},
            "questions": {"type": "array", "items": Q_SCHEMA}}}}}}

ITEM_PROMPT = """너는 독해 평가 문항 출제자다. 장르 "{genre}"의 업무 상황 3개를 만든다. 각 상황은 바쁜 직원이 AI에게 글을 맡기며 건네는 메모다. 평가는 두 가지를 본다. 첫째, 메모가 그날 하는 일(실행일)인지 그때까지 끝낼 일(기한)인지 밝히지 않은 날짜를 글쓴이가 한쪽으로 정해서 쓰는지, 그 글을 읽은 독자가 정해진 쪽을 믿는지 본다. 둘째, 메모가 밝힌 날짜를 글쓴이가 그대로 옮기는지 본다.

- audience: 이 글을 읽을 사람.
- request: AI에게 하는 요청 한 문장. 장르와 독자를 밝힌다. 날짜의 모호함은 언급하지 않는다. 예: "아래 내용으로 전 직원에게 보낼 사내 메신저 공지를 써 줘."
- facts: 10-14개. 실제 직원이 쓰는 짧은 메모 말투(개조식, 조사 생략)로 쓴다. 회사, 사람, 시스템, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 월/일(요일)로 쓴다. 날짜에 시각을 붙여도 된다.
- 날짜는 아래의 흐린 날짜 항목과 분명한 날짜 항목에만 쓴다. 날짜는 모두 서로 다르고, 날짜가 있는 항목은 서로 다른 일이다. 날짜가 있는 항목을 날짜순으로 모으지 말고 facts 전체에 흩어 놓는다. 흐린 날짜 항목끼리는 바로 이어 쓰지 않는다.
- 흐린 날짜: 상황 1에는 1개, 상황 2와 상황 3에는 2개씩 넣는다. 날짜와 일을 붙여 쓰되, 그날 하는 일인지 그때까지 끝낼 일인지 정하지 않는다. 두 해석이 모두 그럴듯해야 하고, 다른 facts 항목으로 정할 수 없어야 한다. 그 항목에는 "에", "까지", "부터", "당일", "마감", "기한", "예정", "이내", "목표", "실시", "시작", "진행", "완료", "전", "후", "~"를 쓰지 않는다.
  - context는 흐린 날짜가 붙은 일의 종류다. "step"은 담당자나 독자가 하는 절차의 한 단계다(예: "12/2(수) 부서별 오류 건수 제출"). "decision"은 결정이나 확정이다(예: "요금 개편안 11/27(금) 확정"). "notice"는 공지나 안내의 발송과 게시다(예: "12/1(화) 고객 안내문 발송"). "incident"는 장애나 사고의 보고와 후속 보고다(예: "원인 분석 보고서 11/30(월) 공유"). "reschedule"은 일정 변경과 그에 따른 회신이나 조정이다(예: "변경된 워크숍 장소 회신 11/25(수)").
  - 상황 1의 흐린 날짜는 step이 아니다. 상황 2와 상황 3에서는 흐린 날짜 하나가 step이고, 다른 하나는 step이 아니다. step이 아닌 흐린 날짜 3개는 decision, notice, incident, reschedule 가운데 서로 다른 종류로 쓴다.
- 분명한 날짜: 상황마다 4개다. 실행일 2개와 기한 2개이고, 아래 네 표현(marker)을 하나씩 쓴다.
  - "에"(실행일): 날짜(와 시각) 바로 뒤에 "에"를 쓴다. 예: "11/24(화) 10:00에 서버 점검".
  - "실시" 또는 "시작"(실행일): 날짜 뒤에 "에"를 쓰지 않고 "실시"나 "시작"으로 밝힌다. 예: "11/26(목) 소방 훈련 실시", "12/3(목) 14:00 교육 시작".
  - "까지"(기한): "까지"로 밝힌다. 예: "11/27(금)까지 신청서 제출".
  - "마감"(기한): "까지"를 쓰지 않고 "마감"으로 밝힌다. 예: "참가 신청 12/4(금) 마감".
- 날짜가 없는 facts는 오해할 여지가 없게 쓴다. 다른 종류의 빈칸(행위자 생략, 두 대상을 뭉뚱그린 이름, 흐린 의무 강도, 대상 없는 "처리함", 한 사람이나 대상을 두 이름으로 부르기)을 넣지 않는다. "미정", "확인 필요", "?", "TBD" 같은 표시를 붙이지 않는다.
- 독자가 행동하는 데 필요한 정보를 고루 담는다: 누가, 무엇을, 어디서, 어떤 조건과 예외에서, 의무 강도, 수치와 단위, 문의처.
- gaps: 흐린 날짜마다 fact(facts 번호, 0부터), date(그 항목의 날짜, facts와 같은 표기), context, what(두 해석이 무엇인지 한 문장)을 쓴다.
- clear: 분명한 날짜마다 fact, date, kind(실행일은 "on", 기한은 "by"), marker("에", "실시", "시작", "까지", "마감" 가운데 그 항목에 쓴 표현)를 쓴다. 4개다.
- questions: 독자에게는 보기 A-D 뒤에 "E. 글만으로는 알 수 없다"가 자동으로 붙는다. 그래서 문항과 보기에 E 보기를 쓰지 않는다. 독자는 메모가 아니라 메모로 쓴 글을 읽는다. 그래서 문항과 보기에 "메모"라는 말을 쓰지 않는다. 문항의 facts에는 근거가 되는 facts 번호를 쓴다.
  - 흐린 날짜 문항: gaps마다 하나씩 쓴다. kind는 "gap", ref는 gaps 번호(0부터)다. 그 날짜에 독자가 무엇을 언제 해야 하는지, 또는 무엇이 언제 일어나는지 묻는다. answer는 E다. A-D에는 그 날짜를 그날 하는 일로 읽은 보기(예: "11/20(금) 당일에 제출한다"), 그 날짜를 기한으로 읽은 보기(예: "11/20(금)까지 제출을 끝낸다"), 그리고 다른 날짜나 다른 해석의 보기 2개를 넣는다. A-D에 "정해지지 않았다", "알 수 없다" 같은 보기를 넣지 않는다.
  - 분명한 날짜 문항 4개: clear마다 하나씩 쓴다. kind는 "clear", ref는 clear 번호(0-3)다. answer는 그 날짜와 그 종류(그날 한다, 또는 그때까지 끝낸다)를 맞게 쓴 보기(A-D)다. 오답 보기에는 같은 날짜를 반대 종류로 읽은 보기를 하나 꼭 넣고, 나머지는 다른 날짜로 만든다.
  - 날짜가 아닌 문항 4개: kind는 "other", ref는 -1이다. 날짜가 없는 facts(사람, 수치, 조건, 장소, 의무 강도 등)를 묻는다. answer는 A-D 가운데 하나이고, facts만으로 하나로 정해지며, 상식이나 추측으로 맞힐 수 없어야 한다. 오답 보기는 같은 메모의 다른 사람, 수치, 조건처럼 헷갈릴 만한 것으로 만든다.
- 3개 상황은 회사, 업무 영역, 독자가 서로 달라야 한다. 상황마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다."""


def gap_ok(fact, date):
    return date in fact and not GAP_BAD.search(fact)


def clear_ok(fact, date, kind, marker):
    if date not in fact or MARKERS.get(marker) != kind:
        return False
    at, by, dl = bool(ON_AT.search(fact)), "까지" in fact, "마감" in fact
    return {"에": at and not (by or dl), "실시": "실시" in fact and not (at or by or dl),
            "시작": "시작" in fact and not (at or by or dl), "까지": by and not dl, "마감": dl and not by}[marker]


def calendar_ok(date):
    m = re.match(r"(\d{1,2})/(\d{1,2})\(([월화수목금토일])\)", date)  # a time may follow the date
    try:
        return bool(m) and "월화수목금토일"[datetime.date(2026, int(m[1]), int(m[2])).weekday()] == m[3]
    except ValueError:
        return False


def problems(it, slot):
    """Format checks of one memo; logged in out/filter-log.json. Only gap_ok and clear_ok drop questions."""
    p, facts = [], it["facts"]
    if not 10 <= len(facts) <= 14:
        p.append(f"facts {len(facts)}")
    if len(it["gaps"]) != GAPS_PER_SLOT[slot]:
        p.append(f"gaps {len(it['gaps'])}")
    ctx = [g["context"] for g in it["gaps"]]
    if ctx.count("step") != (0 if slot == 0 else 1):
        p.append(f"contexts {ctx}")
    marks = sorted("실시" if c["marker"] == "시작" else c["marker"] for c in it["clear"])
    if marks != sorted(["에", "실시", "까지", "마감"]):
        p.append(f"markers {[c['marker'] for c in it['clear']]}")
    refs = it["gaps"] + it["clear"]
    if any(not 0 <= x["fact"] < len(facts) for x in refs):
        return p + ["fact index"]
    if len({x["fact"] for x in refs}) != len(refs) or len({x["date"] for x in refs}) != len(refs):
        p.append("dates or facts not distinct")
    p += [f"bad date {x['date']}" for x in refs if not calendar_ok(x["date"])]
    p += [f"gap {i} marked: {facts[g['fact']]}" for i, g in enumerate(it["gaps"]) if not gap_ok(facts[g["fact"]], g["date"])]
    p += [f"clear {i} ({c['marker']}) unmarked: {facts[c['fact']]}" for i, c in enumerate(it["clear"])
          if not clear_ok(facts[c["fact"]], c["date"], c["kind"], c["marker"])]
    gf = sorted(g["fact"] for g in it["gaps"])
    if any(b - a == 1 for a, b in zip(gf, gf[1:])):
        p.append("adjacent gaps")
    used = {x["fact"] for x in refs}
    p += [f"extra date in fact {i}" for i, f in enumerate(facts) if i not in used and re.search(DATE, f)]
    kinds = [q["kind"] for q in it["questions"]]
    if (kinds.count("gap"), kinds.count("clear"), kinds.count("other")) != (len(it["gaps"]), 4, 4):
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
        return clear_ok(facts[c["fact"]], c["date"], c["kind"], c["marker"])
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
    if "X10" not in os.environ["KSTE_CODEX_HOME"]:
        sys.exit("KSTE_CODEX_HOME must be this experiment's own folder (BRIEF.md)")


def limit(who):
    return int(os.environ.get(f"KSTE_LIMIT_{'CLAUDE' if who in R.WRITERS else who.upper()}", 2))


def cmd_items(pilot):
    def one(gi):
        raw = cached(OUT / "items" / f"batch{gi}.json",
                     lambda: json.loads(R.call("codex", ITEM_PROMPT.format(genre=R.GENRES[gi], batch=gi + 1),
                                               ITEM_SCHEMA)))
        assert len(raw["items"]) >= PER_GENRE, f"batch {gi}: {len(raw['items'])} items"
        for k, it in enumerate(raw["items"][:PER_GENRE]):
            it = json.loads(R.fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=f"V{gi * PER_GENRE + k + 1:02d}", genre=R.GENRES[gi], slot=k)
            (OUT / "items" / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))

    R.pmap(one, [0] if pilot else range(len(R.GENRES)), workers=limit("codex"))


def filter_keep(qs, ans):
    """Grok must pick every kept answer; Haiku must too, except on gap questions (PREREG change log, pilot).
    Haiku's memo answer stays on each kept question for the sensitivity analysis."""
    return [{**q, "haiku_memo": ans["haiku"][i]} for i, q in enumerate(qs)
            if ans["grok"][i] == q["answer"] and (q["kind"] == "gap" or ans["haiku"][i] == q["answer"])]


def cmd_filter(pilot):
    """Grok and Haiku read the memo itself; filter_keep decides which questions survive."""
    flog_f = OUT / "filter-log.json"
    flog = json.loads(flog_f.read_text()) if flog_f.exists() else {}

    def one(f):
        it = json.loads(f.read_text())
        if pilot and it["id"] not in PILOT["new"]:
            return
        qs = [{**shuffle(clean_q(q), f"{it['id']}-{i}"), "qid": f"{it['id']}-q{i}"}
              for i, q in enumerate(it["questions"]) if valid_q(q, it)]
        ans = {r: cached(OUT / "filter" / r / f"{it['id']}.json", lambda r=r: R.ask(r, R.memo(it), qs)) for r in READERS}
        keep = filter_keep(qs, ans)
        flog[it["id"]] = {"problems": problems(it, it["slot"]), "generated": len(it["questions"]), "valid": len(qs),
                          "kept": len(keep), "e_dup_stripped": sum(clean_q(q) != q for q in it["questions"]),
                          "gap_kept_haiku_not_e": sum(q["kind"] == "gap" and q["haiku_memo"] != "E" for q in keep),
                          "says_memo": sum("메모" in q["q"] + q["A"] + q["B"] + q["C"] + q["D"] for q in keep),
                          "dropped_by": {r: [q["qid"] + " " + q["kind"] for q, a in zip(qs, ans[r]) if a != q["answer"]]
                                         for r in READERS},
                          **{f"{k}_valid": sum(q["kind"] == k for q in qs) for k in ("gap", "clear", "other")},
                          **{f"{k}_kept": sum(q["kind"] == k for q in keep) for k in ("gap", "clear", "other")}}
        if any(q["kind"] == "gap" for q in keep):
            (OUT / "kept").mkdir(exist_ok=True)
            (OUT / "kept" / f.name).write_text(json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        else:
            log(f"drop memo {it['id']}: no gap question left")

    R.pmap(one, sorted((OUT / "items").glob("V*.json")), workers=limit("grok"))
    flog_f.write_text(json.dumps(flog, ensure_ascii=False, indent=1, sort_keys=True))


def memos(s, pilot=False):
    d = OUT / "kept" if s == "new" else SRC[s] / "kept"
    its = [json.loads(p.read_text()) for p in sorted(d.glob("[VDM][0-9]*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT[s]]


# ---------- texts and reading ----------

def text_f(s, c, w, mid):
    if s == "new":
        return OUT / "texts" / c / w / f"{mid}.md"
    if c in NEW:
        return OUT / "rep" / s / "texts" / c / w / f"{mid}.md"
    return SRC[s] / "texts" / OLD.get(c, c) / w / f"{mid}.md"


def ans_f(s, c, w, r, mid):
    if s == "new":
        return OUT / "answers" / c / w / r / f"{mid}.json"
    if c in NEW:
        return OUT / "rep" / s / "answers" / c / w / r / f"{mid}.json"
    return SRC[s] / "answers" / OLD.get(c, c) / w / r / f"{mid}.json"


def text_job(job):
    """Write one text, then let Haiku and Grok read it. Each provider's limit is R.LIMITS, so many jobs can wait."""
    s, it, c, w = job
    f, qs = text_f(s, c, w, it["id"]), it["questions"]
    once(f, lambda: R.call(w, R.memo(it), system=system_for(c)))
    for r in ("haiku", "grok"):
        cached(ans_f(s, c, w, r, it["id"]),
               lambda r=r: {"answers": R.ask(r, f.read_text(), qs, R.persona_for(f"{PFX[s]}/{c}/{w}/{r}/{it['id']}")),
                            "gold": [q["answer"] for q in qs], **{k: [q[k] for q in qs] for k in FIELDS[s]}})


def cmd_texts(pilot):
    jobs = ([("new", it, c, w) for it in memos("new", pilot) for c in CONDS for w in R.WRITERS] +
            [(s, it, c, w) for s in ("X7", "X1", "X8") for it in memos(s, pilot) for c in NEW for w in R.WRITERS])
    log(f"text jobs: {len(jobs)}")
    R.pmap(text_job, jobs, workers=96)


# ---------- judging ----------

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["texts"],
    "properties": {"texts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "gaps", "clear", "extra_flags"],
        "properties": {"id": {"type": "string"},
                       "gaps": {"type": "array", "items": {"type": "string", "enum": CATS}},
                       "clear": {"type": "array", "items": {"type": "string", "enum": CLEAR_CATS}},
                       "extra_flags": {"type": "integer"}}}}}}

JUDGE_PROMPT = """아래 메모로 AI 글쓴이 여러 명이 각각 글을 썼다. 메모에는 그날 하는 일(실행일)인지 그때까지 끝낼 일(기한)인지 밝히지 않은 날짜 {k}개와, 메모가 밝힌 날짜 {m}개가 있다. 글마다 그 날짜 하나하나를 어떻게 다뤘는지 판정한다.

밝히지 않은 날짜의 범주(gaps):
- invent: 메모에 없는 해석으로 정했다. 예: 날짜에 붙은 일을 "까지", "마감", "기한", "그 전에"(기한)로 쓰거나, "에", "당일", "예정", "진행", 시작·종료 시각(그날 하는 일)으로 써서 한쪽으로 정했다. 날짜를 바꾼 것도 invent다.
- keep: 메모처럼 날짜와 일만 옮겼고, 실행일인지 기한인지 정하지 않았고, 정해지지 않았다고 표시하지도 않았다.
- flag: 실행일인지 기한인지 정해지지 않았다고 글에 드러냈다. 예: "확인 필요", 요청자에게 묻는 질문, 자리 표시, "추후 안내". 드러내면서 후보를 함께 써도 flag다.
- omit: 그 항목을 글에서 뺐다.

밝힌 날짜의 범주(clear):
- keep: 메모와 같은 종류(그날 하는 일, 또는 그때까지 끝낼 일)로 썼다. 표현은 바꿔도 된다. 예: "마감"을 "까지"로, "실시"를 "에"로 썼다.
- flip: 반대 종류로 썼다. 날짜를 바꾼 것도 flip이다.
- drop: 날짜와 일은 옮겼지만 어느 종류인지 드러나지 않게 썼다. 예: "까지"를 지우고 "11/6(금) | 입력"으로 썼다.
- flag: 그 날짜가 실행일인지 기한인지, 또는 그 날짜가 확정인지를 "확인 필요"나 요청자에게 묻는 질문으로 물었다. 같은 종류로 쓰면서 물어도 flag다.
- omit: 그 항목을 글에서 뺐다.

extra_flags: 밝히지 않은 날짜 목록과 관계없는 내용에 붙은 표시("확인 필요", 요청자에게 묻는 질문, 자리 표시, "미정")의 수다. 밝힌 날짜에 붙은 표시도 여기에 센다. 밝히지 않은 날짜에 붙은 표시는 세지 않는다.

<메모>
{memo}
</메모>

<밝히지 않은 날짜>
{gaps}
</밝히지 않은 날짜>

<밝힌 날짜>
{clears}
</밝힌 날짜>

{texts}

글 {n}편 모두를 판정한다. 출력은 JSON 하나다. 형식: {{"texts": [{{"id": "T1", "gaps": [{gex}], "clear": [{cex}], "extra_flags": 0}}]}}. gaps와 clear에는 목록 번호 순서대로 범주를 하나씩 쓴다."""


def judge_items(s, it):
    """Dates the judge sees. X7's lines passed X7's own marker checks (X7 RESULTS), so X7 uses all of them."""
    if s == "X7":
        return it["gaps"], it["clear"]
    f = it["facts"]
    return ([g for g in it["gaps"] if gap_ok(f[g["fact"]], g["date"])],
            [c for c in it["clear"] if clear_ok(f[c["fact"]], c["date"], c["kind"], c["marker"])])


def judge_order(s, mid):
    order = [(c, w) for c in (CONDS if s == "new" else X7_JUDGED) for w in R.WRITERS]
    random.Random(f"judge-{s}-{mid}").shuffle(order)
    return order


def judge_prompt(s, it, order):
    gs, cs = judge_items(s, it)
    gaps = "\n".join(f"{i}. 메모 항목 \"{it['facts'][g['fact']]}\": {g['what']}" for i, g in enumerate(gs))
    clears = "\n".join(f"{i}. 메모 항목 \"{it['facts'][c['fact']]}\": "
                       f"{'그날 하는 일' if c['kind'] == 'on' else '그때까지 끝낼 일'}" for i, c in enumerate(cs))
    texts = "\n\n".join(f"<글 T{i + 1}>\n{text_f(s, c, w, it['id']).read_text()}\n</글 T{i + 1}>"
                        for i, (c, w) in enumerate(order))
    return JUDGE_PROMPT.format(k=len(gs), m=len(cs), memo=R.memo(it), gaps=gaps, clears=clears, texts=texts,
                               n=len(order), gex=", ".join('"keep"' for _ in gs), cex=", ".join('"keep"' for _ in cs))


def parse_judge(raw, order, k, m):
    """Map T1..Tn back to (condition, writer); raise unless every text has k gap and m clear categories."""
    got = {t["id"].strip(): t for t in R.first_json(raw)["texts"]}
    out = {}
    for i, (c, w) in enumerate(order):
        t = got[f"T{i + 1}"]
        if (len(t["gaps"]) != k or len(t["clear"]) != m or any(g not in CATS for g in t["gaps"])
                or any(g not in CLEAR_CATS for g in t["clear"]) or int(t["extra_flags"]) < 0):
            raise ValueError(f"bad judgment T{i + 1}: {t}")
        out[f"{c}/{w}"] = {"gaps": t["gaps"], "clear": t["clear"], "extra_flags": int(t["extra_flags"])}
    return out


def grok_long(prompt, timeout=1200):
    """R.grok with a longer timeout: judging is slower than reading while other experiments share Grok."""
    with R.LIMITS["grok"]:
        return R._run(["grok", "-p", prompt, "-m", R.GROK_MODEL, "--system-prompt-override",
                       "You are a careful reader. Follow the user message only.", "--tools", "", "--no-subagents",
                       "--disable-web-search", "--max-turns", "1", "--output-format", "plain"], timeout=timeout)


def cmd_judge(pilot):
    def one(job):
        s, it, who = job
        mid, order = it["id"], judge_order(s, it["id"])
        k, m = (len(x) for x in judge_items(s, it))
        if who == "codex":
            cached(OUT / "judge" / s / "codex" / f"{mid}.json",
                   lambda: parse_judge(R.call("codex", judge_prompt(s, it, order), JUDGE_SCHEMA), order, k, m))
            return
        out = {}
        for i in range(0, len(order), 4):  # 4 texts per Grok call to stay under the timeout
            part = order[i:i + 4]
            out.update(cached(OUT / "judge" / s / "grok-parts" / f"{mid}-{i // 4}.json",
                              lambda: parse_judge(grok_long(judge_prompt(s, it, part)), part, k, m)))
        f = OUT / "judge" / s / "grok" / f"{mid}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1))

    new, x7 = memos("new", pilot), memos("X7", pilot)
    sample = [it["id"] for it in new][:1] if pilot else JUDGE_SAMPLE  # pilot: the first kept memo
    jobs = ([("new", it, "codex") for it in new] + [("X7", it, "codex") for it in x7] +
            [("new", it, "grok") for it in new if it["id"] in sample])
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


def paired(mx, my):
    ids = sorted(i for i in set(mx) & set(my) if mx[i] is not None and my[i] is not None)
    if not ids:
        return None
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"memos": len(ids), "diff": round(m, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def r4(d):
    return None if d is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def load_answers(s, conds, mids):
    """{(c, w, r): {mid: rec}} for the files that exist."""
    return {(c, w, r): {m: json.loads(ans_f(s, c, w, r, m).read_text()) for m in mids if ans_f(s, c, w, r, m).exists()}
            for c in conds for w in R.WRITERS for r in READERS}


def per_memo(ans, c, r, mids, select, metric):
    out = {}
    for mid in mids:
        ps = [x for w in R.WRITERS if mid in ans[(c, w, r)] for x in select(ans[(c, w, r)][mid], mid)]
        out[mid] = rates(ps)[metric] if ps else None
    return out


def pooled(ans, c, r, select, ws=R.WRITERS):
    return r4(rates([x for w in ws for mid, rec in ans[(c, w, r)].items() for x in select(rec, mid)]))


def text_stats(texts):
    n = len(texts)
    if not n:
        return {"texts": 0}
    return {"texts": n, "chars_mean": round(sum(map(len, texts)) / n),
            "texts_with_kakunin": sum(bool(FLAG_RE.search(t)) for t in texts),
            "kakunin_per_text": round(sum(len(FLAG_RE.findall(t)) for t in texts) / n, 3),
            "header_lines_per_text": round(sum(len(HEADER_RE.findall(t)) for t in texts) / n, 3),
            "bold_only_lines_per_text": round(sum(len(BOLD_LINE_RE.findall(t)) for t in texts) / n, 3)}


def by_kind(s):
    return lambda rec, mid: [(a, g) for a, g, k in zip(rec["answers"], rec["gold"], rec["kind"]) if s in ("all", k)]


def x1_selectors(its):
    def pick(want):
        def sel(rec, mid):
            dl = {i for i, g in enumerate(its[mid]["gaps"]) if g["kind"] == "deadline_vs_date"}
            return [(a, g) for a, g, gp in zip(rec["answers"], rec["gold"], rec["gap"]) if want(gp, dl)]
        return sel
    return {"other_gap": pick(lambda gp, dl: gp >= 0 and gp not in dl), "deadline": pick(lambda gp, dl: gp in dl),
            "nongap": pick(lambda gp, dl: gp < 0)}


def x8_balance(its):
    """X8 PREREG filtering step 3, as X8's run.py applies it at analysis time."""
    trap = [q for it in its for q in it["questions"] if q["kind"] != "none"]
    e = sorted(q["qid"] for q in trap if q["answer"] == "E")
    random.Random("X8-balance").shuffle(e)
    n_e, n_t, drop = len(e), len(trap), []
    while 2 * n_e > n_t:
        drop.append(e.pop())
        n_e, n_t = n_e - 1, n_t - 1
    return set(drop)


def x8_selectors(drop):
    def pick(want):
        return lambda rec, mid: [(a, g) for a, g, k, q in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
                                 if q not in drop and want(k)]
    return {"trap": pick(lambda k: k != "none"), "nontrap": pick(lambda k: k == "none"), "alias": pick(lambda k: k == "alias")}


def summarize(s, conds, mids, ans, sels):
    out = {}
    for c in conds:
        texts = [text_f(s, c, w, m).read_text() for w in R.WRITERS for m in mids if text_f(s, c, w, m).exists()]
        out[c] = {r: {k: pooled(ans, c, r, f) for k, f in sels.items()} for r in READERS}
        out[c]["grok_by_writer"] = {w: {k: pooled(ans, c, "grok", f, [w]) for k, f in sels.items() if k != "all"}
                                    for w in R.WRITERS}
        out[c].update(text_stats(texts))
    return out


def handling(judged, conds):
    """Judge categories per condition. judged: {mid: {"c/w": cell}}."""
    out = {}
    for c in conds:
        cells = [j[f"{c}/{w}"] for j in judged.values() for w in R.WRITERS if f"{c}/{w}" in j]
        if not cells:
            continue
        g = [x for cell in cells for x in cell["gaps"]]
        cl = [x for cell in cells for x in cell["clear"]]
        out[c] = {"texts": len(cells), "gap_cells": len(g), "clear_cells": len(cl),
                  "gap_dist": {k: round(g.count(k) / len(g), 3) for k in CATS} if g else None,
                  "clear_dist": {k: round(cl.count(k) / len(cl), 3) for k in CLEAR_CATS} if cl else None,
                  "texts_flagging_a_gap": sum("flag" in cell["gaps"] for cell in cells),
                  "texts_flagging_a_clear_date": sum("flag" in cell["clear"] for cell in cells),
                  "extra_flags_total": sum(cell["extra_flags"] for cell in cells),
                  "extra_flags_per_text": round(sum(cell["extra_flags"] for cell in cells) / len(cells), 3)}
    return out


def load_judge(s, who):
    return {p.stem: json.loads(p.read_text()) for p in sorted((OUT / "judge" / s / who).glob("[VD][0-9]*.json"))}


def analyze_new():
    its = {it["id"]: it for it in memos("new")}
    mids = sorted(its)
    ans = load_answers("new", CONDS, mids)
    sels = {k: by_kind(k) for k in ("all", "gap", "clear", "other")}
    # sensitivity (PREREG change log): gap questions Haiku also answered E from the memo, i.e. the registered filter
    haiku_e = {q["qid"] for it in its.values() for q in it["questions"] if q["kind"] == "gap" and q["haiku_memo"] == "E"}
    sels["gap_haiku_e"] = lambda rec, mid: [(a, g) for a, g, k, q in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
                                            if k == "gap" and q in haiku_e]
    gap_qs = [q for it in its.values() for q in it["questions"] if q["kind"] == "gap"]
    sensitivity = {"kept_gap_questions": len(gap_qs), "haiku_memo_e": len(haiku_e),
                   "registered_rule_would_drop": len(gap_qs) - len(haiku_e),
                   "memos_left_under_registered_rule": len({q.split("-")[0] for q in haiku_e})}
    summary = summarize("new", CONDS, mids, ans, sels)
    for c in CONDS:
        summary[c]["system_prompt_chars"] = len(system_for(c)) - len(R.BASE_SYS) - 2 if c != "base" else 0
    j1, j2 = load_judge("new", "codex"), load_judge("new", "grok")

    def extra_per_memo(c):
        return {mid: sum(j[f"{c}/{w}"]["extra_flags"] for w in R.WRITERS) / len(R.WRITERS) for mid, j in j1.items()}

    tests = {}
    for x, y in COMPARE:
        for r in READERS:
            tests[f"{r} gap misread {x} - {y}"] = paired(per_memo(ans, x, r, mids, sels["gap"], "misread"),
                                                         per_memo(ans, y, r, mids, sels["gap"], "misread"))
            for k in ("clear", "other"):
                tests[f"{r} {k} acc {x} - {y}"] = paired(per_memo(ans, x, r, mids, sels[k], "acc"),
                                                         per_memo(ans, y, r, mids, sels[k], "acc"))
        tests[f"judged extra_flags per text {x} - {y}"] = paired(extra_per_memo(x), extra_per_memo(y))
    for x, y in VERDICTS.values():
        for r in READERS:
            sensitivity[f"{r} gap_haiku_e misread {x} - {y}"] = paired(
                per_memo(ans, x, r, mids, sels["gap_haiku_e"], "misread"),
                per_memo(ans, y, r, mids, sels["gap_haiku_e"], "misread"))

    # exploratory: clear-date accuracy by memo marker, gap misread by context, Grok's gap answers by judged handling
    def clear_by(markers):
        return lambda rec, mid: [(a, g) for a, g, k, ref in zip(rec["answers"], rec["gold"], rec["kind"], rec["ref"])
                                 if k == "clear" and its[mid]["clear"][ref]["marker"] in markers]

    def gap_by(step):
        return lambda rec, mid: [(a, g) for a, g, k, ref in zip(rec["answers"], rec["gold"], rec["kind"], rec["ref"])
                                 if k == "gap" and (its[mid]["gaps"][ref]["context"] == "step") == step]

    by_cat = {}
    for mid, j in j1.items():
        for key, cell in j.items():
            c, w = key.split("/")
            rec = ans[(c, w, "grok")].get(mid)
            gs = judge_items("new", its[mid])[0]
            for a, g, k, ref in zip(rec["answers"], rec["gold"], rec["kind"], rec["ref"]) if rec else ():
                if k == "gap" and its[mid]["gaps"][ref] in gs:
                    by_cat.setdefault(cell["gaps"][gs.index(its[mid]["gaps"][ref])], []).append((a, g))
    errors = {c: {k: {"E": sum(a == "E" for w in R.WRITERS for rec in ans[(c, w, "grok")].values()
                               for a, g in sels[k](rec, None) if a != g),
                      "other_option": sum(a != "E" for w in R.WRITERS for rec in ans[(c, w, "grok")].values()
                                          for a, g in sels[k](rec, None) if a != g)} for k in ("clear", "other")}
              for c in CONDS}
    exploratory = {
        "grok_clear_acc_by_marker": {c: {grp: pooled(ans, c, "grok", clear_by(ms)) for grp, ms in
                                         (("에/까지", ("에", "까지")), ("실시/시작/마감", ("실시", "시작", "마감")))}
                                     for c in CONDS},
        "grok_gap_misread_by_context": {c: {"step": pooled(ans, c, "grok", gap_by(True)),
                                            "not_step": pooled(ans, c, "grok", gap_by(False))} for c in CONDS},
        "grok_gap_by_judged_handling": {k: r4(rates(v)) for k, v in sorted(by_cat.items())},
        "grok_wrong_answers": errors}

    both = sorted(set(j1) & set(j2))
    gp = [(a, b) for mid in both for key in j2[mid] for a, b in zip(j1[mid][key]["gaps"], j2[mid][key]["gaps"])]
    cp = [(a, b) for mid in both for key in j2[mid] for a, b in zip(j1[mid][key]["clear"], j2[mid][key]["clear"])]
    ep = [(j1[mid][key]["extra_flags"], j2[mid][key]["extra_flags"]) for mid in both for key in j2[mid]]

    def agree(ps, f=lambda a, b: a == b):
        return round(sum(f(a, b) for a, b in ps) / len(ps), 3) if ps else None

    agreement = {"memos": both, "gap_cells": len(gp), "gap_category": agree(gp),
                 "gap_flag": agree(gp, lambda a, b: (a == "flag") == (b == "flag")),
                 "clear_cells": len(cp), "clear_category": agree(cp),
                 "clear_flag": agree(cp, lambda a, b: (a == "flag") == (b == "flag")),
                 "extra_flags_exact": agree(ep), "extra_flags_total": [sum(a for a, _ in ep), sum(b for _, b in ep)]}

    base = summary["base"]["grok"]["all"]
    flog = json.loads((OUT / "filter-log.json").read_text())
    items = [json.loads(p.read_text()) for p in sorted((OUT / "items").glob("V*.json"))]
    kept_q = [q for it in its.values() for q in it["questions"]]
    return {"memos": len(its), "items_generated": len(items), "filter": flog,
            "kept_questions": {k: sum(q["kind"] == k for q in kept_q) for k in ("gap", "clear", "other")},
            "kept_gap_contexts": {k: sum(its[q["qid"].split("-")[0]]["gaps"][q["ref"]]["context"] == k
                                         for q in kept_q if q["kind"] == "gap") for k in CONTEXTS},
            "kept_clear_markers": {k: sum(its[q["qid"].split("-")[0]]["clear"][q["ref"]]["marker"] == k
                                          for q in kept_q if q["kind"] == "clear") for k in MARKERS},
            "ceiling_broken": bool(base and (base["acc"] <= 0.95 or base["misread"] >= 0.03)),
            "summary": summary, "tests": tests, "gap_filter_sensitivity": sensitivity,
            "judge_handling": handling(j1, CONDS), "judge_agreement": agreement,
            "exploratory": exploratory}


def analyze_rep(s):
    its = {it["id"]: it for it in memos(s)}
    mids, conds = sorted(its), REP_CONDS[s]
    ans = load_answers(s, conds, mids)
    if s == "X7":
        sels = {k: by_kind(k) for k in ("all", "gap", "clear", "other")}
        metrics = [("gap", "misread", READERS), ("clear", "acc", ["grok"]), ("other", "acc", ["grok"])]
    elif s == "X1":
        sels = x1_selectors(its)
        metrics = [("other_gap", "misread", READERS), ("deadline", "misread", ["grok"]), ("nongap", "acc", ["grok"])]
    else:
        sels = x8_selectors(x8_balance(list(its.values())))
        metrics = [("trap", "misread", READERS), ("nontrap", "acc", ["grok"]), ("alias", "acc", ["grok"])]
    tests = {f"{r} {k} {metric} {x} - {y}": paired(per_memo(ans, x, r, mids, sels[k], metric),
                                                   per_memo(ans, y, r, mids, sels[k], metric))
             for x, y in REP_COMPARE[s] for k, metric, rs in metrics for r in rs}
    out = {"memos": len(mids), "summary": summarize(s, conds, mids, ans, sels), "tests": tests}
    if s == "X7":
        out["judge_handling"] = handling(load_judge("X7", "codex"), X7_JUDGED)
    return out


def verdicts(new, rep):
    out = {}
    for name, (x, y) in VERDICTS.items():
        p, cl, ot = (new["tests"][f"grok {k} {x} - {y}"] for k in ("gap misread", "clear acc", "other acc"))
        x1, x8 = rep["X1"]["tests"][f"grok other_gap misread {x} - {y}"], rep["X8"]["tests"][f"grok trap misread {x} - {y}"]
        if not all((p, cl, ot, x1, x8)):
            out[name] = None
            continue
        v = {"primary_upper_below_0": r9(p["ci95"][1]) < 0, "clear_noninferior_3pp": r9(cl["ci95"][0]) > -0.03,
             "other_noninferior_3pp": r9(ot["ci95"][0]) > -0.03,
             "x1_other_gap_upper_below_margin": r9(x1["ci95"][1]) < MARGIN["X1"],
             "x8_trap_upper_below_margin": r9(x8["ci95"][1]) < MARGIN["X8"]}
        v["adopt"] = all(v.values())
        out[name] = v
    return out


def cmd_analyze(pilot=False):
    new = analyze_new() if (OUT / "kept").exists() else None
    rep = {s: analyze_rep(s) for s in ("X7", "X1", "X8")}
    rep_out = {"verdict": verdicts(new, rep) if new else None, "main": new, "regression": rep,
               "prompt_sha256": PROMPT_SHA, "v3_commit": V3_COMMIT, "margins": MARGIN}
    out = json.dumps(rep_out, ensure_ascii=False, indent=1)
    (OUT / ("report-pilot.json" if pilot else "report.json")).write_text(out)
    print(out)


# ---------- power (PREREG numbers) ----------

def cmd_power(_pilot=False):
    """Non-inferiority lower bounds and pass rates for the new memos; regression margins from X1 and X8 data."""
    def sim(n, r, p, delta, reps=200, seed=3):
        rnd, ok = random.Random(seed), 0
        for _ in range(reps):
            d = [sum(rnd.random() < p for _ in range(r)) / r - sum(rnd.random() < p + delta for _ in range(r)) / r
                 for _ in range(n)]
            ok += r9(R.boot(d, n=2000)[1]) > -0.03
        return ok / reps

    def null_pass(d, margin, reps=400, seed=1):
        mu = sum(d) / len(d)
        c, rnd = [v - mu for v in d], random.Random(seed)
        return sum(r9(R.boot([rnd.choice(c) for _ in c], n=2000)[2]) < margin for _ in range(reps)) / reps

    out = {"lower_bound_after_k_extra_errors": {f"memos={n} answers_per_memo={r}": [
        round(R.boot([-1 / r] * k + [0.0] * (n - k))[1], 4) for k in range(6)] for n, r in ((24, 8), (21, 8), (18, 8))},
        "pass_rate_noninferiority": {f"memos={n} answers_per_memo=8 error={p}": {
            f"v4_extra={dl}": sim(n, 8, p, dl) for dl in (0.0, 0.01, 0.02)} for n in (24, 21) for p in (0.0, 0.01, 0.02)}}
    reg = {}
    for s, k in (("X1", "other_gap"), ("X8", "trap")):
        its = {it["id"]: it for it in memos(s)}
        mids = sorted(its)
        ans = load_answers(s, ["short-v3", "full-v3"], mids)
        sel = (x1_selectors(its) if s == "X1" else x8_selectors(x8_balance(list(its.values()))))[k]
        a, b = (per_memo(ans, c, "grok", mids, sel, "misread") for c in ("full-v3", "short-v3"))
        d = [a[m] - b[m] for m in mids if a[m] is not None and b[m] is not None]
        reg[f"{s} {k} misread full-v3 - short-v3"] = {
            "memos": len(d), "observed": paired(a, b),
            "pass_rate_if_no_change": {f"margin={mg}": null_pass(d, mg) for mg in (0.05, 0.07, 0.08, 0.10)}}
    out["regression_margin"] = reg
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------- selftest ----------

def selftest():
    assert rates([("E", "E"), ("A", "E"), ("E", "B"), ("C", "C")]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert rates([]) is None
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "E", "kind": "gap", "ref": 0}
    sq = shuffle(q, "k")
    assert sq["answer"] == "E" and sorted(sq[k] for k in "ABCD") == list("abcd")
    sq = shuffle({**q, "answer": "C", "kind": "other", "ref": -1}, "k")
    assert sq[sq["answer"]] == "c"
    assert clean_q({**q, "A": "그날 반납한다.\nE. 글만으로는 알 수 없다"})["A"] == "그날 반납한다."
    # marker checks on memo lines
    assert gap_ok("11/20(금) 보고서 제출", "11/20(금)") and gap_ok("요금 개편안 11/27(금) 확정", "11/27(금)")
    assert gap_ok("11/20(금) 전사 보고서 제출", "11/20(금)") and gap_ok("11/20(금) 오후 3시 보고서 공유", "11/20(금)")
    for bad in ("11/20(금)까지 보고서 제출", "11/20(금)에 보고서 제출", "11/20(금) 14:00에 배포", "11/20(금) 마감 보고서",
                "11/20(금) 배포 예정", "11/20(금) 전 제출", "11/16(월)~11/18(수) 수령", "11/20(금) 점검 실시",
                "11/20(금) 교육 시작", "11/20(금) 이관 완료", "11/20(금) 진행 현황 공유"):
        assert not gap_ok(bad, bad[:bad.index(")") + 1]), bad
    ok = [("11/24(화) 오전 10시에 점검", "on", "에"), ("11/24(화) 10:00-12:00에 점검", "on", "에"),
          ("11/24(화) 10:00에 점검 시작", "on", "에"), ("11/26(목) 소방 훈련 실시", "on", "실시"),
          ("12/3(목) 14:00 교육 시작", "on", "시작"), ("11/27(금)까지 신청서 제출", "by", "까지"),
          ("참가 신청 12/4(금) 마감", "by", "마감")]
    for fact, kind, mk in ok:
        assert clear_ok(fact, re.search(DATE, fact)[0], kind, mk), fact
    no = [("11/24(화) 점검", "on", "에"), ("11/26(목) 10:00에 훈련 실시", "on", "실시"), ("11/27(금) 신청서 제출", "by", "까지"),
          ("12/4(금)까지 신청 마감", "by", "마감"), ("12/4(금)까지 신청 마감", "by", "까지"), ("11/27(금)까지 제출", "on", "까지"),
          ("11/24(화)에 점검", "by", "에")]
    for fact, kind, mk in no:
        assert not clear_ok(fact, re.search(DATE, fact)[0], kind, mk), fact
    assert calendar_ok("11/20(금)") and not calendar_ok("11/20(목)") and not calendar_ok("11/31(화)")
    assert calendar_ok("11/19(목) 09:00") and not calendar_ok("11/19(금) 09:00")
    it = {"facts": ["요금 개편안 11/27(금) 확정", "11/24(화) 10:00에 서버 점검", "12/1(화) 고객 안내문 발송",
                    "11/26(목) 소방 훈련 실시", "11/30(월)까지 신청서 제출", "참가 신청 12/4(금) 마감", "문의 총무팀",
                    "대상 전 직원", "수량 1인 1장", "장소 본관 3층"],
          "gaps": [{"fact": 0, "date": "11/27(금)", "context": "decision"}, {"fact": 2, "date": "12/1(화)", "context": "step"}],
          "clear": [{"fact": 1, "date": "11/24(화)", "kind": "on", "marker": "에"},
                    {"fact": 3, "date": "11/26(목)", "kind": "on", "marker": "실시"},
                    {"fact": 4, "date": "11/30(월)", "kind": "by", "marker": "까지"},
                    {"fact": 5, "date": "12/4(금)", "kind": "by", "marker": "마감"}],
          "questions": [{"kind": k} for k in ["gap"] * 2 + ["clear"] * 4 + ["other"] * 4]}
    assert problems(it, 1) == [], problems(it, 1)
    assert problems(it, 0) == ["gaps 2", "contexts ['decision', 'step']"], problems(it, 0)
    f = it["facts"]
    adj = {**it, "facts": [f[0], f[2], f[1]] + f[3:], "gaps": [it["gaps"][0], {**it["gaps"][1], "fact": 1}],
           "clear": [{**it["clear"][0], "fact": 2}] + it["clear"][1:]}
    assert problems(adj, 1) == ["adjacent gaps"], problems(adj, 1)
    bad = {**it, "facts": ["요금 개편안 11/27(금)까지 확정"] + it["facts"][1:]}
    assert problems(bad, 1) == ["gap 0 marked: 요금 개편안 11/27(금)까지 확정"], problems(bad, 1)
    assert valid_q({"kind": "gap", "answer": "E", "ref": 1}, it) and not valid_q({"kind": "gap", "answer": "E", "ref": 0}, bad)
    assert not valid_q({"kind": "gap", "answer": "A", "ref": 1}, it) and not valid_q({"kind": "clear", "answer": "E", "ref": 0}, it)
    assert valid_q({"kind": "clear", "answer": "B", "ref": 3}, it) and valid_q({"kind": "other", "answer": "A", "ref": -1}, it)
    assert judge_items("new", {**bad, "gaps": [{**g, "what": ""} for g in bad["gaps"]]})[0] == [{**bad["gaps"][1], "what": ""}]
    fq = [{"kind": k, "answer": a, "qid": f"V01-q{i}"} for i, (k, a) in enumerate((("gap", "E"), ("gap", "E"), ("clear", "B"),
                                                                                   ("other", "C"), ("other", "A")))]
    kept = filter_keep(fq, {"grok": ["E", "D", "B", "C", "A"], "haiku": ["C", "E", "B", "D", "A"]})
    assert [q["qid"] for q in kept] == ["V01-q0", "V01-q2", "V01-q4"] and kept[0]["haiku_memo"] == "C"
    # writer prompts: v3 is commit 98db878's block, with the lengths X7 reported; v4 has the new sentences
    v3 = v3_source()
    for c in ("short", "full"):
        assert system_for(f"{c}-v3") == R.BASE_SYS + "\n\n" + block(v3, c)
    assert len(block_file("short-v3").read_text()) == 1494 and len(block_file("full-v3").read_text()) == 5462
    s4, f4 = block_file("short-v4").read_text(), block_file("full-v4").read_text()
    assert len(s4) == 1499 and '"에"나 "까지"로 밝힌 날짜는 묻지 않는다.' in s4 and "날짜가 실행일인지 기한인지 모르는 문장" in s4
    assert "제목은 헤더로 쓴다" in s4 and '날짜의 "에"' not in s4  # v4.1: v4.0's header rule back, its "에" marker out
    assert '사실이 "에"나 "까지"로 밝힌 날짜는 실행일인지 기한인지 묻지 않는다.' in f4
    assert "한쪽으로 정하지 않고 물었는가?" in f4 and system_for("base") == R.BASE_SYS
    # paths: v3 and base come from each experiment, v4 is written here
    assert text_f("X1", "short-v3", "sonnet", "M01") == SRC["X1"] / "texts/short/sonnet/M01.md"
    assert ans_f("X7", "short+k15u", "haiku", "grok", "D01") == SRC["X7"] / "answers/short+k15u/haiku/grok/D01.json"
    assert ans_f("X8", "full-v4", "haiku", "grok", "M01") == OUT / "rep/X8/answers/full-v4/haiku/grok/M01.json"
    assert text_f("new", "short-v3", "sonnet", "V01") == OUT / "texts/short-v3/sonnet/V01.md"
    for c in REP_CONDS["X7"] + REP_CONDS["X1"]:
        if c not in NEW:
            assert ans_f("X7" if c in REP_CONDS["X7"] else "X1", c, "sonnet", "grok", "D01" if c in REP_CONDS["X7"]
                         else "M01").exists(), c
    assert [len(memos(s)) for s in ("X7", "X1", "X8")] == [21, 24, 24]
    assert len(x8_balance(memos("X8"))) == 17  # X8 RESULTS: the balance rule dropped 17 E-gold trap questions
    # analysis helpers
    rec = {"answers": ["E", "B", "A", "C"], "gold": ["E", "C", "A", "C"], "kind": ["gap", "gap", "clear", "other"]}
    assert by_kind("gap")(rec, None) == [("E", "E"), ("B", "C")] and by_kind("clear")(rec, None) == [("A", "A")]
    assert paired({"V01": 0.5, "V02": None}, {"V01": 0.25, "V02": 0.0}) == {"memos": 1, "diff": 0.25, "ci95": [0.25, 0.25]}
    assert r9(-1.2e-18) == 0 and not r9(-1.2e-18) < 0
    x8 = x8_selectors({"M01-q0"})
    rec8 = {"answers": ["A", "E", "B"], "gold": ["E", "E", "B"], "kind": ["deixis", "abbrev", "none"],
            "qid": ["M01-q0", "M01-q1", "M01-q2"]}
    assert x8["trap"](rec8, "M01") == [("E", "E")] and x8["nontrap"](rec8, "M01") == [("B", "B")]
    x1 = x1_selectors({"M01": {"gaps": [{"kind": "deadline_vs_date"}, {"kind": "no_actor"}]}})
    rec1 = {"answers": ["C", "A", "B"], "gold": ["E", "E", "B"], "gap": [0, 1, -1]}
    assert x1["deadline"](rec1, "M01") == [("C", "E")] and x1["other_gap"](rec1, "M01") == [("A", "E")]
    assert x1["nongap"](rec1, "M01") == [("B", "B")]
    order = [("base", "sonnet"), ("full-v4", "haiku")]
    raw = ('x {"texts": [{"id": "T2", "gaps": ["flag"], "clear": ["keep", "flag"], "extra_flags": 1}, '
           '{"id": "T1", "gaps": ["invent"], "clear": ["keep", "drop"], "extra_flags": 0}]}')
    assert parse_judge(raw, order, 1, 2) == {"base/sonnet": {"gaps": ["invent"], "clear": ["keep", "drop"], "extra_flags": 0},
                                             "full-v4/haiku": {"gaps": ["flag"], "clear": ["keep", "flag"], "extra_flags": 1}}
    for bad_raw in ('{"texts": [{"id": "T1", "gaps": ["invent"], "clear": ["keep", "keep"], "extra_flags": 0}]}',
                    '{"texts": [{"id": "T1", "gaps": ["invent"], "clear": ["keep"], "extra_flags": 0}, '
                    '{"id": "T2", "gaps": ["flag"], "clear": ["keep", "keep"], "extra_flags": 0}]}'):
        try:
            parse_judge(bad_raw, order, 1, 2)
            raise AssertionError("parse_judge accepted " + bad_raw)
        except (KeyError, ValueError):
            pass
    assert sorted(judge_order("new", "V01")) == sorted((c, w) for c in CONDS for w in R.WRITERS)
    assert judge_order("X7", "D01") == judge_order("X7", "D01") and len(judge_order("X7", "D01")) == 12
    h = handling({"V01": {"base/sonnet": {"gaps": ["flag"], "clear": ["keep", "flag"], "extra_flags": 2},
                          "base/haiku": {"gaps": ["keep"], "clear": ["keep", "keep"], "extra_flags": 0}}}, ["base"])
    assert h["base"]["texts_flagging_a_clear_date"] == 1 and h["base"]["extra_flags_per_text"] == 1.0
    assert JUDGE_SAMPLE == ["V01", "V05", "V09", "V13", "V17", "V21"]
    print("selftest ok")


STEPS = {"freeze": cmd_freeze, "items": cmd_items, "filter": cmd_filter, "texts": cmd_texts, "judge": cmd_judge,
         "analyze": cmd_analyze}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=list(STEPS) + ["all", "selftest", "power"])
    ap.add_argument("--pilot", action="store_true", help="genre 0 items; V01-V02 and one memo of X7, X1, X8")
    a = ap.parse_args()
    if a.cmd == "selftest":
        selftest()
        sys.exit()
    if a.cmd == "power":
        cmd_power()
        sys.exit()
    if a.cmd not in ("analyze", "freeze"):
        need_env()
    for step in (list(STEPS) if a.cmd == "all" else [a.cmd]):
        log(f"== {step}")
        STEPS[step](a.pilot)
