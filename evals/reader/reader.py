#!/usr/bin/env python3
"""Reader-comprehension eval: LLM reader panels answer multiple-choice questions about texts.

Design and pre-registered hypotheses: evals/reader/README.md.
Usage: python3 evals/reader/reader.py <items|verify|phase0|write|read|analyze> [options]
Outputs are cached under evals/reader/out/; a call is skipped when its output file exists.
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
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
OUT = ROOT / "out"
EMPTY = Path(tempfile.mkdtemp(prefix="kste-reader-"))  # cwd for model CLIs, so no project files load
CODEX_HOME = Path(os.environ.get("KSTE_CODEX_HOME", Path.home() / ".cache/k-ste-eval/codex-home"))
GROK_MODEL = os.environ.get("KSTE_GROK_MODEL", "grok-4.7")
CODEX_MODEL = os.environ.get("KSTE_CODEX_MODEL", "gpt-6-astra")
LIMITS = {k: threading.Semaphore(int(os.environ.get(f"KSTE_LIMIT_{k.upper()}", n)))
          for k, n in (("claude", 6), ("codex", 4), ("grok", 4))}

GENRES = ["전사 공지", "장애 공유(사내 메신저)", "회의록", "운영 절차(런북)", "PR 설명",
          "고객 안내 메일", "사내 규정 변경 안내", "일정 조율 메일"]
CONDITIONS = ["base", "clarity", "short", "full"]
WRITERS = ["sonnet", "haiku"]
READERS = ["grok", "haiku", "haiku-skim"]
PRIMARY = ["grok"]
ROBUST = "codex"  # read only a subset: Codex hit its usage limit in phase 0 (README change log)
PERSONAS = ["비개발 직군(마케팅) 직원", "입사 3개월 차 개발자", "회의 사이에 휴대폰으로 글을 읽는 팀장"]
SKIM_CHARS = 250
E_TEXT = "글만으로는 알 수 없다"
BASE_SYS = "You are a helpful assistant."
CLARITY = "한국어 업무 글은 명확하고 정확하게, 독자가 오해하지 않게 쓴다."
WEEKDAYS = "월화수목금토일"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- model calls ----------

def _run(cmd, stdin=None, env=None, timeout=420):
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=EMPTY, env=env, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exit {p.returncode}: {p.stderr[-400:]}")
    return p.stdout


def claude(prompt, model, system=BASE_SYS):
    with LIMITS["claude"]:
        return _run(["claude", "-p", prompt, "--model", model, "--setting-sources", "", "--strict-mcp-config",
                     "--system-prompt", system, "--tools", ""])


def _codex_home():
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    auth = CODEX_HOME / "auth.json"
    # the shell's active account (Orca sets CODEX_HOME per account); symlink, so no copy of the credential
    src = Path(os.environ.get("KSTE_CODEX_AUTH") or
               Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json")
    if auth.is_symlink() and auth.resolve() != src.resolve():
        auth.unlink()
    if not auth.exists():
        auth.symlink_to(src)
    (CODEX_HOME / "config.toml").write_text(f'model = "{CODEX_MODEL}"\nmodel_reasoning_effort = "low"\n')


def codex(prompt, schema):
    with LIMITS["codex"]:
        _codex_home()
        with tempfile.TemporaryDirectory() as d:
            sf, of = Path(d, "schema.json"), Path(d, "out.json")
            sf.write_text(json.dumps(schema))
            _run(["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-rules", "-s", "read-only",
                  "--output-schema", str(sf), "-o", str(of), "-"], stdin=prompt,
                 env={**os.environ, "CODEX_HOME": str(CODEX_HOME)})
            return of.read_text()


def grok(prompt, system="You are a careful reader. Follow the user message only."):
    with LIMITS["grok"]:
        return _run(["grok", "-p", prompt, "-m", GROK_MODEL, "--system-prompt-override", system, "--tools", "",
                     "--no-subagents", "--disable-web-search", "--max-turns", "1", "--output-format", "plain"])


def call(who, prompt, schema=None, system=BASE_SYS, tries=3):
    for i in range(tries):
        try:
            if who == "codex":
                return codex(prompt, schema)
            if who == "grok":
                return grok(prompt)
            return claude(prompt, who, system)
        except Exception as e:  # ponytail: plain retry, no backoff; rate limits have not bitten yet
            log(f"retry {who} {i + 1}/{tries}: {e}")
    raise RuntimeError(f"{who} failed {tries} times")


def first_json(s):
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", s):
        try:
            return dec.raw_decode(s[m.start():])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no JSON in: {s[:200]}")


def pmap(fn, xs, workers=16):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, xs))


# ---------- items ----------

ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["audience", "request", "facts", "questions"],
        "properties": {
            "audience": {"type": "string"}, "request": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["q", "A", "B", "C", "D", "answer", "facts", "type"],
                "properties": {
                    "q": {"type": "string"}, "A": {"type": "string"}, "B": {"type": "string"},
                    "C": {"type": "string"}, "D": {"type": "string"},
                    "answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "facts": {"type": "array", "items": {"type": "integer"}},
                    "type": {"type": "string", "enum": ["who", "what", "when", "deadline", "condition", "obligation",
                                                        "number", "scope", "cause", "contact", "other"]}}}}}}}}}

ITEM_PROMPT = """너는 독해 평가 문항 출제자다. 장르 "{genre}"의 업무 상황 5개를 만든다. 각 상황은 바쁜 직원이 AI에게 글을 맡기며 건네는 메모다.

