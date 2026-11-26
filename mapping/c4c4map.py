#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4 -> C4 continuation switches with the batched RCF oracle (r4r4map.py for column wires).

For each net of the vertical-span builds routed LE_BUFFER b -> C4 a -> C4 c -> LAB line L (-> LUT), force c' = every
C4 index 0..23 in a's column starting 6 rows below to 4 rows above a (the corpus's continuations: mostly 4 down),
keeping the rest: an RCF error at c' (hop 2) = a -> c' doesn't exist; at L (hop 3) = it exists but c' doesn't reach L;
honoured = exact bits.  8 probes per fit (rcfforce.scan_batched).
Output (derived facts only): out/c4c4map.json {"job": {"a|c'": {"status": ..., "bits": [...]}}}

  c4c4map.py [N_BUILDS]          (NPAR parallel fits)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import r4r4map  # noqa: E402
import rcfforce as F  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfc4c4")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "c4c4map.json")
LISTS = ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json", "xrkn_c4c_jobs.json", "xrkn_c4d_jobs.json")


def main() -> int:
    nb = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    done = {k.split("|")[0] + "|" + k.split("|")[1] for o in res.values() for k in o}
    # builds whose Quartus route already has a C4 -> C4 chain into a LAB line (from the timing-report routes)
    import routes
    names = []
    for f in LISTS:
        for n in json.load(open(os.path.join(OUT, f))):
            hops = routes.pips(json.load(open(os.path.join(OUT, n + ".route.json"))))
            if any(u.startswith("C4_") and v.startswith("C4_") for u, v in hops):
                names.append(n)
    for name in names[:nb]:
        if name in res:
            continue
        t0 = time.time()
        try:
            pr = F.Project(r4r4map.job_of(name), ROOT)
        except SystemExit as e:
            print(f"{name}: {e}", flush=True)
            continue
        nets = F.nets(pr.base_rcf)
        used = {F.node_name(r) for p in nets.values() for r in p}
        probes = []
        for s, p in nets.items():
            path = [F.node_name(r) for r in p]
            for i in range(1, len(path) - 1):
                a, c = path[i], path[i + 1]
                if not (a.startswith("C4_") and c.startswith("C4_")):
                    continue
                ax, ay = int(a.split("_X")[1].split("_")[0]), int(a.split("_Y")[1].split("_")[0])
                for dy in range(-6, 5):
                    if ay + dy < 0:
                        continue
                    for w in range(24):
                        c2 = f"C4_X{ax}_Y{ay + dy}_N0_I{w}"
                        if c2 == c or c2 in used or f"{a}|{c2}" in done:
                            continue
                        done.add(f"{a}|{c2}")
                        probes.append((s, path, path[:i + 1] + [c2] + path[i + 2:]))
        out = {}
        for (s, old, new), ok, msg, diff in F.scan_batched(pr, probes, workers=NPAR, want_bits=True):
            i = next(j for j in range(1, len(new)) if new[j] != old[j])
            hop = int(msg.split()[-1]) if msg.startswith("rcf error at hop") else None
            st = "honoured" if ok else "no switch" if hop == i else "switch, no tap" if hop == i + 1 else msg
            out[f"{new[i - 1]}|{new[i]}"] = {"status": st, "bits": [list(c) for c in diff] if diff else None}
        res[name] = out
        json.dump(res, open(RES, "w"), indent=0)
        st = {k: sum(1 for v in out.values() if v["status"] == k) for k in ("honoured", "switch, no tap", "no switch")}
        print(f"{name[-34:]}: {len(probes)} probes, {st}, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
