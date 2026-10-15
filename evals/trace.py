#!/usr/bin/env python3
"""Read a `claude -p --output-format stream-json` transcript on stdin.

Usage: ... | python3 evals/trace.py SID OUT_DIR
Writes the final reply to OUT_DIR/SID.md and prints which skills ran and which skill files were read.
"""
import json
import sys

sid, out = sys.argv[1], sys.argv[2]
skills, reads, result = [], [], ""
for line in sys.stdin:
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") == "assistant":
        for c in event["message"]["content"]:
            if c.get("type") != "tool_use":
                continue
            if c["name"] == "Skill":
                skills.append(c["input"].get("skill"))
            elif c["name"] == "Read":
                reads.append(c["input"].get("file_path", "").split("/k-ste/")[-1])
    elif event.get("type") == "result":
        result = event.get("result", "")
with open(f"{out}/{sid}.md", "w", encoding="utf-8") as f:
    f.write(result)
print(f"{sid}\tskill={skills}\treads={reads}")
