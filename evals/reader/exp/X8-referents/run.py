#!/usr/bin/env python3
"""X8-referents: memos that blur their referents. Do writers guess the referent, and do readers believe the guess?

Design and pre-registration: PREREG.md. Pipeline adapted from exp/X1-ambiguous/run.py.
Usage: python3 run.py <items|filter|write|read|judge|analyze|all|selftest> [--pilot]
Every model response is cached under out/; a rerun skips calls whose file exists.
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
PER_GENRE = 3
PILOT = ["M01", "M02"]
KINDS = ["deixis", "shared_name", "alias", "abbrev"]
E_KINDS = {"deixis", "abbrev"}  # gold is E; shared_name and alias have a concrete gold (PREREG)
CATS = ["invent", "keep", "flag", "omit"]
READERS = ["grok", "haiku"]
JUDGES = ["codex", "grok"]  # primary first
JUDGE_SAMPLE = [f"M{i:02d}" for i in range(1, 25, 4)]  # 25% re-judged by Grok
COMPARE = [("full", "base"), ("short", "base"), ("clarity", "base"), ("full", "clarity")]
FLAG_RE = re.compile(r"확인\s*필요|확인이\s*필요")
MEMO_MARK_RE = re.compile(r"확인\s*필요|확인이\s*필요|미정|TBD|\?")
E_ECHO_RE = re.compile(r"\s*\(?\s*E\s*[.)]\s*글만으로는\s*알\s*수\s*없다\.?\s*\)?")

Q_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["q", "A", "B", "C", "D", "answer", "trap", "facts"],
    "properties": {"q": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"},
                   "C": {"type": "string"}, "D": {"type": "string"},
                   "answer": {"type": "string", "enum": list("ABCDE")},
                   "trap": {"type": "integer"}, "facts": {"type": "array", "items": {"type": "integer"}}}}
ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["audience", "request", "facts", "traps", "questions"],
        "properties": {
            "audience": {"type": "string"}, "request": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "string"}},
            "traps": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["kind", "fact", "what"],
                "properties": {"kind": {"type": "string", "enum": KINDS}, "fact": {"type": "integer"},
                               "what": {"type": "string"}}}},
            "questions": {"type": "array", "items": Q_SCHEMA}}}}}}

ITEM_PROMPT = """너는 독해 평가 문항 출제자다. 장르 "{genre}"의 업무 상황 {n}개를 만든다. 각 상황은 바쁜 직원이 AI에게 글을 맡기며 건네는 메모다. 이 메모에는 실제 업무 메모처럼 무엇을 가리키는지 흐린 말(대상 함정)이 일부러 들어 있다. 평가는 글쓴이가 흐린 대상을 짐작해서 정하는지, 그 글을 읽은 독자가 짐작한 대상을 믿는지 본다.

- audience: 이 글을 읽을 사람.
- request: AI에게 하는 요청 한 문장. 장르와 독자를 밝힌다. 함정은 언급하지 않는다. 예: "아래 내용으로 전 직원에게 보낼 사내 메신저 공지를 써 줘."
- facts: 8-12개. 실제 직원이 쓰는 짧은 메모 말투(개조식, 조사 생략)로 쓴다. 회사, 사람, 팀, 시스템, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 요일을 붙인다.
- 독자가 행동하는 데 필요한 정보를 고루 담는다: 누가, 무엇을, 언제, 어디서, 어떤 조건과 예외에서, 의무 강도, 수치와 단위, 원인, 문의처.
- facts 가운데 서로 다른 4개 항목에 대상 함정을 하나씩 넣는다. 아래 4종류를 하나씩 모두 쓴다.
  - deixis: "그거", "그건", "거기", "그쪽 팀", "그 건"처럼 지시어로 대상을 가리키되, 메모의 다른 항목으로 무엇을 가리키는지 정할 수 없게 쓴다. 메모에 그 지시어가 가리킬 만한 후보가 둘 이상 있어야 한다.
  - shared_name: 메모에 서로 다른 두 대상(예: 주문 DB와 정산 DB, 운영팀 팀장과 보안팀 팀장, 사내 서버와 고객사 서버)을 함께 쓰고, 함정 항목에서는 둘 다에 쓸 수 있는 같은 말("DB", "팀장님", "서버")로만 부른다. 다른 항목으로 어느 쪽인지 정할 수 없어야 한다.
  - alias: 한 대상을 두 이름(정식 이름과 별칭, 약칭, 영문 이름)으로 부른다. "정산 시스템(이하 정시)"처럼 대놓고 정의하지 않는다. 하지만 문맥(같은 일정, 같은 담당자, 같은 수치, 같은 작업)으로 두 이름이 같은 대상이라는 것이 하나로 풀려야 한다.
  - abbrev: 두 가지로 읽히는 약칭(예: "PM"은 제품 관리자 또는 프로젝트 관리자, "DR"은 재해 복구 또는 설계 검토, "CS팀"은 고객지원팀 또는 고객성공팀)을 쓰되, 메모의 다른 항목으로 어느 뜻인지 정할 수 없게 쓴다. 두 뜻 모두 그 상황에서 그럴듯해야 한다.