- audience: 이 글을 읽을 사람.
- request: AI에게 하는 요청 한 문장. 장르와 독자를 밝힌다. 예: "아래 내용으로 전 직원에게 보낼 사내 메신저 공지를 써 줘."
- facts: 8-12개. 실제 직원이 쓰는 짧은 메모 말투(개조식, 조사 생략)로 쓰되, 메모 자체는 오해할 여지가 없게 쓴다. 회사, 사람, 시스템, 날짜, 시각, 수치는 모두 가상이다. 날짜는 2026년 11월이나 12월이고 "11/12(목)"처럼 요일을 붙인다.
- 독자가 행동하는 데 필요한 정보를 고루 담는다: 누가, 무엇을, 언제 하는지와 언제까지 끝내야 하는지, 어디서, 어떤 조건과 예외에서, 반드시 해야 하는지와 해도 되는지와 하지 않아도 되는지, 수치와 단위, 원인, 문의처.
- questions: 7개. 글을 읽은 독자가 실제로 알아야 하는 것을 묻는다. 각 문항의 정답은 facts만으로 하나로 정해져야 하고, 상식이나 추측으로 맞힐 수 없어야 한다. 보기 A-D 가운데 정답은 하나다. 오답 보기는 같은 메모의 다른 날짜, 다른 사람, 다른 수치, 다른 의무 강도처럼 헷갈릴 만한 것으로 만든다. 정답 위치를 A-D에 고르게 섞는다.
- 문항의 facts에는 정답 근거가 되는 facts의 번호(0부터)를 쓴다. type은 문항이 묻는 정보의 종류다.
- 5개 상황은 회사, 업무 영역, 독자가 서로 달라야 한다. 이전에 만든 상황과 겹치지 않게, 상황마다 고유한 가상 회사명을 쓴다. 이번 묶음의 번호는 {batch}다."""


def fix_weekdays(s):
    def sub(m):
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            w = WEEKDAYS[datetime.date(2026, mo, d).weekday()]
        except ValueError:
            return m.group(0)
        return f"{m.group(1)}/{m.group(2)}({w})"
    return re.sub(r"(\d{1,2})/(\d{1,2})\s*\(([월화수목금토일])\)", sub, s)


def cmd_items(a):
    d = OUT / "items"
    d.mkdir(parents=True, exist_ok=True)

    def one(gi):
        g = GENRES[gi]
        f = d / f"batch{gi}.json"
        if not f.exists():
            f.write_text(call("codex", ITEM_PROMPT.format(genre=g, batch=gi + 1), ITEM_SCHEMA))
        return g, json.loads(f.read_text())["items"]

    n = 0
    for g, items in pmap(one, range(len(GENRES)), workers=4):
        for it in items:
            n += 1
            it = json.loads(fix_weekdays(json.dumps(it, ensure_ascii=False)))
            it.update(id=f"F{n:02d}", genre=g)
            (d / f"{it['id']}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1))
    log(f"items: {n}")


def items(verified=True):
    d = OUT / ("verified" if verified else "items")
    return [json.loads(p.read_text()) for p in sorted(d.glob("F*.json"))]


def qblock(qs):
    return "\n\n".join(f"Q{i + 1}. {q['q']}\nA. {q['A']}\nB. {q['B']}\nC. {q['C']}\nD. {q['D']}\nE. {E_TEXT}"
                       for i, q in enumerate(qs))


def answer_schema(n):
    keys = [f"Q{i + 1}" for i in range(n)]
    return {"type": "object", "additionalProperties": False, "required": keys,
            "properties": {k: {"type": "string", "enum": list("ABCDE")} for k in keys}}


READ_PROMPT = """{persona}
다음 글을 읽고 질문에 답하라. 글에 쓰인 내용만 근거로 고른다. 글만으로 판단할 수 없으면 E를 고른다.

