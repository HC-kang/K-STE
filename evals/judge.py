#!/usr/bin/env python3
"""Blind judge with an isolated `claude -p` session. The judge never sees the condition name.

Usage: python3 evals/judge.py RESULTS_ROOT [--model opus] [--cond short,full] [--sid S11,S14]
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
2. A fact, condition, exception, scope marker, or qualifier of degree or manner (for example 모두, 만, 까지, 최대, 되도록, 완전히) is missing.
3. Certainty changed: a possibility is stated as fact, or a fact as a possibility.
4. Obligation strength changed: must, recommended, and allowed are swapped.
5. A phrase that the original allows to be read two ways is silently resolved to one reading.
   If the output keeps the original wording for that phrase or explicitly flags it for confirmation, it is not a change.
6. A subject or object that the original states is dropped, so the reader can no longer tell what the statement is about
   (for example "디스크가 가득 차면 로그를 지운다" shortened to "가득 차면 지운다").
7. A causal link is added or removed (for example "after X" becomes "because of X", or "therefore" disappears).

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

TAIL = """
USER REQUEST:
<<<
{prompt}
>>>

OUTPUT:
<<<
{output}
>>>

Reply with one line of JSON and nothing else:
{{"pass": true or false, "issues": ["one short sentence per failure, quoting the Korean phrase"]}}"""

NORMATIVE = """You audit a Korean policy document written from a list of facts. Check only how obligation and possibility are expressed.

The facts state these strengths:
- requirement: rotate production API keys every 90 days; store rotated keys in the Vault path prod/api-keys
- prohibition: commit API keys to a Git repository
- recommendation: rotate keys during weekday business hours
- permission: during incident response, rotating outside business hours is allowed
- no obligation: development API keys do not have to follow the 90-day rule
- capability: the Vault web screen has a feature that issues keys directly

A failure is any of these:
1. A statement's strength differs from the list (for example the recommendation is written as a requirement, or the permission as a recommendation).
2. The permission or the no-obligation is written with "할 수 있다" or "수 있습니다", which a Korean reader can also read as capability.
3. The capability is written as a permission ("발급해도 된다") or as an instruction.
   Writing the capability with "할 수 있다" or "기능이 있다" is correct, not a failure.
4. A requirement, prohibition, or recommendation is written as a plain description with no obligation marker
   (for example "90일마다 교체한다." or "업무 시간에 교체한다."), so the reader cannot tell a rule from a description.
   The rule counts as marked when that sentence or the sentence right after it states the obligation
   (for example "90일마다 교체한다. 이 규칙은 예외 없이 지켜야 한다." is marked).
   Numbered steps under a procedure heading that only state actions are not failures.
5. A fact, rule, or exception appears that the list does not contain. The list itself says the 90-day rule has no exceptions.
""" + TAIL

VAGUE = """You audit a Korean status message written from a list of facts. Check only whether the reader can tell exactly what happened, to what, and where.

A failure is any of these:
1. A vague status word (반영, 처리, 조치, 대응, 적용, 완료, 정상, 확인, 진행) is used where the facts give the exact action, target, or location, and the sentence does not state them.
   For example "수정 사항을 반영했습니다" when the facts say the PR was merged into main, or "QA 확인 완료" when the facts say 14 of 14 test cases passed.
   A vague word is fine when the same sentence names the exact action and location (for example "스테이징 서버 배포를 완료했습니다").
2. The message blurs the difference between merged into main, deployed to staging, and deployed to production.
3. A fact, cause, number, or plan appears that the list does not contain.
""" + TAIL

JUDGMENT = """You audit a Korean load-test report written from a list of facts. Check only evaluative and degree words.

A failure is any of these:
1. An evaluative or degree word (for example 안정적, 정상, 양호, 원활, 충분, 문제없이, 크게, 급격히, 대부분, 다소, 상당히, 우수)
   states a conclusion, and neither that sentence nor the sentence right before or after it gives the number or the stated criterion that supports it.
   A verdict against the stated target (for example "목표 기준을 충족했습니다" or "기준에 미달했습니다") is not an evaluative word;
   it is supported when the output states the target and the measured numbers for that load anywhere.
2. A judgment goes beyond what was tested: for example saying the system handles a load between 500 and 800 requests per second.
3. A cause of the 800 requests-per-second result is stated as fact. The facts only say that DB CPU reached 95%. A hedged inference (보입니다, 추정합니다) is fine.
4. A fact, cause, number, or plan appears that the list does not contain.
""" + TAIL

FLAG = """You audit a Korean rewrite. The original says "해당 문서" without naming the document and "조치" without saying what was done.

A failure is any of these:
1. A meaning change: a fact, cause, actor, or next action appears that the original does not contain, or a fact or qualifier from the original is missing.
2. The output names a specific document, system, or action that the original does not name.
3. The output does not ask the writer to confirm which document "해당 문서" means (a "확인 필요" line or an equivalent question counts).
4. The output has more than three "확인 필요" lines or questions.
5. A confirmation line or the rewrite offers candidate documents or actions that the original does not name
   (for example "장애 보고서인지 위키인지" or "재시작, 패치 중 무엇인지").
6. The rewrite replaces an original phrase with a placeholder such as "[문서명]".
""" + TAIL

REFERENCE = """You audit Korean meeting notes written from a list of facts. Check only how servers, files, settings, notices, and decisions are referred to.

A failure is any of these:
1. A pointing word (해당, 위, 상기, 본, 이, 그, 관련, 앞의) refers to a server, file, setting, value, notice, or decision,
   and the reader could match it to more than one item in the notes (for example "해당 서버" when both 인증 서버 and 결제 서버 appear).
   A pointing word is fine when only one item can match.
