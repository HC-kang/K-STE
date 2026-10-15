#!/usr/bin/env python3
"""Count reader-visible defects in Korean AI output. Evaluation only, not shipped with the skill.

Usage:
  python3 evals/score.py [-v] DIR [DIR...]   # one row per DIR, sums over *.md files
  python3 evals/score.py --self-test
"""
import re
import sys
from pathlib import Path

FENCE = re.compile(r"```([\w-]*)\n(.*?)(```|\Z)", re.S)
INLINE = re.compile(r"`[^`\n]*`")
HANGUL = re.compile(r"[가-힣]")
HEADER = re.compile(r"^\s*#{1,6}\s")
TITLE = re.compile(r"^\s*#\s")
LIST = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
TABLE = re.compile(r"^\s*\|")
TABLE_RULE = re.compile(r"^\s*\|[-:| ]+\|\s*$")
QUOTE = re.compile(r"^\s*>\s?")
HR = re.compile(r"^\s*([-*_])\1{2,}\s*$")
SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")
TRAIL = re.compile(r"[\s.?!:\"'”’)\]]+$")
QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']*'|‘[^’]*’")
WARNING_BOLD = re.compile(r"\*\*\s*(경고|주의|위험|WARNING|CAUTION)[^*\n]*\*\*")

PATTERNS = {
    "bold": re.compile(r"\*\*[^*\n]+\*\*"),  # counted after legal warning bold is removed (K10)
    "emdash": re.compile(r"[—―]|\s–\s"),
    "emoji": re.compile("[\U0001F300-\U0001FAFF☀-➿]|(?<![\\w:]):[a-z][a-z0-9_+-]*:(?![\\w:])"),
    "tilde_range": re.compile(r"\d[가-힣a-zA-Z%]{0,3}\s*~\s*\d"),
    "double_passive": re.compile(r"(되어|보여|불려|쓰여|잊혀)[지집져진질짐졌]"),
    "jinhaeng": re.compile(r"(진행|실시|수행)(하|했|합|할|해|됩|되|된|됐|돼|됨|중)"),
    "not_but": re.compile(r"(이|가) 아니라"),
}
CLOSER = re.compile(r"(필요|원)하시면|말씀해 ?주|궁금한 (점|사항)|도움이 되(었|셨|길)|더 필요하(시면|신)|좋은 질문|물론입니다")
NARRATION = re.compile(r"(살펴|알아|정리해|설명해|확인해) ?(보겠|드리겠)습니다")
PREAMBLE = re.compile(r"(바꾼|다듬은|줄인|정리한|고친|작성한) (글|문장|버전|내용|공지|답변|메시지)|보낼 (답변|메시지)|초안입니다|다음과 같습니다")
LABEL = re.compile(r"^[^:]{1,20}:\s")
NOMINAL = re.compile(r"(함|됨|음|임|바람)$")
FORMAL = re.compile(r"((?<!아)니다|니까|시오)$")  # 합니다체; "아니다" is 한다체
HAEYO = re.compile(r"[어아해에예세네군래대지게돼봐줘워와나까려]요$|죠$")  # 해요체; not nouns like 필요, 중요
PLAIN = re.compile(r"(다|라|냐|자)$")            # 한다체 (checked after the two above)

# Documents use 한다체 and follow their genre's headers. Replies use 합니다체.
# S8 (marketing) is out of scope. S9 (check mode) quotes the original, so its quoted wording is not a defect.
DOC_SCENARIOS = {"S3", "S4"}
OUT_OF_SCOPE = {"S8"}
QUOTES_ORIGINAL = {"S9": {"double_passive", "jinhaeng", "nominal", "not_but"}}
DEFECT_KEYS = ["bold", "emdash", "title", "header", "hr", "emoji", "tilde_range", "preamble", "closer", "narration",
               "nominal", "fragment", "double_passive", "jinhaeng", "not_but", "style_mixed"]


def strip_code(m):
    # A fence around Korean prose (no language or text/markdown) is a message to paste, not code: score it.
    lang, body = m.group(1).lower(), m.group(2)
    chars = len(re.sub(r"\s", "", body)) or 1
    if lang in ("", "text", "markdown", "md", "plaintext") and len(HANGUL.findall(body)) / chars > 0.2:
        return body
    return "\nCODEBLOCK.\n"  # keeps a section with only a command from looking empty


