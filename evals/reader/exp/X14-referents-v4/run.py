#!/usr/bin/env python3
"""X14-referents-v4: does full-v4 (K15 date sentences) raise referent-trap misreads? Large same-run sample.

X8's 24 memos plus 48 new memos of the same design; per memo, full-v3 and full-v4 texts, 2 per writer,
written in the same run with the two conditions interleaved. Grok (primary) and Haiku read them as in X8.
Design and pre-registration: PREREG.md.
Usage: python3 run.py <items|filter|texts|judge|analyze|all|selftest|power> [--pilot]
Every model response is cached under out/; a rerun skips calls whose file exists.
X8, X10 and X12 files (memos, prompt blocks, texts, answers) are read by path; nothing is written there.
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
X12 = EXP.parent / "X12-full-v4-sameday"
CONDS = ["full-v3", "full-v4"]
PROMPT_SHA = {"full-v3": "dbb1b6fbb548888ad6224aacd7c9edd012863907101f394cac49135a99af2fe4",
              "full-v4": "0f11300d1293890f63d6167dcdf1b787f46aa4bb0a04180dac4ac55dd0b3bc24"}  # X10 and X12
REPS = [1, 2]
READERS = ["grok", "haiku"]
KINDS = ["deixis", "shared_name", "alias", "abbrev"]
E_KINDS = {"deixis", "abbrev"}
CATS = ["invent", "keep", "flag", "omit"]
PER_BATCH, BATCHES = 3, 16  # 16 Codex calls x 3 memos = 48 new memos, each genre twice
PILOT = {"items": [0], "texts": ["M01", "M02", "N01", "N02"]}
# earlier runs of X8 memos, read by path (auxiliary pooled analysis): group -> (texts dir, answers dir)
OLD = {"v3-x8": (X8 / "out/texts/full", X8 / "out/answers/full"),
       "v3-x12": (X12 / "out/texts/p1/full-v3", X12 / "out/answers/p1/full-v3"),
       "v4-x10": (X10 / "out/rep/X8/texts/full-v4", X10 / "out/rep/X8/answers/full-v4"),
       "v4-x12": (X12 / "out/texts/p1/full-v4", X12 / "out/answers/p1/full-v4")}
POOLED = {"full-v3": ["full-v3", "v3-x8", "v3-x12"], "full-v4": ["full-v4", "v4-x10", "v4-x12"]}
MARGIN = 0.03  # verdict (i): upper bound below +3%p
FLAG_RE = re.compile(r"확인\s*필요|확인이\s*필요")
DATE_FLAG_LINE_RE = re.compile(r"실행일|기한|마감")
MEMO_MARK_RE = re.compile(r"확인\s*필요|확인이\s*필요|미정|TBD|\?")
E_ECHO_RE = re.compile(r"\s*\(?\s*E\s*[.)]\s*글만으로는\s*알\s*수\s*없다\.?\s*\)?")
BOTH_RE = re.compile(r"모두|둘 다|양쪽|전부")
OVERUSED = ["PM", "DR", "CS팀", "AM", "팀장님", "DB", "서버", "그건", "그거", "거기", "그쪽"]  # X8's trap words
STYLES = ["조사를 줄인 짧은 개조식", "사내 메신저에 여러 줄로 보낸 말투", "짧은 문장을 이어 쓴 보고 말투"]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


# ---------- prompts (X10's frozen blocks, as in X12) ----------

def block_file(c):
    return X10 / "out" / "prompts" / f"{c}.txt"


def system_for(c):
    b = block_file(c).read_text()
    assert sha(b) == PROMPT_SHA[c], f"{c} block differs from X10's frozen one"
    return R.BASE_SYS + "\n\n" + b


def prompt_hashes():
    h = {c: {"path": str(block_file(c).relative_to(R.REPO)), "chars": len(block_file(c).read_text()),
             "sha256": sha(block_file(c).read_text())} for c in CONDS}
    tree = R.system_for("full")[len(R.BASE_SYS) + 2:]  # the working tree's full block (deployed v4)
    h["working_tree_full"] = {"chars": len(tree), "sha256": sha(tree), "equals_full_v4": sha(tree) == PROMPT_SHA["full-v4"]}
    return h


def stamp(name):
    f = OUT / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"), **prompt_hashes()},
                            ensure_ascii=False, indent=1))


# ---------- caches (from X12) ----------

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
    if "X14" not in os.environ["KSTE_CODEX_HOME"]:
        sys.exit("KSTE_CODEX_HOME must be this experiment's own folder (BRIEF.md)")


def limit(who):
    return int(os.environ.get(f"KSTE_LIMIT_{'CLAUDE' if who in R.WRITERS else who.upper()}", 2))


# ---------- items: 48 new memos (X8's design, prompt revised for X8's limitations 1 and 5) ----------

def x8_const(name):
    """A constant of X8's run.py, read from its source."""
    for n in ast.parse((X8 / "run.py").read_text()).body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name:
            return ast.literal_eval(n.value)
    raise KeyError(name)


Q_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["q", "A", "B", "C", "D", "answer", "trap", "facts"],
    "properties": {"q": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"},
                   "C": {"type": "string"}, "D": {"type": "string"},
                   "answer": {"type": "string", "enum": list("ABCDE")},
                   "trap": {"type": "integer"}, "facts": {"type": "array", "items": {"type": "integer"}}}}
