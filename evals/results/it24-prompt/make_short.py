#!/usr/bin/env python3
"""Add v4.1 short-prompt change groups to a v3 prompts/system-prompt.md, in place.

Usage: python3 -I make_short.py <system-prompt.md> [G1 G2 G3 G4]
Only the short block (<!-- short:start --> to <!-- short:end -->) changes. Each phrase must occur exactly once there.
The wording comes from evals/results/it20-prompt/v4.1-full.diff. G1+G2+G3+G4 must give the v4.1 short block
(short-block hash 74ef1680... in it20-prompt/after.sha256); the run script checks that.
"""
import sys

GROUPS = {
    "G1": [  # 날짜: 실행일·기한 조건과 밝힌 날짜 면제 문장
        ("조건이나 꾸밈말이 어디까지 걸리는지 모르는 문장은",
         "조건이나 꾸밈말이 어디까지 걸리는지, 날짜가 실행일인지 기한인지 모르는 문장은"),
        ('"확인 필요:"로 묻는다. 코드와 수치는',
         '"확인 필요:"로 묻는다. "에"나 "까지"로 밝힌 날짜는 묻지 않는다. 코드와 수치는'),
    ],
    "G2": [("정도·방식 한정어(완전히, 즉시)", "한정어(완전히, 즉시)")],  # 한정어
    "G3": [("k-ste 스킬이 설치돼 있으면 재작성과 검수에 그 스킬을 쓰고",  # 스킬 문장
            "k-ste 스킬이 있으면 재작성과 검수에 쓰고")],
    "G4": [  # 나머지 축약
        ("(README, 런북, PR 설명, 회의록)", "(README, 런북, 회의록)"),
        ("처음 나올 때 괄호로", "처음에 괄호로"),
        ("볼드는 경고에만 쓰고, 섹션 제목은 헤더로 쓴다.", "볼드는 경고에만 쓰고 제목은 헤더로 쓴다."),
        ("창작 글에는 이 규칙을 적용하지 않는다.", "창작 글에는 적용하지 않는다."),
    ],
}

path, groups = sys.argv[1], sys.argv[2:]
text = open(path, encoding="utf-8").read()
start, end = "<!-- short:start -->", "<!-- short:end -->"
assert text.count(start) == 1 and text.count(end) == 1
head, rest = text.split(start)
short, tail = rest.split(end)
for g in groups:
    for old, new in GROUPS[g]:
        assert short.count(old) == 1, (g, old, short.count(old))
        short = short.replace(old, new)
open(path, "w", encoding="utf-8").write(head + start + short + end + tail)