def sentences(line):
    return [s for s in SENT_SPLIT.split(line.strip()) if s.strip()]


def register_of(sentence):
    end = TRAIL.sub("", QUOTED.sub("", sentence))
    if FORMAL.search(end):
        return "formal"
    if HAEYO.search(end):
        return "haeyo"
    if PLAIN.search(end):
        return "plain"
    return None


def score(text):
    text = INLINE.sub("CODE", FENCE.sub(strip_code, text))
    r = {k: len(p.findall(WARNING_BOLD.sub("", text) if k == "bold" else text)) for k, p in PATTERNS.items()}
    r.update(title=0, header=0, hr=0, closer=0, narration=0, nominal=0, fragment=0, preamble=0, max_eojeol=0)
    reg = {"formal": 0, "haeyo": 0, "plain": 0}
    first = True
    section = None  # sentence count under the current header; None before the first header
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and TITLE.match(lines[0]):
        r["title"] = 1
        lines.pop(0)
    for line in lines:
        if HEADER.match(line):
            # K10: a header over a section of fewer than three sentences is a defect (replies only).
            r["header"] += section is not None and section < 3
            section = 0
            continue
        if HR.match(line):
            r["hr"] += 1
            continue
        if TABLE.match(line):
            if section is not None and not TABLE_RULE.match(line):
                section += 1
            continue
        if not line.strip():
            continue
        is_list = bool(LIST.match(line))
        line = QUOTE.sub("", LIST.sub("", line))
        if first:
            r["preamble"] = int(bool(PREAMBLE.search(line)))
            first = False
        # A list item that states something in 3+ eojeol must be a full sentence; "label: value" is exempt.
        if (is_list and len(line.split()) >= 3 and not LABEL.match(line)
                and not line.rstrip().endswith("?") and register_of(line) is None):
            r["fragment"] += 1
        if section is not None:
            section += len(sentences(line))
        for s in sentences(line):
            end = TRAIL.sub("", s)
            r["closer"] += bool(CLOSER.search(s)) and not end.endswith("시오")
            r["narration"] += bool(NARRATION.search(s))
            r["max_eojeol"] = max(r["max_eojeol"], len(s.split()))
            if not is_list and NOMINAL.search(end):
                r["nominal"] += 1
            kind = register_of(s)
            if kind:
                reg[kind] += 1
    r["header"] += section is not None and section < 3
    r.update(reg)
    r["style_mixed"] = sum(reg.values()) - max(reg.values())
    return r


def register_miss(r, scenario):
    if scenario in OUT_OF_SCOPE or not any(r[k] for k in ("formal", "haeyo", "plain")):
        return 0
    want = "plain" if scenario in DOC_SCENARIOS else "formal"
    return int(max(("formal", "haeyo", "plain"), key=lambda k: r[k]) != want)