- 함정은 바쁜 직원이 남긴 자연스러운 메모처럼 보여야 한다. "미정", "확인 필요", "?", "TBD" 같은 표시를 붙이지 않는다. 함정이 아닌 facts는 오해할 여지가 없게 쓴다.
- traps: 넣은 함정마다 kind, fact(facts 번호, 0부터), what(무엇이 흐린지 한 문장. alias면 두 이름이 가리키는 하나의 대상)을 쓴다.
- questions: 7개. 모든 문항에는 보기 A-D 뒤에 "E. 글만으로는 알 수 없다"가 자동으로 붙는다. 그래서 문항 본문과 보기에 이 문장을 쓰지 않는다. 독자는 메모를 보지 못하고 메모로 쓴 글만 읽는다. 그래서 문항 본문과 보기에 "메모"라는 말을 쓰지 않는다. 문항의 facts에는 근거가 되는 facts 번호를 쓴다.
  - 함정 문항 4개: 함정마다 하나씩, 독자가 그 함정 항목에서 알아야 하는 대상을 묻는다. trap에는 traps의 번호(0-3)를 쓴다.
  - deixis 문항과 abbrev 문항: answer는 E다. A-D에는 글쓴이가 대상을 짐작해서 정했을 때 독자가 고를 구체적인 대상(지시어가 가리킬 만한 후보, 약칭의 두 뜻)을 넣는다. A-D에 "정해지지 않았다", "알 수 없다" 같은 보기를 넣지 않는다.
  - shared_name 문항: answer는 A-D 가운데 하나다. 흐린 말을 그대로 옮긴 보기 하나를 정답으로 한다(예: "'DB'라고만 했고, 주문 DB인지 정산 DB인지는 밝히지 않았다"). 나머지 보기는 두 대상 가운데 하나, 두 대상 모두처럼 더 구체적인 답으로 만든다.
  - alias 문항: answer는 A-D 가운데 하나이고, 두 이름이 가리키는 그 하나의 대상이다. 오답 보기에는 메모의 다른 대상과, 두 이름을 서로 다른 대상으로 본 독자가 고를 답을 넣는다.
  - 함정이 아닌 문항 3개: 함정이 아닌 facts를 묻는다. trap에는 -1을 쓴다. answer는 A-D 가운데 하나이고, facts만으로 하나로 정해지며, 상식이나 추측으로 맞힐 수 없어야 한다. 오답 보기는 같은 메모의 다른 날짜, 사람, 수치, 의무 강도처럼 헷갈릴 만한 것으로 만든다.
- {n}개 상황은 회사, 업무 영역, 독자가 서로 달라야 한다. 상황마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다."""

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["texts"],
    "properties": {"texts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "traps", "extra_flags"],
        "properties": {"id": {"type": "string"},
                       "traps": {"type": "array", "items": {"type": "string", "enum": CATS}},
                       "extra_flags": {"type": "integer"}}}}}}

JUDGE_PROMPT = """아래 메모로 AI 글쓴이 여러 명이 각각 글을 썼다. 메모에는 대상을 흐리게 쓴 항목(함정)이 {k}개 있다. 글마다 함정 하나하나를 어떻게 다뤘는지 판정한다.

