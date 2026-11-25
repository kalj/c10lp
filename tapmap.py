#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 -> LAB-line selects at every tap of a wire, with the RCF oracle.

selmap.py measures wires that start at the destination LAB; most taps in real routes are further along a wire (both
directions), and the corpus can't separate them (no two entries share bits).  On short-span builds (xrkn_w2w3_jobs:
spans 2-4), for each net routed LE_BUFFER b -> R4 w -> LAB line L of LAB X -> LUT, keep b and w and force every other
line L' of X unused in the build: honoured = w's tap at X enters L' (exact bits from the diff), an error at the line =
no such select, an error after it = the select exists but L' can't reach that LUT port.
Output (derived facts only): out/tapmap.json {"job": {"w|L'": {"status": ..., "bits": [[frame, byte, plane, value]]}}}

  tapmap.py [N_BUILDS]           (NPAR parallel fits from the environment, default 8; keys already scanned are
                                 skipped)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rcfforce as F  # noqa: E402
import r4r4map  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcftap")
NPAR = int(os.environ.get("NPAR", "8"))
JOBS = ("xrkn_w2w3_jobs.json", "xrkn_w2w4_jobs.json")   # short-span builds, in order


def main() -> int:
    nb = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    names = [n for f in JOBS for n in json.load(open(os.path.join(OUT, f)))][:nb]
    p = os.path.join(OUT, "tapmap.json")
    res = json.load(open(p)) if os.path.exists(p) else {}
    # the legal lines and their bits depend only on (wire index, tap offset, X mod 8) (95/95 position pairs agree):
    # a key scanned once needn't be scanned again
    def tapkey(w, L):
        wx, wi = int(w.split("_X")[1].split("_")[0]), int(w.rsplit("_I", 1)[1])
        lx = int(L.split("_X")[1].split("_")[0])
        return wi, lx - wx, lx % 8
    done = {tapkey(*k.split("|")) for out in res.values() for k in out}
    for name in names:
        if name in res:
            continue
        t0 = time.time()
        pr = F.Project(r4r4map.job_of(name), ROOT)
        brs = F.branches(pr.base_rcf)
        used = {n for bl in brs.values() for pth, _ in bl for n in pth}
        probes, seen = [], set()
        for sig, bl in brs.items():
            for path, d in bl:
                if len(path) == 3 and path[0].startswith("LE_BUFFER") and path[1].startswith("R4") and \
                        path[2].startswith("LOCAL_INTERCONNECT") and d[2]:
                    w, L = path[1], path[2]
                    if tapkey(w, L) in done:
                        continue
                    done.add(tapkey(w, L))
                    pre = L.rsplit("_I", 1)[0]
                    for i in range(38):
                        L2 = f"{pre}_I{i}"
                        if L2 in used or (w, L2) in seen:
                            continue
                        seen.add((w, L2))
                        fn = (lambda blk, L=L, L2=L2: re.sub(r", route_port = \w+;", ";", blk)
                              .replace(F.rcf_name(L) + ";", F.rcf_name(L2) + ";"))
                        probes.append((sig, fn, L2, (w, L2)))
        clones = [F._clone(pr, k) for k in range(NPAR)]

        def work(k):
            r = []
            for sig, fn, expect, key in probes[k::NPAR]:
                ok, data, msg = clones[k].rewrite(sig, fn, expect)
                r.append((key, ok, msg, F.xor_cells(pr.ident_rbf, data) if ok else None))
            return r
        out = {}
        with cf.ThreadPoolExecutor(NPAR) as ex:
            for part in ex.map(work, range(NPAR)):
                for (w, L2), ok, msg, d in part:
                    st = ("honoured" if ok else "no select" if F.rcf_name(L2) in msg
                          else "select, port unreachable" if "rcf error" in msg else msg)
                    out[f"{w}|{L2}"] = dict(status=st, msg=msg, bits=[list(x) for x in d] if d else None)
        res[name] = out
        json.dump(res, open(p, "w"), indent=0)
        st = {s: sum(1 for v in out.values() if v["status"] == s) for s in ("honoured", "no select", "select, port unreachable")}
        print(f"{name[-34:]}: {len(probes)} probes, {st}, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
