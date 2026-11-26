#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4 -> LAB-line selects at every tap of a column wire, with the batched RCF oracle (tapmap.py for C4).

On the vertical-span builds (xrkn_c4_jobs.json: sinks 1-4 rows from the sources), each net routed
LE_BUFFER b -> C4 w -> LAB line L of LAB (X, Y) -> LUT is forced to b -> w -> L' for every line L' of that LAB unused
in the build, 8 nets per fit (rcfforce.scan_batched; honoured probes re-run alone for exact bits).  Progress is per
(key, line), key = (wire index, row offset Y - wire start row, X mod 8, Y mod 4): whether the row phase matters is
for the data to show.  A probe's diff also clears the select of the line Quartus chose (its 0-valued cells).
Output (derived facts only): out/c4map.json {"job": {"w|L'": {"status": ..., "bits": [[frame, byte, plane, value]]},
"_orig": {"w": L}}}

  c4map.py [N_BUILDS]          (NPAR parallel fits from the environment, default 8)
  c4map.py --wire-swap [N]     keep the line, swap the C4 (out/c4wire.json)
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
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfc4")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "c4map.json")


def xy(n: str):
    return int(n.split("_X")[1].split("_")[0]), int(n.split("_Y")[1].split("_")[0])


def c4key(w: str, L: str):
    (wx, wy), (lx, ly) = xy(w), xy(L)
    return int(w.rsplit("_I", 1)[1]), ly - wy, lx % 8, ly % 4


def wire_swap(names):
    """The other axis: keep each vertical net's line L and swap its C4 for every other C4 its buffer drives
    (switchmodel drivers, c4drv.py) that passes L's LAB (columns cx, cx + 1; rows start..start + 3).  An honoured
    probe gives that tap's exact select (set cells in the sink LAB) and its driver."""
    import switchmodel as S
    m = S.Model()
    p = os.path.join(OUT, "c4wire.json")
    res = json.load(open(p)) if os.path.exists(p) else {}
    done = {k for o in res.values() for k in o}
    for name in names:
        if name in res:
            continue
        t0 = time.time()
        pr = F.Project(r4r4map.job_of(name), ROOT)
        nets = F.nets(pr.base_rcf)
        used = {F.node_name(r) for pp in nets.values() for r in pp}
        probes = []
        for s, pp in nets.items():
            path = [F.node_name(r) for r in pp]
            if len(path) != 3 or not path[0].startswith("LE_BUFFER") or not path[1].startswith("C4_") or \
                    not path[2].startswith("LOCAL_INTERCONNECT"):
                continue
            (lx, ly), L = xy(path[2]), path[2]
            bq = int(path[0].rsplit("_I", 1)[1])
            sxy = path[0].rsplit("_N0_", 1)[0]
            for bb in (bq - bq % 2, bq - bq % 2 + 1):
                b = f"{sxy}_N0_I{bb}"
                for w, _bits in m.fanout(b):
                    if not w.startswith("C4_") or w == path[1] or w in used:
                        continue
                    (cx, sy) = xy(w)
                    if not (0 <= lx - cx <= 1 and 0 <= ly - sy <= 3) or f"{w}|{L}" in done:
                        continue
                    done.add(f"{w}|{L}")
                    probes.append((s, path, [b, w, L]))
        out = {}
        for (s, old, new), ok, msg, diff in F.scan_batched(pr, probes, workers=NPAR, want_bits=True):
            st = "honoured" if ok else {"rcf error at hop 1": "no driver", "rcf error at hop 2": "no tap"}.get(msg, msg)
            out[f"{new[1]}|{new[2]}"] = {"status": st, "bits": [list(c) for c in diff] if diff else None}
        res[name] = out
        json.dump(res, open(p, "w"), indent=0)
        print(f"{name[-34:]}: {len(probes)} probes, {sum(v['status'] == 'honoured' for v in out.values())} honoured, "
              f"{time.time() - t0:.0f}s", flush=True)
    return 0


def main() -> int:
    if "--wire-swap" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--wire-swap"]
        nb = int(args[0]) if args else 40
        names = [n for f in ("xrkn_c4_jobs.json", "xrkn_c4b_jobs.json") for n in json.load(open(os.path.join(OUT, f)))]
        return wire_swap(names[:nb])
    nb = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    names = json.load(open(os.path.join(OUT, "xrkn_c4_jobs.json")))[:nb]
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    done = {c4key(*k.split("|")) + (int(k.rsplit("_I", 1)[1]),) for o in res.values() for k in o if k != "_orig"}
    for name in names:
        t0 = time.time()
        pr = F.Project(r4r4map.job_of(name), ROOT)
        nets = F.nets(pr.base_rcf)
        used = {F.node_name(r) for p in nets.values() for r in p}
        probes, orig = [], {}
        for s, p in nets.items():
            path = [F.node_name(r) for r in p]
            if len(path) != 3 or not path[0].startswith("LE_BUFFER") or not path[1].startswith("C4_") or \
                    not path[2].startswith("LOCAL_INTERCONNECT"):
                continue
            w, L = path[1], path[2]
            orig[w] = L
            pre = L.rsplit("_I", 1)[0]
            for i in range(38):
                L2 = f"{pre}_I{i}"
                k = c4key(w, L2) + (i,)
                if L2 in used or k in done:
                    continue
                done.add(k)
                probes.append((s, path, [path[0], w, L2]))
        if not probes:
            continue
        out = res.setdefault(name, {})
        out.setdefault("_orig", {}).update(orig)
        for (s, old, new), ok, msg, diff in F.scan_batched(pr, probes, workers=NPAR, want_bits=True):
            st = "honoured" if ok else "no select" if msg == "rcf error at hop 2" else msg
            out[f"{new[1]}|{new[2]}"] = {"status": st, "bits": [list(c) for c in diff] if diff else None}
        json.dump(res, open(RES, "w"), indent=0)
        n_h = sum(1 for k, v in out.items() if k != "_orig" and v["status"] == "honoured")
        print(f"{name[-34:]}: {len(probes)} probes, {n_h} honoured so far in this build, {time.time() - t0:.0f}s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