ITEM_SCHEMA = {  # X8's
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
- facts: 상황마다 아래 "상황별 지정"의 개수만큼 쓴다. 실제 직원이 쓰는 짧은 메모 말투로 쓰되, 말투는 상황별 지정을 따른다. 회사, 사람, 팀, 시스템, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 요일을 붙인다.
- 독자가 행동하는 데 필요한 정보를 고루 담는다: 누가, 무엇을, 언제, 어디서, 어떤 조건과 예외에서, 의무 강도, 수치와 단위, 원인, 문의처.
- facts 가운데 서로 다른 4개 항목에 대상 함정을 하나씩 넣는다. 함정을 넣을 항목 번호는 "상황별 지정"을 따른다. 아래 4종류를 하나씩 모두 쓴다.
  - deixis: 지시어("그 건", "그 파일", "그 방", "그때", "그분", "이거", "아까 말한 데"처럼)로 대상을 가리키되, 메모의 다른 항목으로 무엇을 가리키는지 정할 수 없게 쓴다. 메모에 그 지시어가 가리킬 만한 후보가 둘 이상 있어야 한다.
  - shared_name: 메모에 서로 다른 두 대상을 함께 쓰고, 함정 항목에서는 둘 다에 쓸 수 있는 같은 말로만 부른다(예: 서울 센터와 대전 센터를 "센터"로, 회계 앱과 인사 앱을 "앱"으로, 본부장 두 명을 "본부장님"으로). 다른 항목으로 어느 쪽인지 정할 수 없어야 한다.
  - alias: 한 대상을 두 이름(정식 이름과 팀에서 부르는 별칭, 약칭, 영문 이름)으로 부른다. 메모만 읽은 사람이 두 이름이 같은 대상이라고 하나로 단정할 수 있어야 한다. 그래서 함정 항목이 아닌 다른 항목 하나가 두 이름이 같은 대상이라는 것을 업무 메모 말투로 밝힌다(예: "새 정산 화면, 팀에서는 그냥 정산판이라고 부름"). 같은 담당자, 같은 일시, 같은 수치가 겹치는 것만으로 잇지 않는다. 함정 항목에서는 두 번째 이름만 쓴다.
  - abbrev: 두 가지로 읽히는 약칭(예: "PO"는 제품 책임자 또는 구매 주문서, "IR"은 투자자 관계 또는 사고 대응, "OT"는 오리엔테이션 또는 초과 근무)을 쓰되, 메모의 다른 항목으로 어느 뜻인지 정할 수 없게 쓴다. 두 뜻 모두 그 상황에서 그럴듯해야 한다.
- 후보(지시어가 가리킬 만한 대상, 같은 말로 부르는 두 대상, 약칭의 두 뜻)를 메모에 적을 때는 함정 항목 바로 앞 항목 하나에 나란히 몰아 두지 않는다. 메모의 여러 항목에 흩어 둔다.
- 이 묶음에서는 이전 묶음에서 많이 쓴 말을 함정에 쓰지 않는다: {overused}. 상황마다 서로 다른 지시어, 공유 이름, 약칭을 쓴다.
- 함정은 바쁜 직원이 남긴 자연스러운 메모처럼 보여야 한다. "미정", "확인 필요", "?", "TBD" 같은 표시를 붙이지 않는다. 함정이 아닌 facts는 오해할 여지가 없게 쓴다.
- traps: 넣은 함정마다 kind, fact(facts 번호, 0부터), what(무엇이 흐린지 한 문장. alias면 두 이름이 가리키는 하나의 대상과, 두 이름을 잇는 항목 번호)을 쓴다.
- questions: 7개. 모든 문항에는 보기 A-D 뒤에 "E. 글만으로는 알 수 없다"가 자동으로 붙는다. 그래서 문항 본문과 보기에 이 문장을 쓰지 않는다. 독자는 메모를 보지 못하고 메모로 쓴 글만 읽는다. 그래서 문항 본문과 보기에 "메모"라는 말을 쓰지 않는다. 문항의 facts에는 근거가 되는 facts 번호를 쓴다.
  - 함정 문항 4개: 함정마다 하나씩, 독자가 그 함정 항목에서 알아야 하는 대상을 묻는다. trap에는 traps의 번호(0-3)를 쓴다.
  - deixis 문항과 abbrev 문항: answer는 E다. A-D에는 글쓴이가 대상을 짐작해서 정했을 때 독자가 고를 구체적인 대상(지시어가 가리킬 만한 후보, 약칭의 두 뜻)을 넣는다. A-D에 "정해지지 않았다", "알 수 없다" 같은 보기를 넣지 않는다.
  - shared_name 문항: answer는 A-D 가운데 하나다. 흐린 말을 그대로 옮긴 보기 하나를 정답으로 한다(예: "'센터'라고만 했고, 서울 센터인지 대전 센터인지는 밝히지 않았다"). 나머지 보기는 두 대상 가운데 하나, 두 대상 모두처럼 더 구체적인 답으로 만든다.
  - alias 문항: answer는 A-D 가운데 하나이고, 두 이름이 가리키는 그 하나의 대상이다. 오답 보기에는 메모의 다른 대상과, 두 이름을 서로 다른 대상으로 본 독자가 고를 답을 넣는다.
  - 함정이 아닌 문항 3개: 함정이 아닌 facts를 묻는다. trap에는 -1을 쓴다. answer는 A-D 가운데 하나이고, facts만으로 하나로 정해지며, 상식이나 추측으로 맞힐 수 없어야 한다. 오답 보기는 같은 메모의 다른 날짜, 사람, 수치, 의무 강도처럼 헷갈릴 만한 것으로 만든다.
- {n}개 상황은 회사, 업무 영역, 독자가 서로 달라야 한다. 상황마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다.

상황별 지정(facts 번호는 0부터, items는 이 순서대로 쓴다):
{specs}"""


def spec(b, k):
    """Fact count, trap positions and memo style of memo k in batch b, from a fixed seed (X8 limitation 5)."""
    rnd = random.Random(f"X14-spec-{b}-{k}")
    n = rnd.randint(8, 12)
    return {"n": n, "pos": dict(zip(KINDS, rnd.sample(range(n), 4))), "style": rnd.choice(STYLES)}


def item_prompt(b):
    specs = "\n".join(f"- 상황 {k + 1}: facts {s['n']}개. " + ", ".join(f"{x}는 facts[{s['pos'][x]}]" for x in KINDS)
                      + f". 말투: {s['style']}." for k, s in ((k, spec(b, k)) for k in range(PER_BATCH)))
    return ITEM_PROMPT.format(genre=R.GENRES[b % len(R.GENRES)], n=PER_BATCH, batch=b + 1,
                              overused=", ".join(f'"{w}"' for w in OVERUSED), specs=specs)


def problems(it, sp=None):
    """Format violations of a generated memo; logged, not filtered (as X8)."""
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
    if sp:
        if len(it["facts"]) != sp["n"]:
            p.append(f"facts {len(it['facts'])} != spec {sp['n']}")
        if {t["kind"]: t["fact"] for t in it["traps"]} != sp["pos"]:
            p.append("trap positions differ from spec")
        used = [w for w in OVERUSED if any(w in it["facts"][t["fact"]] for t in it["traps"])]
        if used:
            p.append(f"overused words in traps {used}")
    return p


def clean_q(q):
    """Strip an echoed 'E. 글만으로는 알 수 없다' from the stem (X1 limitation 4); pure formatting."""
    return {**q, "q": E_ECHO_RE.sub("", q["q"]).strip()}


def invalid(q, traps):
    """Reason a question breaks the format (X8 filtering step 1), or None."""
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


def new_id(b, k):
    return f"N{b * PER_BATCH + k + 1:02d}"


def cmd_items(pilot):
    def one(b):
        raw = cached(OUT / "items" / f"batch{b:02d}.json",
                     lambda: json.loads(R.call("codex", item_prompt(b), ITEM_SCHEMA)))
        for k, it in enumerate(raw["items"][:PER_BATCH]):
            it = json.loads(R.fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=new_id(b, k), genre=R.GENRES[b % len(R.GENRES)], spec=spec(b, k))
            (OUT / "items" / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))

    R.pmap(one, PILOT["items"] if pilot else range(BATCHES), workers=limit("codex"))


def cmd_filter(pilot):
    flog_f = OUT / "filter-log.json"
    flog = json.loads(flog_f.read_text()) if flog_f.exists() else {}

    def one(f):
        it = json.loads(f.read_text())
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
        flog[it["id"]] = {"problems": problems(it, it.get("spec")), "invalid": bad, "generated": len(it["questions"]),
                          "valid": len(qs), "kept": len(keep),
                          "dropped_by_grok": [q["qid"] + " " + q["kind"] for q, a in zip(qs, ans) if a != q["answer"]],
                          "trap_kept": sum(q["kind"] != "none" for q in keep)}
        if any(q["kind"] != "none" for q in keep):
            (OUT / "kept").mkdir(exist_ok=True)
            (OUT / "kept" / f.name).write_text(json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        else:
            log(f"drop memo {it['id']}: no trap question left")

    ids = {new_id(b, k) for b in PILOT["items"] for k in range(PER_BATCH)}
    R.pmap(one, [f for f in sorted((OUT / "items").glob("N*.json")) if not pilot or f.stem in ids],
           workers=limit("grok"))
    flog_f.write_text(json.dumps(flog, ensure_ascii=False, indent=1, sort_keys=True))


def memos(pilot=False):
    """X8's 24 kept memos (by path) and this experiment's kept new memos."""
    its = [json.loads(p.read_text()) for p in sorted((X8 / "out" / "kept").glob("M*.json"))]
    its += [json.loads(p.read_text()) for p in sorted((OUT / "kept").glob("N*.json"))]
    return [it for it in its if not pilot or it["id"] in PILOT["texts"]]


def balance(its, seed):
    """X8 PREREG filtering step 3: qids of E-gold trap questions dropped so E-gold is at most half of trap
    questions. Applied at analysis time; readers answer every kept question."""
    trap = [q for it in its for q in it["questions"] if q["kind"] != "none"]
    e = sorted(q["qid"] for q in trap if q["answer"] == "E")
    random.Random(seed).shuffle(e)
    n_e, n_t, drop = len(e), len(trap), []
    while 2 * n_e > n_t:
        drop.append(e.pop())
        n_e, n_t = n_e - 1, n_t - 1
    return set(drop)


def balance_drop(its):
    """X8 memos keep X8's own balance (same 60 trap questions as X8, X10, X12); new memos are balanced apart."""
    return (balance([it for it in its if it["id"][0] == "M"], "X8-balance")
            | balance([it for it in its if it["id"][0] == "N"], "X14-balance"))


# ---------- texts and reading (X12's interleaving, 2 texts per writer and condition) ----------

def text_f(g, w, rep, mid):
    return OLD[g][0] / w / f"{mid}.md" if g in OLD else OUT / "texts" / g / w / f"r{rep}" / f"{mid}.md"


def ans_f(g, w, rep, r, mid):
    return OLD[g][1] / w / r / f"{mid}.json" if g in OLD else OUT / "answers" / g / w / f"r{rep}" / r / f"{mid}.json"


def units(g):
    return [(g, w, rep) for w in R.WRITERS for rep in ([1] if g in OLD else REPS)]


def persona(w, rep, r, mid):
    """The same persona for both conditions of a (memo, writer, replicate, reader)."""
    return R.persona_for(f"X14/{w}/r{rep}/{r}/{mid}")


def job_order(pilot=False):
    """Memo by memo, writer by writer, replicate by replicate; the two conditions of each pair are adjacent
    and their order is a fixed coin flip."""
    jobs = []
    for it in memos(pilot):
        for w in R.WRITERS:
            for rep in REPS:
                pair = list(CONDS)
                random.Random(f"X14-order-{it['id']}-{w}-{rep}").shuffle(pair)
                jobs += [(it, c, w, rep) for c in pair]
    return jobs


def text_job(job):
    """Write one text, then let Haiku and Grok read it (X12's text_job)."""
    it, c, w, rep = job
    qs, mid = it["questions"], it["id"]
    f = text_f(c, w, rep, mid)
    once(f, lambda: R.call(w, R.memo(it), system=system_for(c)))
    for r in ("haiku", "grok"):
        cached(ans_f(c, w, rep, r, mid),
               lambda r=r: {"answers": R.ask(r, f.read_text(), qs, persona(w, rep, r, mid)),
                            "gold": [q["answer"] for q in qs], "kind": [q["kind"] for q in qs],
                            "qid": [q["qid"] for q in qs]})


def cmd_texts(pilot):
    for c in CONDS:
        system_for(c)
    if not (OUT / "prompt-sha-before.json").exists():
        stamp("prompt-sha-before.json")
    jobs = job_order(pilot)
    log(f"text jobs: {len(jobs)}")
    R.pmap(text_job, jobs, workers=24)
    stamp("prompt-sha-after-pilot.json" if pilot else "prompt-sha-after.json")


# ---------- judging (X8's prompt plus date_flags and quotes) ----------

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["texts"],
    "properties": {"texts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "traps", "extra_flags", "date_flags", "quotes"],
        "properties": {"id": {"type": "string"},
                       "traps": {"type": "array", "items": {"type": "string", "enum": CATS}},
                       "extra_flags": {"type": "integer"}, "date_flags": {"type": "integer"},
                       "quotes": {"type": "array", "items": {"type": "string"}}}}}}}