<글>
{text}
</글>

{questions}

출력은 JSON 한 줄이다. 예: {{"Q1": "A", "Q2": "E"}}"""


def ask(reader, text, qs, persona=""):
    if reader == "haiku-skim":
        reader, text = "haiku", text[:SKIM_CHARS] + "\n…(바빠서 여기까지만 읽었다)"
    p = READ_PROMPT.format(persona=persona, text=text, questions=qblock(qs))
    raw = call(reader, p, answer_schema(len(qs)))
    ans = first_json(raw)
    return [str(ans.get(f"Q{i + 1}", "E")).strip()[:1].upper() for i in range(len(qs))]


def shuffle_options(q, key):
    """The generator rotated answers A,B,C,D; reshuffle with a fixed seed so position carries no signal."""
    opts = [q[k] for k in "ABCD"]
    gold = q[q["answer"]]
    random.Random(key).shuffle(opts)
    return {**q, **dict(zip("ABCD", opts)), "answer": "ABCD"[opts.index(gold)]}


def cmd_verify(a):
    d = OUT / "verified"
    d.mkdir(parents=True, exist_ok=True)
    log_f = OUT / "verify-log.json"
    cache = json.loads(log_f.read_text()) if log_f.exists() else {}
    lock = threading.Lock()

    def check(it):
        if it["id"] in cache:
            return cache[it["id"]]
        notes = it["request"] + "\n\n" + "\n".join(f"- {f}" for f in it["facts"])
        r = {"open": {}, "closed": {}}
        for who in ("grok", "haiku"):
            r["open"][who] = ask(who, notes, it["questions"])
            r["closed"][who] = ask(who, it["request"] + "\n(세부 내용 없음)", it["questions"])
        with lock:
            cache[it["id"]] = r
            log_f.write_text(json.dumps(cache, ensure_ascii=False))
        return r

    its = items(verified=False)
    kept_q = dropped_amb = dropped_closed = 0
    for it, r in zip(its, pmap(check, its, workers=8)):
        keep = []
        for i, q in enumerate(it["questions"]):
            if any(r["open"][w][i] != q["answer"] for w in r["open"]):
                dropped_amb += 1
            elif all(r["closed"][w][i] == q["answer"] for w in r["closed"]):
                dropped_closed += 1
            else:
                keep.append(q)
        kept_q += len(keep)
        if len(keep) >= 5:
            keep = [shuffle_options(q, f"{it['id']}-{i}") for i, q in enumerate(keep)]
            (d / f"{it['id']}.json").write_text(json.dumps({**it, "questions": keep}, ensure_ascii=False, indent=1))
        else:
            log(f"drop item {it['id']}: {len(keep)} questions left")
    log(f"questions kept {kept_q}, dropped ambiguous {dropped_amb}, dropped closed-book {dropped_closed}; "
        f"items kept {len(list(d.glob('F*.json')))}/{len(its)}")


# ---------- texts ----------

def system_for(cond):
    if cond == "base":
        return BASE_SYS
    if cond == "clarity":
        return BASE_SYS + "\n\n" + CLARITY
    src = (REPO / "prompts/system-prompt.md").read_text()
    block = re.search(rf"<!-- {cond}:start -->\n(.*?)<!-- {cond}:end -->", src, re.S).group(1)
    return BASE_SYS + "\n\n" + block


def memo(it):
    return it["request"] + "\n\n" + "\n".join(f"- {f}" for f in it["facts"])


def cmd_write(a):
    jobs = [(it, c, w) for it in items() for c in CONDITIONS for w in WRITERS]

    def one(job):
        it, c, w = job
        f = OUT / "texts" / c / w / f"{it['id']}.md"
        if f.exists():
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(call(w, memo(it), system=system_for(c)))

    pmap(one, jobs, workers=12)
    log(f"texts: {len(jobs)}")


PHASE0_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["clean", "flawed", "defects"],
    "properties": {
        "clean": {"type": "string"}, "flawed": {"type": "string"},
        "defects": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "questions"],
            "properties": {"kind": {"type": "string"},
                           "questions": {"type": "array", "items": {"type": "integer"}}}}}}}

PHASE0_PROMPT = """아래 메모로 요청된 글을 두 판으로 쓴다.

