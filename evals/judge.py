#!/usr/bin/env python3
"""Blind judge with an isolated `claude -p` session. The judge never sees the condition name.

Usage: python3 evals/judge.py RESULTS_ROOT [--model opus]
Judges every <model>/<condition>/<SID>.md under RESULTS_ROOT and writes RESULTS_ROOT/judge.jsonl.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCENARIOS = Path(__file__).parent / "scenarios"

MEANING = """You audit a Korean rewrite for meaning preservation. Compare meaning only, never style.

A meaning change is any of these:
1. A fact, cause, number, actor, or next action appears that the original does not contain.
2. A fact, condition, exception, or scope marker (for example 일부, 만, 까지, 반드시, 가능하다면) is missing.
3. Certainty changed: a possibility is stated as fact, or a fact as a possibility.
4. Obligation strength changed: must, recommended, and allowed are swapped.
5. A phrase that the original allows to be read two ways is silently resolved to one reading.
   If the output keeps the original wording for that phrase or explicitly flags it for confirmation, it is not a change.

USER REQUEST (contains the original text):
<<<
{prompt}
>>>

OUTPUT:
<<<
{output}
>>>

Reply with one line of JSON and nothing else:
{{"meaning_changed": true or false, "issues": ["one short sentence per issue"]}}"""

CONCLUSION = """Read the response below. Does its first sentence directly give the answer, the result, or the current status?
A heading, a restatement of the question, a greeting, or a preamble ("다음과 같이 정리했습니다") is not a conclusion.

USER REQUEST:
<<<
{prompt}
>>>

RESPONSE:
<<<
{output}
>>>

Reply with one line of JSON and nothing else:
{{"conclusion_first": true or false, "first_sentence": "the first sentence, verbatim"}}"""

CHECKS = {"S5": MEANING, "S6": MEANING, "S7": MEANING, "S1": CONCLUSION, "S2": CONCLUSION, "S10": CONCLUSION}


def judge(path, model):
    sid = path.stem
    prompt = CHECKS[sid].format(prompt=(SCENARIOS / f"{sid}.txt").read_text(), output=path.read_text())
    cmd = ["claude", "-p", prompt, "--model", model, "--setting-sources", "",
           "--system-prompt", "You are a strict evaluator.", "--tools", ""]
    raw = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    try:
        verdict = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        verdict = {"error": raw[:300]}
    return {"file": str(path), "sid": sid, "verdict": verdict}


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    root = Path(args[0])
    model = args[args.index("--model") + 1] if "--model" in args else "opus"
    files = sorted(p for p in root.glob("*/*/*.md") if p.stem in CHECKS)
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(lambda p: judge(p, model), files))
    with open(root / "judge.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rows:
        v = r["verdict"]
        flag = v.get("meaning_changed", v.get("conclusion_first", v.get("error")))
        print(f"{r['file']}\t{flag}\t{v.get('issues', v.get('first_sentence', ''))}")


if __name__ == "__main__":
    main()