JUDGE_ADD = ("함정에 붙은 표시는 세지 않는다.",
             "함정에 붙은 표시는 세지 않는다.\n\ndate_flags: extra_flags 가운데 날짜나 시각에 붙은 표시의 수다. "
             "예: 실행일인지 기한인지 묻는 표시, 날짜나 시각이 언제인지 묻는 질문.\n\n"
             "quotes: 함정마다 글에서 그 함정 항목을 옮긴 문장 하나를 그대로 쓴다(150자 이내). 그 항목을 뺐으면 빈 문자열을 쓴다.")
JUDGE_FMT = ('"extra_flags": 0}}]}}. traps에는 함정 번호 순서대로 범주를 하나씩 쓴다.',
             '"extra_flags": 0, "date_flags": 0, "quotes": [{qexample}]}}]}}. traps와 quotes에는 함정 번호 순서대로 하나씩 쓴다.')


def judge_template():
    p = x8_const("JUDGE_PROMPT")
    for old, new in (JUDGE_ADD, JUDGE_FMT):
        assert p.count(old) == 1, old
        p = p.replace(old, new)
    return p


def judge_order(mid):
    """8 texts per memo (X8's batch size): 2 conditions x 2 writers x 2 replicates, shuffled, names hidden."""
    order = [u for c in CONDS for u in units(c)]
    random.Random(f"X14-judge-{mid}").shuffle(order)
    return order