- clean: 메모의 모든 사실을 빠짐없이, 오해할 여지 없이 담은 글.
- flawed: clean과 거의 같은 글이되, 아래 결함 가운데 서로 다른 3개를 넣는다. 결함은 실제 업무 글에서 흔히 생기는 자연스러운 실수처럼 보여야 한다. 사실을 새로 지어내지 않는다.
  1. 그때까지 끝낼 일(기한)을 그날 하는 일처럼 "~에"로 쓰거나, 그날 하는 일을 "~까지"로 쓴다.
  2. 누가 하는지(행위자, 담당자)를 뺀다.
  3. 의무 강도를 바꾼다("해야 한다"를 "권장한다"나 "해도 된다"로, 또는 반대로).
  4. 무엇을 했는지 대상 없이 "처리했다", "반영했다", "조치했다"로 쓴다.
  5. 서로 다른 두 날짜를 "~부터 ~까지" 한 기간으로 묶는다.
- 결함은 아래 독해 문항 가운데 서로 다른 문항의 정답에 영향을 주는 사실에 넣는다.
- defects: flawed에 넣은 결함마다 kind(위 번호)와, 그 결함 때문에 독자가 정답을 고르기 어려워지는 문항 번호(Q 뒤의 숫자)를 쓴다.

메모:
{memo}

