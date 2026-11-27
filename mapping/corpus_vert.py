#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""More corpus: xrkn:8 builds whose sinks lie 1-4 rows and 0-2 columns from their sources, where the flow places
designs (X 2..11, Y 3..11), for the corpus learners of C4 drivers / taps and corner turns (c4drv.py, c4sel.py,
corner.py).  Each build is a normal Quartus compile; its timing-report routes go to out/<job>.route.json.
Output: out/xrkn_c4e_jobs.json (the builds that routed).

  corpus_vert.py [N] [SEED]          (8 parallel builds)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import routemap as R  # noqa: E402
import routes  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 2711)
    cols = [x for x in range(2, 12) if R._col_frame(x) is not None]
    jobs, names = [], set()
    while len(jobs) < n:
        dy, dx = rnd.choice((-4, -3, -2, -1, 1, 2, 3, 4)), rnd.choice((-2, -1, 0, 0, 1, 2))
        X, Y = rnd.choice(cols), rnd.randint(3, 11)
        if not 2 <= Y + dy <= 28 or R._col_frame(X + dx) is None:
            continue
        try:
            lutpos._predict_phys(X, Y + dy, 0)
            lutpos._predict_phys(X + dx, Y + dy, 0)
        except (ValueError, KeyError):
            continue
        j = xdev.Job("c10_016", f"xrkn:8:{dx}:{dy}:{rnd.randint(100, 999)}", (X, Y, 0), "vidor")
        if j.name not in names:
            names.add(j.name)
            jobs.append(j)
    t0 = time.time()

    def run(j):
        try:
            return routes.route(j, npaths=40) is not None
        except SystemExit:
            return False
    with cf.ThreadPoolExecutor(8) as ex:
        ok = [j.name for j, r in zip(jobs, ex.map(run, jobs)) if r]
    json.dump(ok, open(os.path.join(OUT, "xrkn_c4e_jobs.json"), "w"))
    print(f"{len(ok)} / {len(jobs)} routed in {time.time() - t0:.0f}s -> out/xrkn_c4e_jobs.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
