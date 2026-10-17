#!/usr/bin/env python3
"""Usage: python3 evals/span.py RUN_PREFIX (for example it18)
Count outputs with an unlabeled '...부터 ...까지' span whose endpoint is a deadline date (S18, S19)."""
import re, sys, glob, collections
from pathlib import Path
DEADLINE = {'S18': {'22', '30'}, 'S19': {'6', '18'}}
SPAN = re.compile(r'(\d+)일[^.\n|]{0,25}?부터[^.\n|]{0,40}?(\d+)일([^.\n|]{0,20}?)까지')
def bad(text, sid):
    for m in SPAN.finditer(text):
        a, b, tail = m.group(1), m.group(2), m.group(3)
        seg = m.group(0)
        if (a in DEADLINE[sid] or b in DEADLINE[sid]) and not re.search(r'마감|기한', seg):
            return True
    return False
prefix = sys.argv[1]
tab = collections.defaultdict(lambda: [0, 0])
for f in glob.glob(f'evals/results/{prefix}-r*/*/*/S1[89].md'):
    p = Path(f); sid = p.stem; cond = p.parts[-2]
    tab[(sid, cond)][0] += bad(p.read_text(), sid); tab[(sid, cond)][1] += 1
for k in sorted(tab): print(k, f'{tab[k][0]}/{tab[k][1]} unlabeled deadline spans')