def defects(r, scenario=""):
    r["register"] = register_miss(r, scenario)
    if scenario in OUT_OF_SCOPE:
        return 0
    # A document may open with a title and follow its genre's headers; a reply may not (K1, K10).
    skip = QUOTES_ORIGINAL.get(scenario, set()) | ({"title", "header"} if scenario in DOC_SCENARIOS else set())
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
        ("**경고:** 되돌릴 수 없습니다.", "bold", 0),
        ("**주의** 운영 DB입니다.", "bold", 0),
        ("**경고:** A다. **주의:** B다.", "bold", 0),
        ("3~5개를 씁니다.", "tilde_range", 1),
        ("1일~5일에 씁니다.", "tilde_range", 1),
        ("약 ~10%입니다.", "tilde_range", 0),
        ("```\n3~5\n```", "tilde_range", 0),
        ("서버를 확인함.", "nominal", 1),
        ("- 서버를 확인함", "nominal", 0),
        ("| 상태 | 확인함 |", "nominal", 0),
        ("다음과 같습니다. 처음입니다.", "nominal", 0),
        ("결과가 보여집니다.", "double_passive", 1),
        ("작업을 진행했습니다.", "jinhaeng", 1),
        ("작업이 진행됐습니다.", "jinhaeng", 1),
        ("배포를 했습니다. 서버는 정상이다.", "style_mixed", 1),
        ("배포를 했습니다. 서버는 정상입니다.", "style_mixed", 0),
        ("목표가 아니다. 표준이 아니다.", "plain", 2),
        ("목표가 아닙니다.", "formal", 1),
        ("배포를 했습니다. 서버는 정상이에요.", "style_mixed", 1),
        ('확인 필요: "관리자와 담당자". 범위가 정해지지 않았습니다.', "style_mixed", 0),
        ("궁금한 점이 있으면 말씀해 주세요.", "closer", 1),
        ("필요하시면 짧은 버전도 만들어 드릴 수 있습니다.", "closer", 1),
        ("원하시면 표로 정리하겠습니다.", "closer", 1),
        ("필요하면 서버를 재시작하십시오.", "closer", 0),
        ("필요하시면 서버를 재시작하십시오.", "closer", 0),
        ("언제든 롤백할 수 있습니다.", "closer", 0),
        ("문제는 A — B입니다.", "emdash", 1),
        ("문제는 A ― B입니다.", "emdash", 1),
        ("범위는 2020–2024입니다.", "emdash", 0),
        ("본문입니다.\n## 원인\n본문입니다.", "header", 1),
        ("## 원인\n하나입니다. 둘입니다. 셋입니다.\n## 조치\n하나입니다.", "header", 1),
        ("## 원인\n- 하나입니다.\n- 둘입니다.\n- 셋입니다.", "header", 0),
        ("# 제목\n본문입니다.", "title", 1),
        ("# 제목\n본문입니다.", "header", 0),
        ("본문입니다.\n\n---\n\n본문입니다.", "hr", 1),
        ("- 항목\n- 항목", "hr", 0),
        ("캐시가 아니라 DB입니다.", "not_but", 1),
        ("완료했습니다 🎉", "emoji", 1),
        (":rotating_light: 장애입니다.", "emoji", 1),
        ("14:02:30에 시작했습니다.", "emoji", 0),
        ("키는 redis:cache:key입니다.", "emoji", 0),
        ("- 응답 시간이 300ms에서 2.1초로 증가", "fragment", 1),
        ("- 응답 시간이 2.1초로 늘었습니다.", "fragment", 0),
        ("- 김민수(백엔드)", "fragment", 0),
        ("- 배포 도구: ArgoCD 3.1 버전", "fragment", 0),
        ("- 첫 문장이 답, 결과, 상태인가?", "fragment", 0),
        ("쉽게 바꾼 글입니다.\n\n본문입니다.", "preamble", 1),
        ("이 글의 문제점은 다음과 같습니다.\n\n- 항목", "preamble", 1),
        ("PM님께 보낼 답변 초안입니다.", "preamble", 1),
        ("어제 고친 설정이 원인입니다.", "preamble", 0),
        ("배포는 마이그레이션 단계에서 실패했습니다.", "preamble", 0),
        ("하나 둘 셋 넷 다섯입니다.", "max_eojeol", 5),
    ]
    failed = 0
    for text, key, want in cases:
        got = score(text)[key]
        if got != want:
            failed += 1
            print(f"FAIL {key}: want {want}, got {got} :: {text!r}")
    defect_cases = [
        ("배포했습니다. 끝났습니다.", "S3", "register", 1),
        ("배포했다. 끝났다.", "S3", "register", 0),
        ("배포했다. 끝났다.", "S1", "register", 1),
        ("배포했어요. 끝났어요.", "S1", "register", 1),
        ("필요한 것은 확인 필요. 중요.", "S1", "register", 0),
        ("문구입니다.", "S8", "register", 0),
        ("**굵게** 썼다.", "S8", "defects", 0),
        ("보여지며 → 보이며 입니다.", "S9", "defects", 0),
        ("보여지며 → 보이며 입니다.", "S1", "defects", 1),
        ("# 런북\n## 절차\n하나다.", "S4", "defects", 0),
    ]
    for text, sid, key, want in defect_cases:
        r = score(text)
        r["defects"] = defects(r, sid)
        if r[key] != want:
            failed += 1
            print(f"FAIL {key} {sid}: want {want}, got {r[key]} :: {text!r}")
    total = len(cases) + len(defect_cases)
    print(f"{total - failed}/{total} passed")
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