독해 문항(글에는 쓰지 않는다):
{questions}"""


def cmd_phase0(a):
    sel = phase0_items()
    d = OUT / "phase0"

    def gen(it):
        f = d / "gen" / f"{it['id']}.json"
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(call("codex", PHASE0_PROMPT.format(memo=memo(it), questions=qblock(it["questions"])),
                              PHASE0_SCHEMA))
        return it, json.loads(f.read_text())

    gens = pmap(gen, sel, workers=4)
    jobs = [(it, g, v, r) for it, g in gens for v in ("clean", "flawed") for r in READERS + [ROBUST]]
    pmap(lambda j: read_one(j[0], j[1][j[2]], j[3], d / "answers" / j[2] / j[3] / f"{j[0]['id']}.json"), jobs)
    log(f"phase0 answers: {len(jobs)}")


def phase0_items():
    its = items()
    by_genre = {}
    for it in its:
        by_genre.setdefault(it["genre"], []).append(it)
    sel = [g[0] for g in by_genre.values()] + [g[1] for g in by_genre.values() if len(g) > 1]
    return sel[:12]


def persona_for(key):
    return "너는 " + PERSONAS[int(hashlib.md5(key.encode()).hexdigest(), 16) % len(PERSONAS)] + "이다. 평소처럼 읽는다."


def read_one(it, text, reader, f):
    if f.exists():
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    ans = ask(reader, text, it["questions"], persona_for(f"{f}"))
    f.write_text(json.dumps({"answers": ans, "gold": [q["answer"] for q in it["questions"]]}))


def cmd_read_codex(a):
    """Robustness check: Codex reads base and full texts from the Sonnet writer only."""
    its = {it["id"]: it for it in items()}
    jobs = [(its[tf.stem], tf.read_text(), ROBUST, OUT / "answers" / c / "sonnet" / ROBUST / f"{tf.stem}.json")
            for c in ("base", "full") for tf in sorted((OUT / "texts" / c / "sonnet").glob("F*.md"))]
    pmap(lambda j: read_one(*j), jobs, workers=4)


def cmd_read(a):
    its = {it["id"]: it for it in items()}
    jobs = []
    for c in CONDITIONS:
        for w in WRITERS:
            for tf in sorted((OUT / "texts" / c / w).glob("F*.md")):
                for r in READERS:
                    jobs.append((its[tf.stem], tf.read_text(), r, OUT / "answers" / c / w / r / f"{tf.stem}.json"))
    pmap(lambda j: read_one(*j), jobs)
    log(f"answers: {len(jobs)}")


# ---------- rewrite arm (phase 2) ----------

RQ_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["questions"],
             "properties": {"questions": ITEM_SCHEMA["properties"]["items"]["items"]["properties"]["questions"]}}

RQ_PROMPT = """너는 독해 평가 문항 출제자다. 아래 글을 읽은 독자가 실제로 알아야 하는 내용을 묻는 객관식 문항 6개를 만든다.
- 정답은 글만으로 하나로 정해져야 한다. 일반 상식이나 배경지식만으로 맞힐 수 없는 문항을 우선한다(이 글에만 있는 수치, 조건, 순서, 예외, 주체, 이유).
- 보기 A-D 가운데 정답은 하나다. 오답 보기는 글의 다른 내용과 헷갈릴 만한 것으로 만든다.
- facts에는 빈 배열을 쓴다. type은 문항이 묻는 정보의 종류다.