def judge_prompt(it, order):
    traps = "\n".join(f"{i}. ({t['kind']}) 메모 항목 \"{it['facts'][t['fact']]}\": {t['what']}"
                      for i, t in enumerate(it["traps"]))
    texts = "\n\n".join(f"<글 T{i + 1}>\n{text_f(*u, it['id']).read_text()}\n</글 T{i + 1}>" for i, u in enumerate(order))
    k = len(it["traps"])
    return judge_template().format(k=k, memo=R.memo(it), traps=traps, texts=texts, n=len(order),
                                   example=", ".join('"keep"' for _ in range(k)),
                                   qexample=", ".join('"..."' for _ in range(k)))


def ukey(u):
    return f"{u[0]}/{u[1]}/r{u[2]}"


def parse_judge(raw, order, k):
    """Map T1..Tn back to units; raise unless every text has k valid categories and k quotes."""
    got = {t["id"].strip(): t for t in R.first_json(raw)["texts"]}
    out = {}
    for i, u in enumerate(order):
        t = got[f"T{i + 1}"]
        if (len(t["traps"]) != k or any(x not in CATS for x in t["traps"]) or int(t["extra_flags"]) < 0
                or int(t["date_flags"]) < 0 or len(t["quotes"]) != k):
            raise ValueError(f"bad judgment T{i + 1}: {t}")
        out[ukey(u)] = {"traps": t["traps"], "extra_flags": int(t["extra_flags"]), "date_flags": int(t["date_flags"]),
                        "quotes": [str(q) for q in t["quotes"]]}
    return out


def grok_long(prompt, timeout=1200):
    """R.grok with a longer timeout, as in X8 and X12."""
    with R.LIMITS["grok"]:
        return R._run(["grok", "-p", prompt, "-m", R.GROK_MODEL, "--system-prompt-override",
                       "You are a careful reader. Follow the user message only.", "--tools", "", "--no-subagents",
                       "--disable-web-search", "--max-turns", "1", "--output-format", "plain"], timeout=timeout)


def judge_sample(ids):
    """Every 6th memo of the sorted list (12 of 72) is re-judged by Grok."""
    return sorted(ids)[::6]


def cmd_judge(pilot):
    def one(job):
        it, who = job
        mid, order, k = it["id"], judge_order(it["id"]), len(it["traps"])
        if not all(text_f(*u, mid).exists() for u in order):
            log(f"judge: skip {mid}, texts missing")  # rerun judge after texts; cached memos are skipped
            return
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
    sample = ["M01"] if pilot else judge_sample([it["id"] for it in memos()])
    jobs = [(it, "codex") for it in its] + [(it, "grok") for it in its if it["id"] in sample]
    R.pmap(one, jobs, workers=limit("codex") + 2)


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


def verdict(t):
    """Pre-registered: (i) upper < +3%p -> no meaningful increase; (ii) lower > 0 -> increase; else undecided."""
    if not t:
        return None
    lo, hi = r9(t["ci95"][0]), r9(t["ci95"][1])
    no_inc, inc = hi < MARGIN, lo > 0
    label = ("increase_below_3pp" if no_inc and inc else "no_meaningful_increase" if no_inc
             else "increase" if inc else "undecided")
    return {"i_upper_below_3pp": no_inc, "ii_lower_above_0": inc, "label": label}


SUBSETS = {"all": lambda k, g: True, "trap": lambda k, g: k != "none", "nontrap": lambda k, g: k == "none",
           "trap_nonE": lambda k, g: k != "none" and g != "E", **{x: (lambda k, g, x=x: k == x) for x in KINDS}}


def pairs(rec, subset, drop=frozenset()):
    keep = SUBSETS[subset]
    return [(a, g) for a, g, k, q in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"])
            if keep(k, g) and q not in drop]


def load_answers(groups, mids):
    """{(unit, reader): {mid: rec}} for the files that exist."""
    return {(u, r): {m: json.loads(ans_f(*u, r, m).read_text()) for m in mids if ans_f(*u, r, m).exists()}
            for g in groups for u in units(g) for r in READERS}


def per_memo(ans, groups, r, mids, subset, metric, drop):
    out = {}
    for mid in mids:
        ps = [x for g in groups for u in units(g) if mid in ans.get((u, r), {})
              for x in pairs(ans[(u, r)][mid], subset, drop)]
        out[mid] = rates(ps)[metric] if ps else None
    return out


def pooled(ans, groups, r, mids, subset, drop, writers=R.WRITERS):
    return r4(rates([x for g in groups for u in units(g) if u[1] in writers for m in mids
                     if m in ans.get((u, r), {}) for x in pairs(ans[(u, r)][m], subset, drop)]))


def text_stats(texts):
    n = len(texts)
    return {"texts": n, "chars_mean": round(sum(map(len, texts)) / n) if n else None,
            "texts_with_kakunin": sum(bool(FLAG_RE.search(t)) for t in texts),
            "kakunin_per_text": round(sum(len(FLAG_RE.findall(t)) for t in texts) / n, 3) if n else None,
            "kakunin_date_lines_per_text": round(sum(kakunin_date_lines(t) for t in texts) / n, 3) if n else None}


def kakunin_date_lines(t):
    """Machine cross-check of the judged date_flags: lines with '확인 필요' and 실행일/기한/마감."""
    return sum(bool(FLAG_RE.search(ln) and DATE_FLAG_LINE_RE.search(ln)) for ln in t.splitlines())


def write_order():
    """Completion order of the texts (file mtimes): evidence that the two conditions were interleaved."""
    fs = sorted((f.stat().st_mtime, c) for c in CONDS for f in (OUT / "texts" / c).glob("*/r*/*.md"))
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


def load_judge(who):
    return {p.stem: json.loads(p.read_text()) for p in sorted((OUT / "judge" / who).glob("[MN]*.json"))}


def judged_cells(j1, its, c):
    """[(mid, unit, cell)] of condition c."""
    return [(mid, u, j[ukey(u)]) for mid, j in sorted(j1.items()) if mid in its for u in units(c) if ukey(u) in j]


