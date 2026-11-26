#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LAB control mux (LAB line -> LAB_CONTROL_MUX slot -> register ENA / SCLR / CLRN) with the RCF oracle (M3a).

On ffe2:KIND:F builds (four registers of one LAB with control C from a pin, KIND = ena, sclr, aclr), Quartus routes
C ... C4 -> LAB line k0 -> LAB_CONTROL_MUX slot j0 -> the registers' control ports.  Probes rename one resource of
C's net everywhere in its block (rcfforce rename: plain lines, labels and branch points):
  mux|j   slot j0 -> slot j (0..9): which slots a port can use, and their cells (the diff: slot j set, j0 cleared)
  line|k  line k0 -> line k (0..37, unused elsewhere): which lines a slot takes; the diff also holds the C4's new tap
          select and the comb LUT's input mux (C also feeds a LUT), both priced by switchmodel
Positions: the five ffe2 LABs and more, covering X mod 8 = 0..7.
Output (derived facts only): out/ctlmap.json {"job": {"base": {"line": k0, "mux": j0}, "probes": {"mux|j": {"status",
"bits"}, "line|k": ...}}}

  ctlmap.py [KIND ...]          (NPAR parallel fits, default 8)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import rcfforce as F  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfctl")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "ctlmap.json")
POS = [(10, 10), (22, 8), (30, 20), (6, 12), (28, 5), (9, 15), (11, 6), (12, 18), (15, 9), (17, 22), (20, 13),
       (23, 16), (31, 11)]
KINDS = ("ena", "sclr", "aclr")


def main() -> int:
    kinds = sys.argv[1:] or KINDS
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    for kind in kinds:
        for x, y in POS:
            job = xdev.Job("c10_016", f"ffe2:{kind}:F", (x, y, 0), "vidor")
            if job.name in res:
                continue
            t0 = time.time()
            try:
                pr = F.Project(job, ROOT)
            except SystemExit as e:
                print(f"{job.name}: {e}", flush=True)
                continue
            m = re.search(r"signal_name = C~input \{(.*?)\n\}", pr.base_rcf, re.S)
            if not m:
                print(f"{job.name}: no C~input block", flush=True)
                continue
            mux = re.search(r"LAB_CONTROL_MUX:X(\d+)Y(\d+)S0I(\d+)", m.group(1))
            line = re.findall(r"LOCAL_INTERCONNECT:X(\d+)Y(\d+)S0I(\d+)", m.group(1))
            if not mux or not line:
                print(f"{job.name}: no control mux / line in C's route", flush=True)
                continue
            mx, my, j0 = map(int, mux.groups())
            lx, ly, k0 = map(int, line[-1])
            used = {int(i) for i in re.findall(rf"LOCAL_INTERCONNECT:X{lx}Y{ly}S0I(\d+)", pr.base_rcf)}
            M = lambda j: f"LAB_CONTROL_MUX_X{mx}_Y{my}_N0_I{j}"
            L = lambda k: f"LOCAL_INTERCONNECT_X{lx}_Y{ly}_N0_I{k}"
            probes = [("rename", "C~input", M(j0), M(j)) for j in range(10) if j != j0]
            probes += [("rename", "C~input", L(k0), L(k)) for k in range(38) if k not in used]
            out = {}
            for pb, ok, msg, cells in F.scan(pr, probes, workers=NPAR, want_bits=True):
                what = ("mux|" + pb[3].rsplit("_I", 1)[1]) if "CONTROL" in pb[3] else ("line|" + pb[3].rsplit("_I", 1)[1])
                out[what] = {"status": msg, "bits": [list(c) for c in cells] if cells else None}
            res[job.name] = {"base": {"line": k0, "mux": j0, "lab": [lx, ly]}, "probes": out}
            json.dump(res, open(RES, "w"), indent=0)
            n_ok = {t: sum(1 for k, v in out.items() if k.startswith(t) and v["status"] == "honoured") for t in ("mux", "line")}
            print(f"{job.name}: line {k0} slot {j0}; honoured {n_ok}, {len(probes)} probes, {time.time() - t0:.0f}s",
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