<글>
{text}
</글>"""

REWRITE_REQ = "아래 글을 더 읽기 쉽게 다듬어 줘.\n\n"
RW_CONDITIONS = ["original"] + CONDITIONS


def hangul_ratio(t):
    letters = [c for c in t if c.isalpha()]
    return sum("가" <= c <= "힣" for c in letters) / max(1, len(letters))


def passages():
    out = []
    for sub in ("src", "src-local"):
        for f in sorted((OUT / "rewrite" / sub).glob("*.json")):
            out.append(json.loads(f.read_text()))
    return out


def cmd_ritems(a):
    d = OUT / "rewrite" / "items"
    d.mkdir(parents=True, exist_ok=True)

    def one(ps):
        f = d / f"{ps['id']}.raw.json"
        if not f.exists():
            f.write_text(call("codex", RQ_PROMPT.format(text=ps["text"]), RQ_SCHEMA))
        qs = json.loads(f.read_text())["questions"]
        r = {w: (ask(w, ps["text"], qs), ask(w, "(글 없음)", qs)) for w in ("grok", "haiku")}
        keep = [shuffle_options(q, f"{ps['id']}-{i}") for i, q in enumerate(qs)
                if all(r[w][0][i] == q["answer"] for w in r) and not all(r[w][1][i] == q["answer"] for w in r)]
        if len(keep) >= 4:
            (d / f"{ps['id']}.json").write_text(json.dumps({**ps, "questions": keep}, ensure_ascii=False, indent=1))
        return ps["id"], len(qs), len(keep)

    for pid, n, k in pmap(one, passages(), workers=8):
        log(f"{pid}: kept {k}/{n}")


def ritems():
    return [json.loads(p.read_text()) for p in sorted((OUT / "rewrite" / "items").glob("[KB]*[0-9].json"))]


def rtext(it, c):
    if c == "original":
        return it["text"]
    return (OUT / "rewrite" / "texts" / c / f"{it['id']}.md").read_text()


def cmd_rwrite(a):
    def one(job):
        it, c = job
        f = OUT / "rewrite" / "texts" / c / f"{it['id']}.md"
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(call("sonnet", REWRITE_REQ + it["text"], system=system_for(c)))
    pmap(one, [(it, c) for it in passages() for c in CONDITIONS], workers=6)


def cmd_rread(a):
    jobs = [(it, rtext(it, c), r, OUT / "rewrite" / "answers" / c / r / f"{it['id']}.json")
            for it in ritems() for c in RW_CONDITIONS for r in READERS]
    pmap(lambda j: read_one(*j), jobs)
    log(f"rewrite answers: {len(jobs)}")


# ---------- analysis ----------

def boot(diffs, n=10000, seed=7):
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return sum(diffs) / len(diffs), ms[int(0.025 * n)], ms[int(0.975 * n)]


def rates(recs):
    n = sum(len(r["gold"]) for r in recs)
    ok = sum(a == g for r in recs for a, g in zip(r["answers"], r["gold"]))
    e = sum(a == "E" for r in recs for a in r["answers"])
    return {"acc": ok / n, "misread": (n - ok - e) / n, "abstain": e / n, "n": n}


def load(base, *parts):
    return {p.stem: json.loads(p.read_text()) for p in sorted(Path(base, *parts).glob("[FKB][0-9]*.json"))}


def cmd_analyze(a):
    rep = {}
    p0 = OUT / "phase0"
    if (p0 / "answers").exists():
        its = {it["id"]: it for it in items()}
        gens = {f.stem: json.loads(f.read_text()) for f in (p0 / "gen").glob("[FKB][0-9]*.json")}
        per_item = {}
        for v in ("clean", "flawed"):
            for r in READERS + [ROBUST]:
                for fid, rec in load(p0, "answers", v, r).items():
                    qs = sorted({q - 1 for dfx in gens[fid]["defects"] for q in dfx["questions"]
                                 if 1 <= q <= len(rec["gold"])})
                    sub = [rec["answers"][i] == rec["gold"][i] for i in qs]
                    if sub:
                        per_item.setdefault(fid, {}).setdefault(v, []).extend(sub)
        diffs = [sum(x["clean"]) / len(x["clean"]) - sum(x["flawed"]) / len(x["flawed"])
                 for x in per_item.values() if "clean" in x and "flawed" in x]
        m, lo, hi = boot(diffs)
        rep["phase0"] = {"items": len(diffs), "clean_minus_flawed": round(m, 3), "ci95": [round(lo, 3), round(hi, 3)],
                         "gate_pass": m >= 0.10 and lo > 0}
    if (OUT / "answers").exists():
        res = {}
        for c in CONDITIONS:
            for w in WRITERS:
                for r in READERS:
                    res[(c, w, r)] = load(OUT, "answers", c, w, r)
        summary = {}
        for c in CONDITIONS:
            prim = [rec for w in WRITERS for r in PRIMARY for rec in res[(c, w, r)].values()]
            skim = [rec for w in WRITERS for rec in res[(c, w, "haiku-skim")].values()]
            hk = [rec for w in WRITERS for rec in res[(c, w, "haiku")].values()]
            lens = [len((OUT / "texts" / c / w / f"{fid}.md").read_text())
                    for w in WRITERS for fid in res[(c, w, "grok")]]
            summary[c] = {"primary": rates(prim) if prim else None, "haiku": rates(hk) if hk else None,
                          "skim": rates(skim) if skim else None,
                          "chars_mean": round(sum(lens) / len(lens)) if lens else None}

        def item_metric(c, metric, readers):
            out = {}
            for w in WRITERS:
                for r in readers:
                    for fid, rec in res[(c, w, r)].items():
                        out.setdefault(fid, []).append(rec)
            return {fid: rates(v)[metric] for fid, v in out.items()}

        tests = {}
        for name, (x, y, metric, readers) in {
            "H1 acc full-base": ("full", "base", "acc", PRIMARY),
            "H2 misread base-full": ("base", "full", "misread", PRIMARY),
            "H3 acc short-base": ("short", "base", "acc", PRIMARY),
            "H4 acc full-clarity": ("full", "clarity", "acc", PRIMARY),
            "acc clarity-base": ("clarity", "base", "acc", PRIMARY),
            "skim acc full-base": ("full", "base", "acc", ["haiku-skim"]),
            "haiku acc full-base": ("full", "base", "acc", ["haiku"]),
        }.items():
            mx, my = item_metric(x, metric, readers), item_metric(y, metric, readers)
            ids = sorted(set(mx) & set(my))
            if ids:
                m, lo, hi = boot([mx[i] - my[i] for i in ids])
                tests[name] = {"items": len(ids), "diff": round(m, 3), "ci95": [round(lo, 3), round(hi, 3)]}
        cx = {c: load(OUT, "answers", c, "sonnet", ROBUST) for c in ("base", "full")}
        ids = sorted(set(cx["base"]) & set(cx["full"]))
        if ids:
            m, lo, hi = boot([rates([cx["full"][i]])["acc"] - rates([cx["base"][i]])["acc"] for i in ids])
            tests["codex acc full-base (sonnet writer)"] = {"items": len(ids), "diff": round(m, 3),
                                                            "ci95": [round(lo, 3), round(hi, 3)]}
        rep["summary"], rep["tests"] = summary, tests
    rw = OUT / "rewrite" / "answers"
    if rw.exists():
        def rmetric(c, readers):
            out = {}
            for r in readers:
                for fid, rec in load(rw, c, r).items():
                    out.setdefault(fid, []).append(rec)
            return {fid: rates(v)["acc"] for fid, v in out.items()}
        rsum, rtests = {}, {}
        for c in RW_CONDITIONS:
            recs = [rec for r in PRIMARY for rec in load(rw, c, r).values()]
            if recs:
                rsum[c] = rates(recs)
        orig = rmetric("original", PRIMARY)
        for c in CONDITIONS:
            mc = rmetric(c, PRIMARY)
            ids = sorted(set(mc) & set(orig))
            if ids:
                m, lo, hi = boot([mc[i] - orig[i] for i in ids])
                rtests[f"acc {c}-original"] = {"items": len(ids), "diff": round(m, 3), "ci95": [round(lo, 3), round(hi, 3)],
                                               "noninferior_3pp": lo > -0.03}
        rep["rewrite_summary"], rep["rewrite_tests"] = rsum, rtests
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    (OUT / "report.json").write_text(out)
    print(out)


def selftest():
    assert fix_weekdays("마감 11/20(월)") == "마감 11/20(금)"
    assert first_json('text {"Q1": "A"} tail') == {"Q1": "A"}
    assert rates([{"answers": ["A", "E", "C"], "gold": ["A", "B", "B"]}]) == {
        "acc": 1 / 3, "misread": 1 / 3, "abstain": 1 / 3, "n": 3}
    m, lo, hi = boot([0.1] * 10)
    assert abs(m - 0.1) < 1e-9 and abs(lo - 0.1) < 1e-9
    q = {"q": "x", "A": "a", "B": "b", "C": "c", "D": "d", "answer": "C"}
    sq = shuffle_options(q, "k")
    assert sq[sq["answer"]] == "c" and sorted(sq[k] for k in "ABCD") == list("abcd")
    assert hangul_ratio("한국어 text") > 0.4 and hangul_ratio("English only") == 0
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["items", "verify", "phase0", "write", "read", "read-codex", "ritems", "rwrite", "rread",
                                    "analyze", "selftest"])
    a = ap.parse_args()
    {"items": cmd_items, "verify": cmd_verify, "phase0": cmd_phase0, "write": cmd_write, "read": cmd_read,
     "read-codex": cmd_read_codex, "ritems": cmd_ritems, "rwrite": cmd_rwrite, "rread": cmd_rread,
     "analyze": cmd_analyze, "selftest": lambda _: selftest()}[a.cmd](a)