def handling(j1, its):
    out = {}
    for c in CONDS:
        cells = judged_cells(j1, its, c)
        if not cells:
            continue
        by_kind = {k: [cell["traps"][i] for mid, _, cell in cells for i, t in enumerate(its[mid]["traps"]) if t["kind"] == k]
                   for k in KINDS}
        cats = [x for v in by_kind.values() for x in v]
        nonalias = [x for k, v in by_kind.items() if k != "alias" for x in v]
        n = len(cells)
        out[c] = {"texts": n, "dist": {k: round(cats.count(k) / len(cats), 3) for k in CATS},
                  "by_kind": {k: {x: v.count(x) for x in CATS} for k, v in by_kind.items()},
                  "nonalias_invent": [nonalias.count("invent"), len(nonalias)],
                  "trap_flags_per_text": round(sum(cell["traps"].count("flag") for _, _, cell in cells) / n, 3),
                  "nonalias_trap_flags_per_text": round(nonalias.count("flag") / n, 3),
                  "extra_flags_per_text": round(sum(cell["extra_flags"] for _, _, cell in cells) / n, 3),
                  "date_flags_per_text": round(sum(cell["date_flags"] for _, _, cell in cells) / n, 3),
                  "date_flags_above_extra": sum(cell["date_flags"] > cell["extra_flags"] for _, _, cell in cells)}
    return out


def judged_per_memo(j1, its, c, fn):
    """Per-memo mean over the condition's judged texts of fn(mid, cell)."""
    out = {}
    for mid in its:
        vals = [fn(mid, cell) for m, _, cell in judged_cells(j1, its, c) if m == mid]
        out[mid] = sum(vals) / len(vals) if vals else None
    return out


JUDGED_METRICS = {
    "nonalias_invent_rate": lambda its: lambda mid, cell: (
        sum(x == "invent" for x, t in zip(cell["traps"], its[mid]["traps"]) if t["kind"] != "alias")
        / sum(t["kind"] != "alias" for t in its[mid]["traps"])),
    "trap_flags": lambda its: lambda mid, cell: cell["traps"].count("flag"),
    "nonalias_trap_flags": lambda its: lambda mid, cell: sum(
        x == "flag" for x, t in zip(cell["traps"], its[mid]["traps"]) if t["kind"] != "alias"),
    "extra_flags": lambda its: lambda mid, cell: cell["extra_flags"],
    "date_flags": lambda its: lambda mid, cell: min(cell["date_flags"], cell["extra_flags"]),
    "nondate_extra_flags": lambda its: lambda mid, cell: cell["extra_flags"] - min(cell["date_flags"], cell["extra_flags"]),
}


def agreement(j1, j2):
    both = sorted(set(j1) & set(j2))
    ks = [(m, k) for m in both for k in j2[m] if k in j1[m]]
    cp = [(a, b) for m, k in ks for a, b in zip(j1[m][k]["traps"], j2[m][k]["traps"])]
    if not cp:
        return None
    pair = lambda f: [(j1[m][k][f], j2[m][k][f]) for m, k in ks]  # noqa: E731
    return {"memos": len(both), "texts": len(ks), "trap_cells": len(cp),
            "category": round(sum(a == b for a, b in cp) / len(cp), 3),
            "flag": round(sum((a == "flag") == (b == "flag") for a, b in cp) / len(cp), 3),
            "invent": round(sum((a == "invent") == (b == "invent") for a, b in cp) / len(cp), 3),
            **{f"{f}_exact": round(sum(a == b for a, b in pair(f)) / len(ks), 3) for f in ("extra_flags", "date_flags")},
            **{f"{f}_total": [sum(a for a, _ in pair(f)), sum(b for _, b in pair(f))] for f in ("extra_flags", "date_flags")}}


def misreads(ans, j1, its, drop):
    """Every Grok misread on a trap question of this run's texts, with the judged handling and the quoted sentence."""
    out = []
    for c in CONDS:
        for u in units(c):
            for mid, rec in sorted(ans.get((u, "grok"), {}).items()):
                qmap = {q["qid"]: q for q in its[mid]["questions"]}
                cell = j1.get(mid, {}).get(ukey(u))
                for a, g, k, qid in zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"]):
                    if k == "none" or qid in drop or a == g or a == "E":
                        continue
                    q, ti = qmap[qid], qmap[qid]["trap"]
                    out.append({"cond": c, "unit": ukey(u), "mid": mid, "qid": qid, "kind": k, "answer": a,
                                "answer_text": q[a], "gold_text": "E" if g == "E" else q[g],
                                "both": bool(BOTH_RE.search(q[a])),
                                "judged": cell["traps"][ti] if cell else None, "quote": cell["quotes"][ti] if cell else None})
    return out


def misread_traps_md(ans, j1, its, drop, mis):
    """For every trap with a misread: the 8 texts' quoted sentences, judged handling and Grok's answer."""
    lines = ["# X14 오독이 난 함정의 문장 (탐색, run.py analyze가 만든다)", ""]
    for mid, qid in sorted({(m["mid"], m["qid"]) for m in mis}):
        q = next(x for x in its[mid]["questions"] if x["qid"] == qid)
        t = its[mid]["traps"][q["trap"]]
        lines += [f"## {qid} ({t['kind']})", "", f"- 메모 항목: {its[mid]['facts'][t['fact']]}",
                  f"- 문항: {q['q']} 정답: {q['answer']}" + ("" if q["answer"] == "E" else f" ({q[q['answer']]})"), ""]
        for c in CONDS:
            for u in units(c):
                rec, cell = ans.get((u, "grok"), {}).get(mid), j1.get(mid, {}).get(ukey(u))
                a = rec["answers"][rec["qid"].index(qid)] if rec else "-"
                mark = "오독" if a not in (q["answer"], "E", "-") else ""
                lines.append(f"- {ukey(u)} | 답 {a} {mark} | 판정 {cell['traps'][q['trap']] if cell else '-'} | "
                             f"{(cell['quotes'][q['trap']] if cell else '').replace(chr(10), ' ')}")
        lines.append("")
    return "\n".join(lines)


