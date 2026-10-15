#!/usr/bin/env python3
"""Count reader-visible defects in Korean AI output. Evaluation only, not shipped with the skill.

Usage:
  python3 evals/score.py DIR [DIR...]   # one row per DIR, sums over *.md files
  python3 evals/score.py --self-test
"""
import re
import sys
from pathlib import Path

FENCE = re.compile(r"```([\w-]*)\n(.*?)(```|\Z)", re.S)
HANGUL = re.compile(r"[가-힣]")
INLINE = re.compile(r"`[^`\n]*`")
HEADER = re.compile(r"^\s*#{1,6}\s")
LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
TABLE = re.compile(r"^\s*\|")
QUOTE = re.compile(r"^\s*>\s?")
HR = re.compile(r"^\s*([-*_])\1{2,}\s*$")
SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")
TRAIL = re.compile(r"[\s.?!:\"'”’)\]]+$")

PATTERNS = {
    "bold": re.compile(r"\*\*[^*\n]+\*\*"),
    "emdash": re.compile(r"—|\s–\s"),
    "emoji": re.compile("[\U0001F300-\U0001FAFF☀-➿]"),
    "slack_emoji": re.compile(r":[a-z][a-z0-9_+-]*:"),
    "tilde_range": re.compile(r"\d\s*~\s*\d"),
    "double_passive": re.compile(r"(되어|보여|불려|쓰여|잊혀)[지집져진질짐졌]"),
    "jinhaeng": re.compile(r"(진행|실시|수행)(하|했|합|할|해|됩|되|된|중)"),
    "not_but": re.compile(r"(이|가) 아니라"),
}
CLOSER = re.compile(r"(필요|원)하시면|말씀해 ?주|궁금한 (점|사항)|도움이 되(었|셨|길)|더 필요하(시면|신)|언제든(지)? |좋은 질문|물론입니다")
NARRATION = re.compile(r"(살펴|알아|정리해|설명해|확인해) ?(보겠|드리겠)습니다")
PREAMBLE = re.compile(r"(바꾼|다듬은|줄인|정리한|고친|작성한|보낼|제안|초안).{0,20}(입니다|같습니다)$|다음과 같습니다$")
LABEL = re.compile(r"^[^:]{1,20}:\s")
NOMINAL = re.compile(r"(함|됨|음|임|바람)$")
FORMAL = re.compile(r"(니다|니까|시오|세요|어요|아요|해요|에요|예요|죠|까요)$")
PLAIN = re.compile(r"(다|라|냐|자)$")

# Documents use 한다체 and may have headers. Replies use 합니다체.
# S8 (marketing) is out of scope. S9 (check mode) quotes the original, so its quoted wording is not a defect.
DOC_SCENARIOS = {"S3", "S4"}
NO_REGISTER = {"S8"}
OUT_OF_SCOPE = {"S8"}
QUOTES_ORIGINAL = {"S9": {"double_passive", "jinhaeng", "nominal", "not_but"}}
DEFECT_KEYS = ["bold", "emdash", "header", "hr", "emoji", "tilde_range", "preamble", "closer", "narration",
               "nominal", "fragment", "double_passive", "jinhaeng", "not_but", "style_mixed"]


def strip_code(m):
    # A fence around Korean prose (no language or text/markdown) is a message to paste, not code: score it.
    lang, body = m.group(1).lower(), m.group(2)
    chars = len(re.sub(r"\s", "", body)) or 1
    if lang in ("", "text", "markdown", "md", "plaintext") and len(HANGUL.findall(body)) / chars > 0.2:
        return body
    return ""


def sentences(line):
    return [s for s in SENT_SPLIT.split(line.strip()) if s.strip()]


def score(text):
    text = INLINE.sub("CODE", FENCE.sub(strip_code, text))
    r = {k: len(p.findall(text)) for k, p in PATTERNS.items()}
    r["emoji"] += r.pop("slack_emoji")
    r.update(header=0, hr=0, closer=0, narration=0, nominal=0, fragment=0, preamble=0, max_eojeol=0)
    formal = plain = 0
    first = True
    for line in text.splitlines():
        if HEADER.match(line):
            r["header"] += 1
            continue
        if HR.match(line):
            r["hr"] += 1
            continue
        if TABLE.match(line) or not line.strip():
            continue
        is_list = bool(LIST.match(line))
        line = QUOTE.sub("", LIST.sub("", line))
        if first:
            r["preamble"] = int(bool(PREAMBLE.search(TRAIL.sub("", line))))
            first = False
        # A list item that states something in 3+ eojeol must be a full sentence; "label: value" is exempt.
        end_line = TRAIL.sub("", line)
        if (is_list and len(line.split()) >= 3 and not LABEL.match(line)
                and not (FORMAL.search(end_line) or PLAIN.search(end_line))):
            r["fragment"] += 1
        for s in sentences(line):
            end = TRAIL.sub("", s)
            r["closer"] += bool(CLOSER.search(s))
            r["narration"] += bool(NARRATION.search(s))
            r["max_eojeol"] = max(r["max_eojeol"], len(s.split()))
            if not is_list and NOMINAL.search(end):
                r["nominal"] += 1
            if FORMAL.search(end):
                formal += 1
            elif PLAIN.search(end):
                plain += 1
    r["style_mixed"] = min(formal, plain)
    r["formal"], r["plain"] = formal, plain
    return r


