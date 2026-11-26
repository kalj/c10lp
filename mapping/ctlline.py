#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LAB line -> LAB_CONTROL_MUX selects with the RCF oracle (M3a, after ctlmap.py's slot probes).

On ffc:KIND:S builds (the control of four registers comes from LE slot S of the same LAB), Quartus routes the control
t: LOCAL_LINE of S -> LAB_CONTROL_MUX slot j -> ENA / SCLR / CLRN.  Each probe forces t out over one of S's buffers
onto LAB line k and into the same slot (force: LOCAL_LINE -> LE_BUFFER b, LOCAL_INTERCONNECT k); the diff is the
buffer -> line select (priced by switchmodel) plus line k's select into slot j, minus the local line's.  ctlmap.py's
line renames kept the C4 and so could reach almost no line.
Output (derived facts only): out/ctlline.json {"job": {"slot": j, "probes": {"b|k": {"status", "bits"}}}}

  ctlline.py [KIND ...]          (NPAR parallel fits, default 8)
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
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfctl")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "ctlline.json")
JOBS = [((10, 10), 10), ((22, 8), 20), ((30, 20), 12), ((6, 12), 22), ((15, 9), 14), ((12, 18), 24), ((20, 13), 18),
        ((23, 16), 26), ((31, 11), 28), ((11, 6), 30)]


def main() -> int:
    kinds = sys.argv[1:] or ("ena", "sclr", "aclr")
    m = S.Model()
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    for kind in kinds:
        for (x, y), slot in JOBS:
            job = xdev.Job("c10_016", f"ffc:{kind}:{slot}", (x, y, 0), "vidor")
            if job.name in res:
                continue
            t0 = time.time()
            try:
                pr = F.Project(job, ROOT)
            except SystemExit as e:
                print(f"{job.name}: {e}", flush=True)
                continue
            mm = re.search(r"signal_name = t \{(.*?)\n\}", pr.base_rcf, re.S)
            ll = re.search(r"^\t(LOCAL_LINE:X\d+Y\d+S0I\d+);", mm.group(1), re.M) if mm else None
            mux = re.search(r"LAB_CONTROL_MUX:X\d+Y\d+S0I(\d+)", mm.group(1)) if mm else None
            if not ll or not mux:
                print(f"{job.name}: t is not LOCAL_LINE -> LAB_CONTROL_MUX", flush=True)
                continue
            local = F.node_name(ll.group(1))
            used = {int(i) for i in re.findall(rf"LOCAL_INTERCONNECT:X{x}Y{y}S0I(\d+)", pr.base_rcf)}
            probes = []
            for b in (slot, slot + 1):
                buf = f"LE_BUFFER_X{x}_Y{y}_N0_I{b}"
                for k in range(38):
                    line = f"LOCAL_INTERCONNECT_X{x}_Y{y}_N0_I{k}"
                    if k not in used and m.bits(buf, line) is not None:
                        probes.append(("t", [local], [buf, line]))
            out = {}
            for (sg, old, new), ok, msg, cells in F.scan(pr, probes, workers=NPAR, want_bits=True):
                key = f"{new[0].rsplit('_I', 1)[1]}|{new[1].rsplit('_I', 1)[1]}"
                out[key] = {"status": msg, "bits": [list(c) for c in cells] if cells else None}
            res[job.name] = {"slot": int(mux.group(1)), "lab": [x, y], "source": slot, "probes": out}
            json.dump(res, open(RES, "w"), indent=0)
            print(f"{job.name}: slot {mux.group(1)}; {sum(v['status'] == 'honoured' for v in out.values())} of "
                  f"{len(probes)} honoured, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
