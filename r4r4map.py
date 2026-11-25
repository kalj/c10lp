#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 -> R4 continuation switches with the RCF oracle, on the 7-column-span corpus (xrkn_w2w_jobs.json).

For each net routed LE_BUFFER b -> R4 a -> R4 c -> LAB line L -> LUT, force c' = every R4 index at c's column and row:
  error at hop 2 (c'): a -> c' doesn't exist; error at hop 3 (L): a -> c' exists, c' doesn't reach L;
  honoured: a -> c' exists and reaches L; the diff against the identity build holds the bits of the old and new hops.
Output (derived facts only): out/r4r4map.json {"job": {"a|c'": {"status": ..., "bits": [[frame, byte, plane, value]]}}}

  r4r4map.py [N_BUILDS]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rcfforce as F  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfw2w")


def job_of(name: str) -> xdev.Job:
    m = re.search(r"xrkn-(\d+)_(-?\d+)_(-?\d+)_(\d+)_X(\d+)Y(\d+)__", name)
    k, dx, dy, seed, x, y = map(int, m.groups())
    return xdev.Job("c10_016", f"xrkn:{k}:{dx}:{dy}:{seed}", (x, y, 0), "vidor")


def main() -> int:
    nb = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    names = json.load(open(os.path.join(OUT, "xrkn_w2w_jobs.json")))[::max(1, 100 // nb)][:nb]
    res = json.load(open(os.path.join(OUT, "r4r4map.json"))) if os.path.exists(os.path.join(OUT, "r4r4map.json")) else {}
    for name in names:
        if name in res:
            continue
        t0 = time.time()
        pr = F.Project(job_of(name), ROOT)
        brs = F.branches(pr.base_rcf)
        used = {n for bl in brs.values() for p, _ in bl for n in p}
        probes, seen = [], set()
        for sig, bl in brs.items():
            for path, d in bl:
                if len(path) == 4 and path[0].startswith("LE_BUFFER") and path[1].startswith("R4") and \
                        path[2].startswith("R4") and path[3].startswith("LOCAL_INTERCONNECT") and d[2]:
                    a, c = path[1], path[2]
                    pre = c.rsplit("_I", 1)[0]
                    for i in range(48):
                        c2 = f"{pre}_I{i}"
                        if c2 == c or c2 in used or (a, c2) in seen:
                            continue
                        seen.add((a, c2))
                        fn = (lambda blk, c=c, c2=c2: re.sub(r", route_port = \w+;", ";", blk)
                              .replace(F.rcf_name(c) + ";", F.rcf_name(c2) + ";"))
                        probes.append(("rw", sig, fn, path[3], (a, c2)))
        out = {}
        import concurrent.futures as cf
        clones = [F._clone(pr, k) for k in range(6)]

        def work(k):
            r = []
            for _t, sig, fn, expect, key in probes[k::6]:
                ok, data, msg = clones[k].rewrite(sig, fn, expect)
                r.append((key, ok, msg, F.xor_cells(pr.ident_rbf, data) if ok else None))
            return r
        with cf.ThreadPoolExecutor(6) as ex:
            for part in ex.map(work, range(6)):
                for (a, c2), ok, msg, d in part:
                    st = "honoured" if ok else ("no switch" if F.rcf_name(c2) in msg else "no line" if "LOCAL_INTERCONNECT" in msg else msg)
                    out[f"{a}|{c2}"] = dict(status=st, bits=[list(x) for x in d] if d else None)
        res[name] = out
        json.dump(res, open(os.path.join(OUT, "r4r4map.json"), "w"), indent=0)
        st = {s: sum(1 for v in out.values() if v["status"] == s) for s in ("honoured", "no switch", "no line")}
        print(f"{name[-34:]}: {len(probes)} probes, {st}, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