함정 종류:
- deixis: 무엇을 가리키는지 정할 수 없는 지시어.
- shared_name: 서로 다른 두 대상에 같이 쓰는 이름. 함정 항목에서는 어느 대상인지 정할 수 없다.
- alias: 한 대상을 부르는 두 이름. 문맥으로 같은 대상임이 풀린다.
- abbrev: 두 가지로 읽히는 약칭. 어느 뜻인지 정할 수 없다.

범주:
- invent: 메모에 없는 내용으로 대상을 정했다. deixis: 지시어가 가리키는 대상을 정했다. shared_name: 두 대상 가운데 하나로 정했거나, 두 대상을 하나로 합쳤거나, 둘 다로 넓혔다. alias: 한 대상을 서로 다른 둘로 나눴거나 다른 대상으로 정했다. abbrev: 약칭의 뜻 하나를 정해서 풀어 썼다.
- keep: 메모의 표현을 같은 정도로 옮겼고, 대상이 흐리다고 표시하지 않았다. alias는 같은 대상으로 썼으면(이름 하나로 통일했거나 두 이름을 같은 대상으로 이었으면) keep이다.
- flag: 대상이 무엇인지 빠졌거나 확인이 필요하다고 글에 드러냈다. 예: "확인 필요", 요청자에게 묻는 질문, "[대상]" 같은 자리 표시. 드러내면서 후보를 함께 써도 flag다. alias에서 두 이름이 같은 대상인지 확인이 필요하다고 쓴 것도 flag다.
- omit: 그 항목을 글에서 뺐다.

extra_flags: 함정 목록과 관계없는 내용에 붙은 표시("확인 필요", 요청자에게 묻는 질문, 자리 표시, "미정")의 수다. 함정에 붙은 표시는 세지 않는다.

<메모>
{memo}
</메모>

<함정>
{traps}
</함정>

{texts}