2. The same server, file, or setting is named differently in different places (for example "인증 서버" and "로그인 서버").
3. A fact, decision, owner, or date appears that the list does not contain, or one from the list is missing.
""" + TAIL

HELDOUT = """You audit a Korean weekly update written from a work memo. Check only whether the reader can tell exactly what happened and what the result was.

A failure is any of these:
1. A vague process or status word (for example 검토, 마무리, 작업, 진행, 개선, 이슈, 문제, 대응, 처리, 반영, 완료, 정상)
   is used where the memo gives the exact action, result, or number, and the sentence does not state them.
   For example "시안 검토를 마쳤습니다" when the memo says 박서윤 adopted option 2 of 3,
   or "접근성 이슈를 대부분 개선했습니다" when the memo says 3 of 4 warnings were fixed.
2. The remaining accessibility warning is described without its measured value (3.9:1) or its criterion (4.5:1).
3. A fact, cause, actor, number, date, or plan appears that the memo does not contain.
   A short general definition of a technical term in parentheses is not a failure.
""" + TAIL

COMPLETION = """You audit a Korean status message written from a work memo. Check only how finished work is reported.

A failure is any of these:
1. A completion word (완료, 마쳤다, 끝냈다, 끝났다, 마무리했다, 다 했다) reports a step whose result the memo gives,
   and neither that sentence nor the sentence right after it states the result.
   For example "고객 테이블 이관을 마쳤습니다" without "120만 행 중 120만 행",
   or "검증도 완료했습니다" without "쿼리 3개 모두 일치".
2. An evaluative word replaces a stated fact (for example "문제없이 이관했습니다" instead of saying the service did not stop).
3. A fact, cause, number, or plan appears that the memo does not contain.
""" + TAIL

DATES = """You audit a Korean announcement written from a list of facts. Check only how dates and times are presented.

The facts contain two kinds of dates.
- Scheduled: the event happens at that time (security training on 10월 23일 14:00; IT updates every laptop on 10월 26일).
- Deadline: the action must be done by that time (survey by 10월 22일 18:00; each employee changes the password by 10월 30일).

A failure is any of these:
1. A deadline is presented so a reader could take it as the time the action happens, or a scheduled date as a deadline.
   For example "10월 22일 18:00에 설문을 제출합니다", "10월 26일까지 백신 업데이트",
   or a single date column (날짜, 일시, 기한) that mixes both kinds without marking which is which in each row,
   or a "~부터 ~까지" span in a summary whose endpoint is a deadline and is not labeled as one (마감, 기한, 제출 기한).
   A span whose deadline endpoints are labeled (for example "피드백 마감까지") is fine.
2. The actor or the obligation changes (for example employees are told to update the antivirus themselves,
   or the password change becomes optional).
3. A fact, place, time, or step appears that the list does not contain.
""" + TAIL

DATES2 = """You audit a Korean email written from a list of facts. Check only how dates and times are presented.

The facts contain two kinds of dates.
- Scheduled: the event happens at that time (kickoff meeting on 11월 3일 10:00; internal demo on 11월 13일).
- Deadline: the action must be done by that time (design drafts by 11월 6일; demo feedback is collected until 11월 18일 18:00).

A failure is any of these:
1. A deadline is presented so a reader could take it as the time the action happens, or a scheduled date as a deadline.
   For example "11월 6일에 시안을 제출합니다", "11월 13일까지 시연",
   or a single date column that mixes both kinds without marking which is which in each row,
   or a "~부터 ~까지" span in a summary whose endpoint is a deadline and is not labeled as one (마감, 기한, 제출 기한).
   A span whose deadline endpoints are labeled (for example "피드백 마감까지") is fine.
2. The actor or the obligation changes.
3. A fact, place, time, or step appears that the list does not contain.
""" + TAIL

CHECKS = {"S5": MEANING, "S6": MEANING, "S7": MEANING, "S1": CONCLUSION, "S2": CONCLUSION, "S10": CONCLUSION,
          "S11": NORMATIVE, "S12": VAGUE, "S13": JUDGMENT, "S14": FLAG, "S15": REFERENCE, "S16": HELDOUT, "S17": COMPLETION, "S18": DATES, "S19": DATES2}


def judge(path, model):
    sid = path.stem
    prompt = CHECKS[sid].format(prompt=(SCENARIOS / f"{sid}.txt").read_text(), output=path.read_text())
    cmd = ["claude", "-p", prompt, "--model", model, "--setting-sources", "", "--strict-mcp-config",
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
    conds = args[args.index("--cond") + 1].split(",") if "--cond" in args else None
    sids = args[args.index("--sid") + 1].split(",") if "--sid" in args else None
    files = sorted(p for p in root.glob("*/*/*.md")
                   if p.stem in CHECKS and (conds is None or p.parent.name in conds)
                   and (sids is None or p.stem in sids))
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(lambda p: judge(p, model), files))
    # Re-judging a file replaces its old verdict instead of appending a duplicate.
    path = root / "judge.jsonl"
    judged = {r["file"] for r in rows}
    old = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    with open(path, "w", encoding="utf-8") as f:
        for r in [o for o in old if o["file"] not in judged] + rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rows:
        v = r["verdict"]
        flag = v.get("meaning_changed", v.get("conclusion_first", v.get("pass", v.get("error"))))
        print(f"{r['file']}\t{flag}\t{v.get('issues', v.get('first_sentence', ''))}")


if __name__ == "__main__":
    main()
