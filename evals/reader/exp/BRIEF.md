# 천장 깨기 실험 공통 지시

이 폴더의 실험은 `evals/reader/`의 독자 패널 평가에서 나온 천장 효과를 깨려는 탐색 실험이다. 먼저 `evals/reader/README.md`의 사전 등록, 결과, 변경 기록을 읽는다. 1단계에서는 글 전체를 읽는 LLM 독자가 모든 조건에서 약 99.5%를 맞혔다. 그래서 K-STE의 이해도 효과를 잴 수 없었다.

## 범위와 소유

- 실험마다 `evals/reader/exp/<실험 ID>/` 폴더 하나만 만들고 고친다. 다른 실험의 폴더, `evals/reader/reader.py`, `evals/reader/README.md`, `evals/reader/out/`, 저장소의 다른 파일을 고치면 안 된다.
- `git add`, `git commit`, `git stash`, `git checkout`, `git reset`처럼 저장소 상태를 바꾸는 git 명령을 실행하면 안 된다. 커밋은 코디네이터가 한다.
- 블로그 원문(`evals/reader/out/rewrite/src-local/`)과 그 파생물을 쓰면 안 된다. 공개 원문이 필요하면 Kubernetes 한국어 문서(CC BY 4.0)만 쓴다.

## 하네스 사용

- `evals/reader/reader.py`를 모듈로 불러 쓴다(`sys.path.insert(0, "<저장소>/evals/reader")`, `import reader as R`). 필요한 함수가 다르면 내 스크립트에 복사해서 고친다.
- 주요 함수는 다음과 같다.
  - `R.call(who, prompt, schema=None, system=R.BASE_SYS)`: `who`는 `"grok"`, `"codex"`, `"sonnet"`, `"haiku"`다. 실패하면 3번 재시도한다. `codex`는 `schema`(JSON Schema)가 있어야 한다.
  - `R.system_for(cond)`: 조건(`base`, `clarity`, `short`, `full`)의 글쓴이 시스템 프롬프트를 돌려준다.
  - `R.items()`: 1단계 사실 목록 40개와 검증된 문항(문항 280개)을 돌려준다. 1단계 글은 `out/texts/{조건}/{sonnet|haiku}/F##.md`에 있다.
  - `R.ask(reader, text, qs, persona)`, `R.READ_PROMPT`, `R.qblock`, `R.answer_schema`, `R.shuffle_options`, `R.persona_for`: 객관식 읽기.
  - `R.rates(recs)`(정답률, 오독률, 정보 누락률), `R.boot(diffs)`(짝지은 차이의 평균과 95% 신뢰구간), `R.pmap(fn, xs, workers)`.
- 실행 전에 환경 변수를 설정해야 한다. 설정하지 않으면 다른 계정의 Codex 인증을 써서 한도 오류가 난다.

```sh
export KSTE_CODEX_HOME="$HOME/.cache/k-ste-eval/codex-home-<실험 ID>"
export KSTE_CODEX_AUTH="/Users/ford/Library/Application Support/orca/codex-accounts/e7b29eca-10d5-4ace-b7f2-cacabc9f7b3e/home/auth.json"
export KSTE_LIMIT_GROK=2 KSTE_LIMIT_CODEX=2 KSTE_LIMIT_CLAUDE=3
```

- 여섯 실험이 동시에 실행된다. 동시 호출 수는 위 값보다 크게 하면 안 된다.
- 2차(X7-X9)에는 세 실험만 동시에 실행된다. 그래서 `KSTE_LIMIT_GROK=4 KSTE_LIMIT_CODEX=3 KSTE_LIMIT_CLAUDE=4`까지 써도 된다.
- 3차(X10, X11)에는 독자 패널 실험 두 개와 시나리오 평가(19차) 하나가 동시에 실행된다. X10은 `KSTE_LIMIT_GROK=5 KSTE_LIMIT_CODEX=3 KSTE_LIMIT_CLAUDE=4`, X11은 `KSTE_LIMIT_GROK=3 KSTE_LIMIT_CODEX=3 KSTE_LIMIT_CLAUDE=3`까지 써도 된다.
- 모든 모델 응답은 파일로 저장하고, 파일이 있으면 다시 호출하지 않게 한다. 중간에 끊겨도 다시 실행하면 이어서 해야 한다.
- Codex 호출은 한 번에 약 2만 토큰이 든다. 문항 출제와 채점처럼 Claude가 하면 안 되는 일에만 쓰고, 여러 항목을 한 번에 묶는다.

## 순환을 막는 규칙

- 글쓴이는 Claude(Sonnet, Haiku)다. 문항 출제는 Codex가 한다. 주 독자는 Grok이다. Claude 독자(Haiku)는 보조 지표로만 쓴다.
- 글쓴이는 문항을 보면 안 된다. 독자는 조건을 알면 안 된다.
- 회사, 사람, 날짜, 수치는 가상으로 만든다. 날짜와 요일은 달력으로 확인한다(`R.fix_weekdays` 참고).
- 채점은 기계로 한다. 자유 응답처럼 모델 채점이 필요하면 채점 모델은 조건을 모르게 하고, 표본의 일부를 두 번째 모델로 다시 채점해서 일치율을 보고한다.

## 순서

1. `PREREG.md`를 쓴다. 가설, 조건, 표본 크기와 그 근거, 주 지표, 판정 기준, "천장을 깼다"의 기준을 쓴다. 천장 기준의 기본값은 "base 조건의 주 독자 정답률이 95% 이하이거나 오독률이 3% 이상"이다.
2. 작은 시험 실행(전체의 10% 이하)으로 스크립트를 확인한다. 이 결과로 가설과 기준을 바꾸면 안 된다. 스크립트 오류만 고친다.
3. 본 실행을 한다.
4. `RESULTS.md`를 쓴다. 조건별 표(정답률, 오독률, 정보 누락률, 길이), 사전 등록한 비교의 차이와 95% 신뢰구간, 천장을 깼는지, 한계를 쓴다. 유의하지 않은 결과도 쓴다. 사전 등록에서 바꾼 것은 `PREREG.md`의 변경 기록에 이유와 함께 남긴다.

## 완료 기준

- `exp/<실험 ID>/run.py`가 있고, `python3 run.py selftest`가 채점과 집계 논리를 `assert`로 확인한다.
- `PREREG.md`, `RESULTS.md`, 원자료 폴더(`out/`)가 있다.
- 결과 수치는 `out/`의 파일에서 다시 계산할 수 있다.
- 문서는 한국어 한다체로 쓴다. 사실, 추론, 미확인을 구분한다. 실행하지 않은 검사를 통과했다고 쓰면 안 된다.