글 {n}편 모두를 판정한다. 출력은 JSON 하나다. 형식: {{"texts": [{{"id": "T1", "traps": [{example}], "extra_flags": 0}}]}}. traps에는 함정 번호 순서대로 범주를 하나씩 쓴다."""


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


# ---------- items ----------

def problems(it):
    """Format violations of a generated memo; logged, not filtered (PREREG)."""
    p = []
    if not 8 <= len(it["facts"]) <= 12:
        p.append(f"facts {len(it['facts'])}")
    kinds = [t["kind"] for t in it["traps"]]
    if sorted(kinds) != sorted(KINDS):
        p.append(f"traps {kinds}")
    if any(not 0 <= t["fact"] < len(it["facts"]) for t in it["traps"]):
        p.append("trap fact index")
    if len({t["fact"] for t in it["traps"]}) != len(it["traps"]):
        p.append("traps share a fact")
    if len(it["questions"]) != 7:
        p.append(f"questions {len(it['questions'])}")
    per_trap = [sum(q["trap"] == i for q in it["questions"]) for i in range(len(it["traps"]))]
    if per_trap != [1] * len(it["traps"]):
        p.append(f"questions per trap {per_trap}")
    if any(MEMO_MARK_RE.search(f) for f in it["facts"]):
        p.append("flag mark in memo")
    return p


def clean_q(q):
    """Strip an echoed 'E. 글만으로는 알 수 없다' from the stem (X1 limitation 4); pure formatting."""
    return {**q, "q": E_ECHO_RE.sub("", q["q"]).strip()}


def invalid(q, traps):
    """Reason a question breaks the format (PREREG filtering step 1), or None."""
    if any("메모" in q[k] for k in ("q", "A", "B", "C", "D")):
        return "mentions memo"
    if q["trap"] == -1:
        return None if q["answer"] in "ABCD" else "non-trap gold E"
    if not 0 <= q["trap"] < len(traps):
        return "trap index"
    want_e = traps[q["trap"]]["kind"] in E_KINDS
    return None if (q["answer"] == "E") == want_e else f"{traps[q['trap']]['kind']} gold {q['answer']}"


def shuffle(q, key):
    """Shuffle A-D with a fixed seed; E stays E."""
    opts = [q[k] for k in "ABCD"]
    gold = None if q["answer"] == "E" else q[q["answer"]]
    random.Random(key).shuffle(opts)
    return {**q, **dict(zip("ABCD", opts)), "answer": "E" if gold is None else "ABCD"[opts.index(gold)]}


def cmd_items(pilot):
    def one(gi):
        raw = cached(OUT / "items" / f"batch{gi}.json",
                     lambda: json.loads(R.call("codex", ITEM_PROMPT.format(genre=R.GENRES[gi], n=PER_GENRE,
                                                                           batch=gi + 1), ITEM_SCHEMA)))
        for k, it in enumerate(raw["items"][:PER_GENRE]):
            it = json.loads(R.fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=f"M{gi * PER_GENRE + k + 1:02d}", genre=R.GENRES[gi])
            (OUT / "items" / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))

    R.pmap(one, [0] if pilot else range(len(R.GENRES)), workers=3)


def cmd_filter(pilot):
    flog_f = OUT / "filter-log.json"
    flog = json.loads(flog_f.read_text()) if flog_f.exists() else {}

    def one(f):
        it = json.loads(f.read_text())
        if pilot and it["id"] not in PILOT:
            return
        qs, bad = [], []
        for i, q in enumerate(it["questions"]):
            q = clean_q(q)
            why = invalid(q, it["traps"])
            if why:
                bad.append(f"q{i}: {why}")
                continue
            kind = "none" if q["trap"] == -1 else it["traps"][q["trap"]]["kind"]
            qs.append({**shuffle(q, f"{it['id']}-{i}"), "qid": f"{it['id']}-q{i}", "kind": kind})
        ans = cached(OUT / "filter" / f"{it['id']}.json", lambda: R.ask("grok", R.memo(it), qs))
        keep = [q for q, a in zip(qs, ans) if a == q["answer"]]
        flog[it["id"]] = {"problems": problems(it), "invalid": bad, "generated": len(it["questions"]),
                          "valid": len(qs), "kept": len(keep),
                          "dropped_by_grok": [q["qid"] + " " + q["kind"] for q, a in zip(qs, ans) if a != q["answer"]],
                          "trap_kept": sum(q["kind"] != "none" for q in keep)}
        if any(q["kind"] != "none" for q in keep):
            (OUT / "kept").mkdir(exist_ok=True)
            (OUT / "kept" / f.name).write_text(json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        else:
            log(f"drop memo {it['id']}: no trap question left")

    R.pmap(one, sorted((OUT / "items").glob("M*.json")), workers=4)
    flog_f.write_text(json.dumps(flog, ensure_ascii=False, indent=1, sort_keys=True))


def memos(pilot=False):
    its = [json.loads(p.read_text()) for p in sorted((OUT / "kept").glob("M*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT]


def balance(its):
    """PREREG filtering step 3: qids of E-gold trap questions dropped so E-gold is at most half of trap questions.
    Applied at analysis time; readers answer every kept question."""
    trap = [q for it in its for q in it["questions"] if q["kind"] != "none"]
    e = sorted(q["qid"] for q in trap if q["answer"] == "E")
    random.Random("X8-balance").shuffle(e)
    n_e, n_t, drop = len(e), len(trap), []
    while 2 * n_e > n_t:
        drop.append(e.pop())
        n_e, n_t = n_e - 1, n_t - 1
    return set(drop)


# ---------- texts and reading ----------

def text_f(c, w, mid):
    return OUT / "texts" / c / w / f"{mid}.md"


def cmd_write(pilot):
    def one(job):
        it, c, w = job
        f = text_f(c, w, it["id"])
        if not f.exists():
            t = R.call(w, R.memo(it), system=R.system_for(c))
            if not t.strip():
                raise RuntimeError(f"empty text {c}/{w}/{it['id']}")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(t)

    R.pmap(one, [(it, c, w) for it in memos(pilot) for c in R.CONDITIONS for w in R.WRITERS],
           workers=int(os.environ.get("KSTE_LIMIT_CLAUDE", 3)))


def read_one(it, c, w, r):
    qs = it["questions"]
    cached(OUT / "answers" / c / w / r / f"{it['id']}.json",
           lambda: {"answers": R.ask(r, text_f(c, w, it["id"]).read_text(), qs,
                                     R.persona_for(f"X8/{c}/{w}/{r}/{it['id']}")),
                    "gold": [q["answer"] for q in qs], "kind": [q["kind"] for q in qs],
                    "qid": [q["qid"] for q in qs]})


def cmd_read(pilot):
    jobs = {r: [(it, c, w, r) for it in memos(pilot) for c in R.CONDITIONS for w in R.WRITERS] for r in READERS}
    workers = {"grok": int(os.environ.get("KSTE_LIMIT_GROK", 2)), "haiku": int(os.environ.get("KSTE_LIMIT_CLAUDE", 3))}
    with ThreadPoolExecutor(len(READERS)) as ex:
        for f in [ex.submit(R.pmap, lambda j: read_one(*j), jobs[r], workers[r]) for r in READERS]:
            f.result()


# ---------- judging ----------

def judge_order(mid):
    order = [(c, w) for c in R.CONDITIONS for w in R.WRITERS]
    random.Random(f"judge-{mid}").shuffle(order)
    return order


def judge_prompt(it, order):
    traps = "\n".join(f"{i}. ({t['kind']}) 메모 항목 \"{it['facts'][t['fact']]}\": {t['what']}"
                      for i, t in enumerate(it["traps"]))
    texts = "\n\n".join(f"<글 T{i + 1}>\n{text_f(c, w, it['id']).read_text()}\n</글 T{i + 1}>"
                        for i, (c, w) in enumerate(order))
    return JUDGE_PROMPT.format(k=len(it["traps"]), memo=R.memo(it), traps=traps, texts=texts, n=len(order),
                               example=", ".join('"keep"' for _ in it["traps"]))


def parse_judge(raw, order, k):
    """Map T1..Tn back to (condition, writer); raise unless every text has k valid categories."""
    got = {t["id"].strip(): t for t in R.first_json(raw)["texts"]}
    out = {}
    for i, (c, w) in enumerate(order):
        t = got[f"T{i + 1}"]
        if len(t["traps"]) != k or any(g not in CATS for g in t["traps"]) or int(t["extra_flags"]) < 0:
            raise ValueError(f"bad judgment T{i + 1}: {t}")
        out[f"{c}/{w}"] = {"traps": t["traps"], "extra_flags": int(t["extra_flags"])}
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

    its = memos(pilot)
    jobs = [(it, "codex") for it in its] + [(it, "grok") for it in its if it["id"] in JUDGE_SAMPLE]
    R.pmap(one, jobs, workers=4)


# ---------- analysis ----------

def rates(pairs):
    """pairs: [(answer, gold)]. R.rates counts a correct E as both right and abstain, so this one splits them."""
    n = len(pairs)
    if not n:
        return None
    ok = sum(a == g for a, g in pairs)
    mis = sum(a != g and a != "E" for a, g in pairs)
    ab = sum(a == "E" and g != "E" for a, g in pairs)
    return {"acc": ok / n, "misread": mis / n, "abstain": ab / n, "n": n}


SUBSETS = {"all": lambda k, g: True, "trap": lambda k, g: k != "none", "nontrap": lambda k, g: k == "none",
           "trap_nonE": lambda k, g: k != "none" and g != "E", **{x: (lambda k, g, x=x: k == x) for x in KINDS}}


def pairs(rec, subset, drop=frozenset()):
    keep = SUBSETS[subset]
    return [(a, g) for a, g, k, q in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
            if keep(k, g) and q not in drop]


def paired(mx, my):
    ids = sorted(i for i in set(mx) & set(my) if mx[i] is not None and my[i] is not None)
    if not ids:
        return None
    m, lo, hi = R.boot([mx[i] - my[i] for i in ids])
    return {"memos": len(ids), "diff": round(m, 3), "ci95": [round(lo, 3), round(hi, 3)]}


def r3(d):
    return None if d is None else {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def cmd_analyze(pilot=False):
    its = {it["id"]: it for it in memos()}
    drop = balance(list(its.values()))
    ans = {}  # (c, w, r) -> {mid: rec}
    for c in R.CONDITIONS:
        for w in R.WRITERS:
            for r in READERS:
                d = OUT / "answers" / c / w / r
                ans[(c, w, r)] = {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("M*.json"))}

    def pooled(c, r, subset, ws=R.WRITERS):
        return rates([x for w in ws for rec in ans[(c, w, r)].values() for x in pairs(rec, subset, drop)])

    def per_memo(c, r, subset, metric, drop=drop):
        out = {}
        for mid in its:
            ps = [x for w in R.WRITERS if mid in ans[(c, w, r)] for x in pairs(ans[(c, w, r)][mid], subset, drop)]
            out[mid] = rates(ps)[metric] if ps else None
        return out

    summary = {}
    for c in R.CONDITIONS:
        texts = [text_f(c, w, mid).read_text() for w in R.WRITERS for mid in ans[(c, w, "grok")]]
        summary[c] = {r: {s: r3(pooled(c, r, s)) for s in ("all", "trap", "nontrap", "trap_nonE")} for r in READERS}
        summary[c]["grok_by_kind"] = {k: r3(pooled(c, "grok", k)) for k in KINDS}
        summary[c]["grok_by_writer"] = {w: {s: r3(pooled(c, "grok", s, [w])) for s in ("all", "trap")}
                                        for w in R.WRITERS}
        summary[c]["texts"] = len(texts)
        summary[c]["chars_mean"] = round(sum(map(len, texts)) / len(texts)) if texts else None
        summary[c]["texts_with_kakunin"] = sum(bool(FLAG_RE.search(t)) for t in texts)
        summary[c]["kakunin_count"] = sum(len(FLAG_RE.findall(t)) for t in texts)
        summary[c]["kakunin_per_text"] = round(summary[c]["kakunin_count"] / len(texts), 3) if texts else None

    tests = {}
    for x, y in COMPARE:
        for r, s, m in (("grok", "trap", "misread"), ("haiku", "trap", "misread"), ("grok", "trap_nonE", "misread"),
                        ("grok", "alias", "acc"), ("grok", "nontrap", "acc"), ("grok", "trap", "acc")):
            tests[f"{r} {s} {m} {x}-{y}"] = paired(per_memo(x, r, s, m), per_memo(y, r, s, m))

    judge = {who: {p.stem: json.loads(p.read_text()) for p in sorted((OUT / "judge" / who).glob("M*.json"))}
             for who in JUDGES}
    handling = {}
    for c in R.CONDITIONS:
        cells = [(mid, j[f"{c}/{w}"]) for mid, j in judge[JUDGES[0]].items() for w in R.WRITERS]
        by_kind = {k: [cell["traps"][i] for mid, cell in cells for i, t in enumerate(its[mid]["traps"])
                       if t["kind"] == k] for k in KINDS}
        cats = [g for v in by_kind.values() for g in v]
        handling[c] = {"texts": len(cells),
                       "dist": {k: round(cats.count(k) / len(cats), 3) for k in CATS} if cats else None,
                       "by_kind": {k: {x: v.count(x) for x in CATS} for k, v in by_kind.items()},
                       "texts_flagging_a_nonalias_trap": sum(
                           any(g == "flag" and its[mid]["traps"][i]["kind"] != "alias"
                               for i, g in enumerate(cell["traps"])) for mid, cell in cells),
                       "extra_flags_total": sum(cell["extra_flags"] for _, cell in cells),
                       "extra_flags_per_text": round(sum(cell["extra_flags"] for _, cell in cells) / len(cells), 3)
                       if cells else None}
    # exploratory (not pre-registered): judged handling of a trap x Grok's answer on that trap's question
    by_cat = {}
    for mid, j in judge[JUDGES[0]].items():
        for key, cell in j.items():
            c, w = key.split("/")
            rec = ans[(c, w, "grok")].get(mid)
            q_trap = {q["qid"]: q["trap"] for q in its[mid]["questions"]}
            for a, g, k, qid in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"]) if rec else ():
                if k != "none" and qid not in drop:
                    by_cat.setdefault(k, {}).setdefault(cell["traps"][q_trap[qid]], []).append((a, g))
    # exploratory: the balance step dropped E-gold questions only because Grok filtered out most alias questions
    nobal = {c: {r: r3(rates([x for w in R.WRITERS for rec in ans[(c, w, r)].values() for x in pairs(rec, "trap")]))
                 for r in READERS} for c in R.CONDITIONS}
    nobal_tests = {f"{r} trap misread {x}-{y}": paired(per_memo(x, r, "trap", "misread", frozenset()),
                                                       per_memo(y, r, "trap", "misread", frozenset()))
                   for x, y in COMPARE for r in READERS}
    explore = {"grok_trap_by_kind_and_judged_handling": {k: {x: r3(rates(v)) for x, v in sorted(d.items())}
                                                         for k, d in sorted(by_cat.items())},
               "no_balance_trap": nobal, "no_balance_tests": nobal_tests}

    j1, j2 = judge[JUDGES[0]], judge[JUDGES[1]]
    both = sorted(set(j1) & set(j2))
    cat_pairs = [(a, b) for mid in both for key in j1[mid] for a, b in zip(j1[mid][key]["traps"], j2[mid][key]["traps"])]
    ext_pairs = [(j1[mid][key]["extra_flags"], j2[mid][key]["extra_flags"]) for mid in both for key in j1[mid]]
    agreement = {"memos": len(both), "trap_cells": len(cat_pairs),
                 "category_agreement": round(sum(a == b for a, b in cat_pairs) / len(cat_pairs), 3) if cat_pairs else None,
                 "flag_agreement": round(sum((a == "flag") == (b == "flag") for a, b in cat_pairs) / len(cat_pairs), 3)
                 if cat_pairs else None,
                 "extra_flags_exact": round(sum(a == b for a, b in ext_pairs) / len(ext_pairs), 3) if ext_pairs else None,
                 "extra_flags_total": [sum(a for a, _ in ext_pairs), sum(b for _, b in ext_pairs)]}

    trap_qs = [q for it in its.values() for q in it["questions"] if q["kind"] != "none" and q["qid"] not in drop]
    questions = {"memos": len(its), "kept": sum(len(it["questions"]) for it in its.values()) - len(drop),
                 "trap": len(trap_qs), "trap_gold_E": sum(q["answer"] == "E" for q in trap_qs),
                 "trap_by_kind": {k: sum(q["kind"] == k for q in trap_qs) for k in KINDS},
                 "nontrap": sum(q["kind"] == "none" for it in its.values() for q in it["questions"]),
                 "balance_dropped": sorted(drop)}
    base = summary["base"]["grok"]["all"]
    rep = {"questions": questions, "filter": json.loads((OUT / "filter-log.json").read_text()),
           "ceiling_broken": bool(base and (base["acc"] <= 0.95 or base["misread"] >= 0.03)),
           "summary": summary, "tests": tests, "judge_handling": handling, "judge_agreement": agreement,
           "exploratory": explore}
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / ("report-pilot.json" if pilot else "report.json")).write_text(out)
    print(out)


def selftest():
    assert rates([("E", "E"), ("A", "E"), ("E", "B"), ("C", "C")]) == {
        "acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert rates([]) is None
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "E", "trap": 0}
    sq = shuffle(q, "k")
    assert sq["answer"] == "E" and sorted(sq[k] for k in "ABCD") == list("abcd")
    sq = shuffle({**q, "answer": "C", "trap": -1}, "k")
    assert sq[sq["answer"]] == "c"
    traps = [{"kind": k, "fact": i} for i, k in enumerate(KINDS)]
    assert invalid({**q, "trap": 0, "answer": "E"}, traps) is None  # deixis -> E
    assert invalid({**q, "trap": 3, "answer": "E"}, traps) is None  # abbrev -> E
    assert invalid({**q, "trap": 0, "answer": "B"}, traps) == "deixis gold B"
    assert invalid({**q, "trap": 1, "answer": "E"}, traps) == "shared_name gold E"
    assert invalid({**q, "trap": 2, "answer": "A"}, traps) is None
    assert invalid({**q, "trap": -1, "answer": "E"}, traps) == "non-trap gold E"
    assert invalid({**q, "trap": 4, "answer": "E"}, traps) == "trap index"
    assert invalid({**q, "trap": 2, "answer": "A", "B": "메모에 없다"}, traps) == "mentions memo"
    assert clean_q({"q": "기한은? E. 글만으로는 알 수 없다"})["q"] == "기한은?"
    assert clean_q({"q": "기한은? (E. 글만으로는 알 수 없다.)"})["q"] == "기한은?"
    it = {"facts": ["f"] * 9, "traps": traps, "questions": [{"trap": t} for t in (0, 1, 2, 3, -1, -1, -1)]}
    assert problems(it) == []
    assert problems({**it, "facts": ["그거 확인 필요"] * 9}) == ["flag mark in memo"]
    assert problems({**it, "questions": it["questions"][:6] + [{"trap": 0}]}) == [
        "questions per trap [2, 1, 1, 1]"]
    # balance: 3 E of 4 trap questions -> drop 2 E (then 1 E of 2); non-trap questions do not count
    bq = [{"qid": f"M01-q{i}", "kind": k, "answer": a}
          for i, (k, a) in enumerate([("deixis", "E"), ("abbrev", "E"), ("deixis", "E"), ("alias", "A"),
                                      ("none", "B")])]
    dropped = balance([{"questions": bq}])
    assert len(dropped) == 2 and dropped <= {"M01-q0", "M01-q1", "M01-q2"}
    assert len(balance([{"questions": bq[1:]}])) == 1  # 2 E of 3 -> 1 E of 2
    assert balance([{"questions": bq[2:]}]) == set()  # 1 E of 2 is exactly half
    rec = {"answers": ["A", "E", "B", "C"], "gold": ["A", "E", "C", "C"], "kind": ["none", "deixis", "alias", "shared_name"],
           "qid": ["q0", "q1", "q2", "q3"]}
    assert pairs(rec, "trap") == [("E", "E"), ("B", "C"), ("C", "C")]
    assert pairs(rec, "trap_nonE") == [("B", "C"), ("C", "C")]
    assert pairs(rec, "alias") == [("B", "C")] and pairs(rec, "nontrap") == [("A", "A")]
    assert pairs(rec, "trap", frozenset({"q1"})) == [("B", "C"), ("C", "C")]
    assert paired({"M01": 0.5, "M02": None}, {"M01": 0.25, "M02": 0.0}) == {"memos": 1, "diff": 0.25,
                                                                           "ci95": [0.25, 0.25]}
    order = [("base", "sonnet"), ("full", "haiku")]
    raw = 'x {"texts": [{"id": "T2", "traps": ["flag"], "extra_flags": 1}, {"id": "T1", "traps": ["invent"], "extra_flags": 0}]}'
    assert parse_judge(raw, order, 1) == {"base/sonnet": {"traps": ["invent"], "extra_flags": 0},
                                          "full/haiku": {"traps": ["flag"], "extra_flags": 1}}
    for bad in ('{"texts": [{"id": "T1", "traps": ["invent"], "extra_flags": 0}]}',
                '{"texts": [{"id": "T1", "traps": ["guess"], "extra_flags": 0}, {"id": "T2", "traps": ["flag"], "extra_flags": 0}]}'):
        try:
            parse_judge(bad, order, 1)
            raise AssertionError("parse_judge accepted " + bad)
        except (KeyError, ValueError):
            pass
    assert len(FLAG_RE.findall("확인 필요: 담당자. 기한도 확인이 필요합니다. 확인했다")) == 2
    assert judge_order("M01") == judge_order("M01") and sorted(judge_order("M01")) == sorted(
        (c, w) for c in R.CONDITIONS for w in R.WRITERS)
    assert JUDGE_SAMPLE == ["M01", "M05", "M09", "M13", "M17", "M21"]
    print("selftest ok")


STEPS = {"items": cmd_items, "filter": cmd_filter, "write": cmd_write, "read": cmd_read, "judge": cmd_judge,
         "analyze": cmd_analyze}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=list(STEPS) + ["all", "selftest"])
    ap.add_argument("--pilot", action="store_true", help="genre 0 items; M01-M02 through the pipeline")
    a = ap.parse_args()
    if a.cmd == "selftest":
        selftest()
        sys.exit()
    if a.cmd != "analyze":
        need_env()
    for step in (list(STEPS) if a.cmd == "all" else [a.cmd]):
        log(f"== {step}")
        STEPS[step](a.pilot)
