#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path library for the Vidor's test pins: complete corpus routes whose every hop the switch model prices.

On this board the designs may use D1..D4 as inputs and D5 as output only (board rules), so instead of general I/O the
nextpnr database gets these pins' complete paths as single pseudo-pips:
  input:  pin -> pad -> input buffer -> IO_DATAIN -> C16/R24/R4/... -> a LAB line   (one per (pin, LAB line))
  output: an LE buffer -> R4/C4/... -> D5's I/O block line                          (one per LE buffer)
taken from every corpus build's timing-report routes (the pad's own buffer hops and D5's block mux are fixed
configuration).  npnr2asm.py expands a pseudo-pip back into its hops.
Output: out/iopaths.json {"input": {"PIN|LINE": [nodes]}, "output": {"LE_BUFFER": [nodes]}}

  iopaths.py
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import switchmodel as S  # noqa: E402

OUT = os.path.join(HERE, "out")
SKIP_IN = {("IOPAD", "IOIBUF"), ("IOIBUF", "IOIBUF")}       # the pad's own configuration


def main() -> int:
    m = S.Model()
    inp, outp, stats = {}, {}, collections.Counter()
    for f in sorted(glob.glob(os.path.join(OUT, "*_jobs.json"))):
        if "holdout" in f:
            continue
        for name in json.load(open(f)):
            rp = os.path.join(OUT, name + ".route.json")
            if not os.path.exists(rp):
                continue
            for _k, p in json.load(open(rp))["paths"].items():
                nodes = [e[0] for e in p if isinstance(e, list)]
                nodes = [x for i, x in enumerate(nodes) if i == 0 or x != nodes[i - 1]]
                types = [x.split("_X")[0] for x in nodes]
                if types and types[0].startswith("PIN_") and "IOPAD" in types[:2]:
                    i = next((j for j, t in enumerate(types) if t == "LOCAL_INTERCONNECT"), None)
                    if i is not None:
                        path = nodes[1:i + 1]
                        hops = [(a, b) for a, b in zip(path, path[1:])
                                if (a.split("_X")[0], b.split("_X")[0]) not in SKIP_IN]
                        ok = all(m.bits(a, b) is not None for a, b in hops)
                        stats[("input", ok)] += 1
                        if ok:
                            inp.setdefault(f"{nodes[0]}|{path[-1]}", path)
                if "BLOCK_INPUT_MUX" in types:
                    e = types.index("BLOCK_INPUT_MUX")
                    js = [j for j in range(e) if types[j] == "LE_BUFFER"]
                    if js:
                        path = nodes[js[-1]:e]
                        ok = all(m.bits(a, b) is not None for a, b in zip(path, path[1:]))
                        stats[("output", ok)] += 1
                        if ok:
                            outp.setdefault(path[0], path)
    json.dump({"input": inp, "output": outp}, open(os.path.join(OUT, "iopaths.json"), "w"), indent=0)
    pins = collections.Counter(k.split("|")[0] for k in inp)
    print(f"input: {len(inp)} (pin, LAB line) paths {dict(pins)}; output: {len(outp)} LE buffers in "
          f"{len({b.rsplit('_N0', 1)[0] for b in outp})} LABs; uses {dict(stats)} -> out/iopaths.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
