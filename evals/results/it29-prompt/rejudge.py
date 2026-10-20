# 29차: judge.jsonl에서 판정 오류("error")가 난 출력만 저장소의 evals/judge.py judge()로 다시 판정하고, 그 행만 바꾼다.
# 저장소 루트에서 PATH=$P/bin:$PATH KSTE_SLOTS=6 python3 evals/results/it29-prompt/rejudge.py로 실행한다. 판정 프롬프트와 모델(opus)은 judge.py와 같다.
import glob, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "evals")
import judge  # noqa: E402

for path in sorted(glob.glob("evals/results/it29-r*/judge.jsonl")):
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    bad = [i for i, r in enumerate(rows) if "error" in r["verdict"]]
    if not bad:
        continue
    with ThreadPoolExecutor(6) as pool:
        new = list(pool.map(lambda i: judge.judge(Path(rows[i]["file"]), "opus"), bad))
    for i, r in zip(bad, new):
        assert r["file"] == rows[i]["file"]
        rows[i] = r
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(path, "다시 판정", len(bad), "남은 오류", sum("error" in r["verdict"] for r in rows))
