#!/usr/bin/env python3
"""evals/judge.py의 main을 동시 실행 3개로 부른다(judge.py는 6개). 판정 프롬프트, 모델(opus), judge.jsonl 쓰기는 judge.py 그대로다.
Usage: python3 evals/results/it26-prompt/judge3.py RESULTS_ROOT [judge.py 옵션...]
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # evals/
import judge

judge.ThreadPoolExecutor = lambda _n: ThreadPoolExecutor(3)  # ponytail: 다른 워커와 함께 돌려서 claude -p 3개 상한
judge.main()