def register_miss(r, scenario):
    if scenario in NO_REGISTER or not (r["formal"] or r["plain"]):
        return 0
    return int(r["formal"] > r["plain"]) if scenario in DOC_SCENARIOS else int(r["plain"] > r["formal"])


def defects(r, scenario=""):
    r["register"] = register_miss(r, scenario)
    if scenario in OUT_OF_SCOPE:
        return 0
    skip = QUOTES_ORIGINAL.get(scenario, set()) | ({"header"} if scenario in DOC_SCENARIOS else set())
    return r["register"] + sum(r[k] for k in DEFECT_KEYS if k not in skip)


def report(dirs, verbose=False):
    cols = DEFECT_KEYS + ["register", "defects", "max_eojeol", "chars"]
    print("| dir | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for d in dirs:
        total = dict.fromkeys(cols, 0)
        for f in sorted(Path(d).glob("*.md")):
            text = f.read_text(encoding="utf-8")
            r = score(text)
            r["defects"] = defects(r, f.stem)
            r["chars"] = len(text)
            if verbose:
                print(f"| {f} | " + " | ".join(str(r[c]) for c in cols) + " |")
            for c in cols:
                total[c] = max(total[c], r[c]) if c == "max_eojeol" else total[c] + r[c]
        print(f"| {d} | " + " | ".join(str(total[c]) for c in cols) + " |")


def self_test():
    cases = [
        ("**굵게** 썼습니다.", "bold", 1),
        ("```\n**x**\n```\n본문입니다.", "bold", 0),
        ("`**x**` 입니다.", "bold", 0),
        ("```\n**장애 공유** 결제 API가 느립니다.\n```", "bold", 1),
        ("```python\n# **설명** 한국어 주석입니다\n```", "bold", 0),
        ("3~5개를 씁니다.", "tilde_range", 1),
        ("약 ~10%입니다.", "tilde_range", 0),
        ("```\n3~5\n```", "tilde_range", 0),
        ("서버를 확인함.", "nominal", 1),
        ("- 서버를 확인함", "nominal", 0),
        ("| 상태 | 확인함 |", "nominal", 0),
        ("다음과 같습니다. 처음입니다.", "nominal", 0),
        ("결과가 보여집니다.", "double_passive", 1),
        ("작업을 진행했습니다.", "jinhaeng", 1),
        ("배포를 했습니다. 서버는 정상이다.", "style_mixed", 1),
        ("배포를 했습니다. 서버는 정상입니다.", "style_mixed", 0),
        ("궁금한 점이 있으면 말씀해 주세요.", "closer", 1),
        ("필요하시면 짧은 버전도 만들어 드릴 수 있습니다.", "closer", 1),
        ("원하시면 표로 정리하겠습니다.", "closer", 1),
        ("필요하면 서버를 재시작하십시오.", "closer", 0),
        ("본문입니다.\n\n---\n\n본문입니다.", "hr", 1),
        ("- 항목\n- 항목", "hr", 0),
        ("문제는 A — B입니다.", "emdash", 1),
        ("범위는 2020–2024입니다.", "emdash", 0),
        ("## 원인\n본문입니다.", "header", 1),
        ("캐시가 아니라 DB입니다.", "not_but", 1),
        ("완료했습니다 🎉", "emoji", 1),
        (":rotating_light: 장애입니다.", "emoji", 1),
        ("14:02:30에 시작했습니다.", "emoji", 0),
        ("- 응답 시간이 300ms에서 2.1초로 증가", "fragment", 1),
        ("- 응답 시간이 2.1초로 늘었습니다.", "fragment", 0),
        ("- 김민수(백엔드)", "fragment", 0),
        ("- 배포 도구: ArgoCD 3.1 버전", "fragment", 0),
        ("쉽게 바꾼 글입니다.\n\n본문입니다.", "preamble", 1),
        ("이 글의 문제점은 다음과 같습니다.\n\n- 항목", "preamble", 1),
        ("배포는 마이그레이션 단계에서 실패했습니다.", "preamble", 0),
        ("하나 둘 셋 넷 다섯입니다.", "max_eojeol", 5),
    ]
    failed = 0
    for text, key, want in cases:
        got = score(text)[key]
        if got != want:
            failed += 1
            print(f"FAIL {key}: want {want}, got {got} :: {text!r}")
    for text, sid, want in [("배포했습니다. 끝났습니다.", "S3", 1), ("배포했다. 끝났다.", "S3", 0),
                            ("배포했다. 끝났다.", "S1", 1), ("문구입니다.", "S8", 0)]:
        r = score(text)
        defects(r, sid)
        if r["register"] != want:
            failed += 1
            print(f"FAIL register {sid}: want {want}, got {r['register']} :: {text!r}")
    for text, sid, want in [("**굵게** 썼다.", "S8", 0), ("보여지며 → 보이며 입니다.", "S9", 0),
                            ("보여지며 → 보이며 입니다.", "S1", 1)]:
        if defects(score(text), sid) != want:
            failed += 1
            print(f"FAIL defects {sid}: want {want} :: {text!r}")
    print(f"{len(cases) + 7 - failed}/{len(cases) + 7} passed")
    return failed == 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--self-test"]:
        sys.exit(0 if self_test() else 1)
    verbose = "-v" in args
    dirs = [a for a in args if a != "-v"]
    if not dirs:
        sys.exit(__doc__)
    report(dirs, verbose)