def cmd_analyze(pilot=False):
    all_its = memos()
    its = {it["id"]: it for it in memos(pilot)}
    mids = sorted(its)
    drop = balance_drop(all_its)  # the balance rule always sees every memo of a set
    x8, new = [m for m in mids if m[0] == "M"], [m for m in mids if m[0] == "N"]
    ans = load_answers(CONDS + list(OLD), mids)
    sets = {"all": mids, "x8": x8, "new": new}

    summary = {}
    for c in CONDS:
        texts = [text_f(*u, m).read_text() for u in units(c) for m in mids if text_f(*u, m).exists()]
        summary[c] = {r: {s: pooled(ans, [c], r, mids, s, drop) for s in ("all", "trap", "nontrap", "trap_nonE")}
                      for r in READERS}
        summary[c]["grok_trap_by_set"] = {k: pooled(ans, [c], "grok", v, "trap", drop) for k, v in sets.items()}
        summary[c]["grok_by_kind"] = {k: pooled(ans, [c], "grok", mids, k, drop) for k in KINDS}
        summary[c]["grok_trap_by_writer"] = {w: pooled(ans, [c], "grok", mids, "trap", drop, [w]) for w in R.WRITERS}
        summary[c].update(text_stats(texts))

    def test(gx, gy, r, subset, metric, ids=mids):
        return paired(per_memo(ans, gx, r, ids, subset, metric, drop), per_memo(ans, gy, r, ids, subset, metric, drop))

    v3, v4 = ["full-v3"], ["full-v4"]
    primary = test(v4, v3, "grok", "trap", "misread")
    tests = {"grok trap misread v4-v3 (primary)": primary,
             "haiku trap misread v4-v3": test(v4, v3, "haiku", "trap", "misread"),
             "grok trap misread v4-v3 x8 memos": test(v4, v3, "grok", "trap", "misread", x8),
             "grok trap misread v4-v3 new memos": test(v4, v3, "grok", "trap", "misread", new),
             "grok trap_nonE misread v4-v3": test(v4, v3, "grok", "trap_nonE", "misread"),
             "grok nontrap acc v4-v3": test(v4, v3, "grok", "nontrap", "acc"),
             "grok alias acc v4-v3": test(v4, v3, "grok", "alias", "acc"),
             "grok trap acc v4-v3": test(v4, v3, "grok", "trap", "acc"),
             **{f"grok {k} misread v4-v3": test(v4, v3, "grok", k, "misread") for k in KINDS if k != "alias"}}
    # auxiliary: X8 memos pooled with X8, X10 and X12 texts (both conditions over three runs)
    aux = {"grok trap misread v4-v3 x8 memos, x8+x10+x12+x14": test(POOLED["full-v4"], POOLED["full-v3"], "grok", "trap",
                                                                      "misread", x8),
           "grok trap misread v4-v3 all memos, x8 memos with earlier runs": test(
               POOLED["full-v4"], POOLED["full-v3"], "grok", "trap", "misread"),
           "haiku trap misread v4-v3 all memos, x8 memos with earlier runs": test(
               POOLED["full-v4"], POOLED["full-v3"], "haiku", "trap", "misread"),
           "grok trap misread x14 v3 - x8 run v3 (run-to-run)": test(v3, ["v3-x8"], "grok", "trap", "misread", x8),
           "grok trap misread x14 v4 - x10 run v4 (run-to-run)": test(v4, ["v4-x10"], "grok", "trap", "misread", x8),
           "pooled_counts": {c: {s: pooled(ans, POOLED[c], "grok", sets[s], "trap", drop) for s in ("x8", "all")}
                             for c in CONDS}}

    j1 = load_judge("codex")
    jmet = {k: paired(judged_per_memo(j1, its, "full-v4", f(its)), judged_per_memo(j1, its, "full-v3", f(its)))
            for k, f in JUDGED_METRICS.items()}
    def kakunin(c):  # machine count of "확인 필요" per text, per memo
        return {mid: sum(len(FLAG_RE.findall(text_f(*u, mid).read_text())) for u in units(c)) / len(units(c))
                if all(text_f(*u, mid).exists() for u in units(c)) else None for mid in mids}
    jmet["kakunin_machine"] = paired(kakunin("full-v4"), kakunin("full-v3"))
    by_cat = {}  # exploratory: judged handling x Grok's answer on that trap's question
    for c in CONDS:
        for mid, u, cell in judged_cells(j1, its, c):
            rec = ans[(u, "grok")].get(mid)
            q_trap = {q["qid"]: q["trap"] for q in its[mid]["questions"]}
            for a, g, k, qid in (zip(rec["answers"], rec["gold"], rec["kind"], rec["qid"]) if rec else ()):
                if k != "none" and qid not in drop:
                    by_cat.setdefault(c, {}).setdefault(k, {}).setdefault(cell["traps"][q_trap[qid]], []).append((a, g))
    date_assoc = {}  # exploratory: non-alias invent in texts with and without a judged date flag
    for c in CONDS:
        for has in (True, False):
            cells = [(mid, cell) for mid, _, cell in judged_cells(j1, its, c) if (min(cell["date_flags"], cell["extra_flags"]) > 0) == has]
            na = [x for mid, cell in cells for x, t in zip(cell["traps"], its[mid]["traps"]) if t["kind"] != "alias"]
            date_assoc[f"{c} date_flag={'yes' if has else 'no'}"] = {
                "texts": len(cells), "nonalias_invent": [na.count("invent"), len(na)],
                "nonalias_flag": [na.count("flag"), len(na)]}
    mis = misreads(ans, j1, its, drop)
    mis_sum = {c: {"misreads": sum(m["cond"] == c for m in mis),
                   "both_option": sum(m["cond"] == c and m["both"] for m in mis),
                   "by_judged": {x: sum(m["cond"] == c and m["judged"] == x for m in mis) for x in CATS + [None]},
                   "by_kind": {k: sum(m["cond"] == c and m["kind"] == k for m in mis) for k in KINDS}} for c in CONDS}
    (OUT / ("misreads-pilot.json" if pilot else "misreads.json")).write_text(json.dumps(mis, ensure_ascii=False, indent=1))
    (OUT / ("misread-traps-pilot.md" if pilot else "misread-traps.md")).write_text(misread_traps_md(ans, j1, its, drop, mis))

    questions = {}
    for s, v in sets.items():
        qs = [q for m in v for q in its[m]["questions"] if q["qid"] not in drop]
        tq = [q for q in qs if q["kind"] != "none"]
        questions[s] = {"memos": len(v), "trap": len(tq), "trap_gold_E": sum(q["answer"] == "E" for q in tq),
                        "trap_by_kind": {k: sum(q["kind"] == k for q in tq) for k in KINDS},
                        "nontrap": len(qs) - len(tq)}
    questions["balance_dropped"] = sorted(drop)
    flog_f = OUT / "filter-log.json"
    v3all = summary["full-v3"]["grok"]["all"]
    rep = {"verdict": verdict(primary), "primary": primary, "questions": questions,
           "filter": json.loads(flog_f.read_text()) if flog_f.exists() else None,
           "ceiling_broken_v3": bool(v3all and (v3all["acc"] <= 0.95 or v3all["misread"] >= 0.03)),
           "summary": summary, "tests": tests, "auxiliary_pooled": aux,
           "judge_handling": handling(j1, its), "judge_tests_v4_minus_v3": jmet,
           "judge_agreement_grok_vs_codex": agreement(j1, load_judge("grok")),
           "exploratory": {"grok_trap_by_kind_and_judged_handling": {
               c: {k: {x: r4(rates(v)) for x, v in sorted(d.items())} for k, d in sorted(kd.items())}
               for c, kd in by_cat.items()},
               "nonalias_handling_by_date_flag": date_assoc, "misreads_summary": mis_sum},
           "write_order": write_order(),
           "prompt_sha256": PROMPT_SHA, "prompt_now": prompt_hashes(),
           "prompt_before": json.loads((OUT / "prompt-sha-before.json").read_text())
           if (OUT / "prompt-sha-before.json").exists() else None,
           "prompt_after": json.loads((OUT / "prompt-sha-after.json").read_text())
           if (OUT / "prompt-sha-after.json").exists() else None}
    assert all(rep["prompt_now"][c]["sha256"] == PROMPT_SHA[c] for c in CONDS)
    (OUT / ("report-pilot.json" if pilot else "report.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps({"verdict": rep["verdict"], "primary": primary}, ensure_ascii=False))
    for k, v in tests.items():
        print(k, v)


# ---------- power (PREREG numbers, from X8, X10 and X12 files only) ----------

def fast_ci(d, rnd, n=2000):
    """R.boot's percentile interval with random.choices (the simulation runs thousands of intervals)."""
    k = len(d)
    ms = sorted(sum(rnd.choices(d, k=k)) / k for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def cmd_power(_pilot=False):
    x8 = [it for it in memos() if it["id"][0] == "M"]
    mids, drop = sorted(it["id"] for it in x8), balance(x8, "X8-balance")
    ans = load_answers(list(OLD), mids)
    pm = lambda gs: per_memo(ans, gs, "grok", mids, "trap", "misread", drop)  # noqa: E731
    scen = {  # per-memo v4 - v3 differences of earlier runs
        "two_runs_pooled (2 texts per writer and condition, as X14)": (pm(["v4-x10", "v4-x12"]), pm(["v3-x8", "v3-x12"])),
        "x12_same_run (1 text per writer and condition, pessimistic)": (pm(["v4-x12"]), pm(["v3-x12"]))}
    out = {}
    for name, (x, y) in scen.items():
        d = [x[m] - y[m] for m in mids]
        mu = sum(d) / len(d)
        sd = (sum((v - mu) ** 2 for v in d) / (len(d) - 1)) ** 0.5
        res = {"observed": paired(x, y), "sd_per_memo": round(sd, 4),
               "normal_half_width_72": round(1.96 * sd / 72 ** 0.5, 4), "by_true_diff": {}}
        for delta in (0.0, 0.02, 0.035, 0.05):
            rnd, reps, tally, widths = random.Random(11), 400, {}, []
            c = [v - mu + delta for v in d]
            for _ in range(reps):
                s = [rnd.choice(c) for _ in range(72)]
                lo, hi = fast_ci(s, rnd)
                widths.append(hi - lo)
                lab = verdict({"ci95": [lo, hi]})["label"]
                tally[lab] = tally.get(lab, 0) + 1
            res["by_true_diff"][f"{delta:+.3f}"] = {"verdicts": {k: round(v / reps, 3) for k, v in sorted(tally.items())},
                                                    "median_ci_width": round(sorted(widths)[reps // 2], 4)}
        out[name] = res
    (OUT / "power.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------- selftest ----------

def selftest():
    assert rates([("E", "E"), ("A", "E"), ("E", "B"), ("C", "C")]) == {"acc": 0.5, "misread": 0.25, "abstain": 0.25, "n": 4}
    assert rates([]) is None
    assert r9(-1.2e-18) == 0
    assert paired({"M01": 0.5, "M02": None}, {"M01": 0.25, "M02": 0.0}) == {"memos": 1, "diff": 0.25, "ci95": [0.25, 0.25]}
    # verdict: the four outcomes, exact bounds
    v = lambda lo, hi: verdict({"ci95": [lo, hi]})["label"]  # noqa: E731
    assert v(-0.02, 0.029) == "no_meaningful_increase" and v(-0.02, 0.03) == "undecided"
    assert v(0.001, 0.05) == "increase" and v(0.0, 0.05) == "undecided" and v(0.005, 0.02) == "increase_below_3pp"
    assert v(-1.2e-18, 0.05) == "undecided"
    # prompts: X10's frozen blocks; the working tree's full block is v4
    for c in CONDS:
        assert system_for(c) == R.BASE_SYS + "\n\n" + block_file(c).read_text()
    assert [len(block_file(c).read_text()) for c in CONDS] == [5462, 5611]
    # items: spec is fixed per memo, positions distinct and inside the fact count
    for b in range(BATCHES):
        for k in range(PER_BATCH):
            s = spec(b, k)
            assert s == spec(b, k) and 8 <= s["n"] <= 12 and len(set(s["pos"].values())) == 4
            assert all(0 <= p < s["n"] for p in s["pos"].values()) and s["style"] in STYLES
    p = item_prompt(0)
    assert "상황 3:" in p and "{" not in p.replace("{{", "") and '"PM"' in p and R.GENRES[0] in p
    assert [new_id(b, k) for b, k in ((0, 0), (0, 2), (15, 2))] == ["N01", "N03", "N48"]
    traps = [{"kind": k, "fact": i} for i, k in enumerate(KINDS)]
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "E", "trap": 0}
    assert invalid({**q, "trap": 0}, traps) is None and invalid({**q, "trap": 3}, traps) is None
    assert invalid({**q, "trap": 1}, traps) == "shared_name gold E" and invalid({**q, "trap": -1}, traps) == "non-trap gold E"
    assert invalid({**q, "trap": 2, "answer": "A", "B": "메모에 없다"}, traps) == "mentions memo"
    sq = shuffle({**q, "answer": "C", "trap": -1}, "k")
    assert sq[sq["answer"]] == "c" and shuffle(q, "k")["answer"] == "E"
    assert clean_q({"q": "기한은? (E. 글만으로는 알 수 없다.)"})["q"] == "기한은?"
    it = {"facts": ["f"] * 9, "traps": traps, "questions": [{"trap": t} for t in (0, 1, 2, 3, -1, -1, -1)]}
    sp = {"n": 9, "pos": {k: i for i, k in enumerate(KINDS)}}
    assert problems(it, sp) == []
    assert problems(it, {**sp, "n": 10}) == ["facts 9 != spec 10"]
    assert problems({**it, "facts": ["PM 승인"] + ["f"] * 8}, sp) == ["overused words in traps ['PM']"]
    # memos and balance: X8's 24 memos keep X8's 17 dropped questions (60 trap questions left)
    x8 = [it for it in memos() if it["id"][0] == "M"]
    assert len(x8) == 24 and len(balance(x8, "X8-balance")) == 17
    assert balance_drop(x8) == balance(x8, "X8-balance")
    assert sum(q["kind"] != "none" and q["qid"] not in balance_drop(x8) for it in x8 for q in it["questions"]) == 60
    bq = [{"qid": f"N01-q{i}", "kind": k, "answer": a} for i, (k, a) in
          enumerate([("deixis", "E"), ("abbrev", "E"), ("deixis", "E"), ("alias", "A"), ("none", "B")])]
    assert len(balance([{"id": "N01", "questions": bq}], "s")) == 2
    assert balance_drop(x8 + [{"id": "N01", "questions": bq}]) >= balance(x8, "X8-balance")
    # paths and units: this run's 2 replicates here, earlier runs by path
    assert text_f("full-v4", "haiku", 2, "N05") == OUT / "texts/full-v4/haiku/r2/N05.md"
    assert ans_f("v4-x10", "haiku", 1, "grok", "M01") == X10 / "out/rep/X8/answers/full-v4/haiku/grok/M01.json"
    assert ans_f("v3-x12", "sonnet", 1, "grok", "M01") == X12 / "out/answers/p1/full-v3/sonnet/grok/M01.json"
    assert len(units("full-v3")) == 4 and len(units("v3-x8")) == 2
    for g in OLD:
        assert all(text_f(*u, m).exists() and ans_f(*u, r, m).exists() for u in units(g) for r in READERS
                   for m in (it["id"] for it in x8)), g
    # pooling: per_memo pools every unit of the listed groups
    rec = {"answers": ["A", "E", "B", "C"], "gold": ["A", "E", "C", "C"], "kind": ["none", "deixis", "alias", "shared_name"],
           "qid": ["q0", "q1", "q2", "q3"]}
    assert pairs(rec, "trap") == [("E", "E"), ("B", "C"), ("C", "C")] and pairs(rec, "nontrap") == [("A", "A")]
    assert pairs(rec, "trap", frozenset({"q1"})) == [("B", "C"), ("C", "C")]
    a2 = {(u, "grok"): {} for g in CONDS for u in units(g)}
    a2[(("full-v3", "sonnet", 1), "grok")]["N01"] = rec  # trap: 1 misread of 3
    a2[(("full-v3", "haiku", 2), "grok")]["N01"] = {**rec, "answers": ["A", "A", "B", "C"]}  # 2 of 3
    assert per_memo(a2, ["full-v3"], "grok", ["N01", "N02"], "trap", "misread", frozenset()) == {"N01": 0.5, "N02": None}
    # interleaving: each (memo, writer, replicate) pair is adjacent, both conditions, order varies
    jobs = job_order()
    pairs_ = [jobs[i:i + 2] for i in range(0, len(jobs), 2)]
    assert all({j[1] for j in pr} == set(CONDS) and len({(j[0]["id"], j[2], j[3]) for j in pr}) == 1 for pr in pairs_)
    assert 0.25 < [pr[0][1] for pr in pairs_].count("full-v3") / len(pairs_) < 0.75
    # judging: X8's prompt plus two fields; 8 texts per memo, names hidden
    jt = judge_template()
    assert jt.startswith("아래 메모로 AI 글쓴이 여러 명이") and "date_flags:" in jt and "quotes:" in jt
    order = judge_order("M01")
    assert len(order) == 8 and sorted(order) == sorted(u for c in CONDS for u in units(c)) and order == judge_order("M01")
    old_order = [u for g in ("v3-x8", "v4-x10") for u in units(g)]  # earlier texts exist, so the prompt can be built
    jp = judge_prompt(x8[0], old_order)
    assert jp.count("<글 T") == 4 and "full-v" not in jp and "x8" not in jp and '"quotes": ["...", "...", "...", "..."]' in jp
    raw = ('x {"texts": [{"id": "T2", "traps": ["flag"], "extra_flags": 2, "date_flags": 1, "quotes": ["b"]},'
           ' {"id": "T1", "traps": ["invent"], "extra_flags": 0, "date_flags": 0, "quotes": ["a"]}]}')
    o2 = [("full-v3", "sonnet", 1), ("full-v4", "haiku", 2)]
    assert parse_judge(raw, o2, 1) == {
        "full-v3/sonnet/r1": {"traps": ["invent"], "extra_flags": 0, "date_flags": 0, "quotes": ["a"]},
        "full-v4/haiku/r2": {"traps": ["flag"], "extra_flags": 2, "date_flags": 1, "quotes": ["b"]}}
    for bad in (raw.replace('"quotes": ["a"]', '"quotes": []'), raw.replace('"invent"', '"guess"'),
                '{"texts": [{"id": "T1", "traps": ["keep"], "extra_flags": 0, "date_flags": 0, "quotes": ["a"]}]}'):
        try:
            parse_judge(bad, o2, 1)
            raise AssertionError("parse_judge accepted " + bad)
        except (KeyError, ValueError):
            pass
    assert judge_sample([f"M{i:02d}" for i in range(1, 25)] + [f"N{i:02d}" for i in range(1, 49)]) == [
        "M01", "M07", "M13", "M19", "N01", "N07", "N13", "N19", "N25", "N31", "N37", "N43"]
    jj = {"N01": {"full-v3/sonnet/r1": {"traps": ["flag", "keep"], "extra_flags": 1, "date_flags": 1, "quotes": ["", ""]}}}
    jk = {"N01": {"full-v3/sonnet/r1": {"traps": ["flag", "invent"], "extra_flags": 1, "date_flags": 0, "quotes": ["", ""]}}}
    ag = agreement(jj, jk)
    assert ag["category"] == 0.5 and ag["flag"] == 1.0 and ag["extra_flags_exact"] == 1.0 and ag["date_flags_exact"] == 0.0
    its_ = {"N01": {"traps": [{"kind": "deixis"}, {"kind": "alias"}]}}
    cell = jj["N01"]["full-v3/sonnet/r1"]
    assert JUDGED_METRICS["nonalias_invent_rate"](its_)("N01", {**cell, "traps": ["invent", "invent"]}) == 1.0
    assert JUDGED_METRICS["nonalias_trap_flags"](its_)("N01", cell) == 1
    assert JUDGED_METRICS["nondate_extra_flags"](its_)("N01", {**cell, "date_flags": 3}) == 0
    assert kakunin_date_lines("확인 필요: 11/12가 실행일인지 기한인지\n확인 필요: 담당자\n기한은 11/13") == 1
    assert len(FLAG_RE.findall("확인 필요: 담당자. 기한도 확인이 필요합니다. 확인했다")) == 2
    assert BOTH_RE.search("서울 센터와 대전 센터 모두") and not BOTH_RE.search("서울 센터")
    print("selftest ok")


STEPS = {"items": cmd_items, "filter": cmd_filter, "texts": cmd_texts, "judge": cmd_judge, "analyze": cmd_analyze}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=list(STEPS) + ["all", "selftest", "power"])
    ap.add_argument("--pilot", action="store_true", help="batch 1 items; M01, M02, N01, N02 through the pipeline")
    a = ap.parse_args()
    if a.cmd in ("selftest", "power"):
        (selftest if a.cmd == "selftest" else cmd_power)()
        sys.exit()
    if a.cmd != "analyze":
        need_env()
    for step in (list(STEPS) if a.cmd == "all" else [a.cmd]):
        log(f"== {step}")
        STEPS[step](a.pilot)
