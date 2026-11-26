#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Delays per routing-resource type and per cell arc from Quartus's timing reports (M5).

On already compiled oracle projects (their work directories under $CLAUDE_JOB_DIR/tmp/rcf*/work), quartus_sta reports
the paths from every input port to Q (and between registers where there is a clock) with -detail full_path
-show_routing, at the default (slow 1200 mV 85 C) corner.  Each Data Arrival Path element has an incremental delay:
  RE  a routing element: keyed by its node type (R4, C4, LOCAL_LINE, LOCAL_INTERCONNECT, LE_BUFFER, C16, ...)
  IC  a cell input pin: keyed by port (datab, ...)
  CELL  a cell: LUT input -> combout keyed by the input port, register clock -> q (uTco and CELL)
Only the statistics are kept (derived facts): out/delays.json {"RE": {type: [n, median, p90]}, "IC": ..., "CELL": ...}

  delays.py [N_PROJECTS]          (NPAR parallel runs, default 8)
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import glob
import json
import os
import random
import re
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
NPAR = int(os.environ.get("NPAR", "8"))
TCL = """project_open fuzz
create_timing_netlist
{clock}
set_max_delay -from [all_inputs] -to [all_outputs] 50
update_timing_netlist
report_timing -to [all_outputs] -npaths 40 -detail full_path -show_routing -file _dly.txt
{reg}
project_close
"""
ROW = re.compile(r"^;\s*([\d.]+)\s*;\s*(-?[\d.]+)\s*;\s*\w*\s*;\s*(\w*)\s*;\s*\d*\s*;\s*(\S*)\s*;\s*(\S+)\s*;")


def one(work: str):
    v = open(os.path.join(work, "fuzz_top.v")).read() if os.path.exists(os.path.join(work, "fuzz_top.v")) else ""
    clocked = re.search(r"input\s+wire\s+K\b|\bK\b", v) is not None
    tcl = TCL.format(clock="create_clock -period 20.833 -name K [get_ports K]" if clocked else "",
                     reg="report_timing -from_clock K -to_clock K -setup -npaths 40 -detail full_path -show_routing "
                         "-append -file _dly.txt" if clocked else "")
    open(os.path.join(work, "_dly.tcl"), "w").write(tcl)
    r = subprocess.run([xdev.tool("quartus_sta"), "-t", "_dly.tcl"], cwd=work, capture_output=True, text=True,
                       timeout=600)
    p = os.path.join(work, "_dly.txt")
    if r.returncode or not os.path.exists(p):
        return []
    rows, on = [], False
    for line in open(p, errors="replace"):
        if "Data Arrival Path" in line:
            on = True
        elif "Data Required Path" in line:
            on = False
        elif on:
            m = ROW.match(line)
            if m:
                _tot, incr, typ, loc, elem = m.groups()
                rows.append((typ, loc, elem, float(incr)))
    os.remove(p)
    return rows


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    root = os.environ.get("CLAUDE_JOB_DIR", OUT)
    works = [w for w in glob.glob(os.path.join(root, "tmp", "rcf*", "work", "*")) if not re.search(r"\.w\d+$", w)]
    random.Random(3).shuffle(works)
    data = collections.defaultdict(list)
    with cf.ThreadPoolExecutor(NPAR) as ex:
        for rows in ex.map(one, works[:n]):
            prev_in = None
            for typ, loc, elem, incr in rows:
                kind = loc.split("_X")[0] if "_X" in loc else elem
                port = elem.split("|")[1] if "|" in elem else ""
                if typ == "RE":
                    data[("RE", kind)].append(incr)
                elif typ == "IC":
                    data[("IC", f"{kind}:{port}")].append(incr)
                    prev_in = port
                elif typ == "CELL" and kind == "LCCOMB" and port == "combout" and prev_in:
                    data[("CELL", f"LCCOMB:{prev_in}->combout")].append(incr)   # the LUT arc, by input port
                elif typ == "CELL" and kind == "FF" and not port and prev_in:
                    data[("CELL", f"FF:{prev_in}")].append(incr)   # the register's arc from its input (d, ena, ...)
                    prev_in = None
                elif typ in ("CELL", "uTco"):
                    data[(typ, f"{kind}:{port}")].append(incr)
    out = collections.defaultdict(dict)
    for (cls, key), v in sorted(data.items()):
        v = sorted(v)
        out[cls][key] = [len(v), round(statistics.median(v), 3), round(v[int(0.9 * (len(v) - 1))], 3)]
    out["_about"] = (f"Incremental delays (ns, slow 1200 mV 85 C) from quartus_sta reports of {min(n, len(works))} "
                     "compiled projects: [count, median, 90th percentile] per class (mapping/delays.py)")
    json.dump(out, open(os.path.join(OUT, "delays.json"), "w"), indent=1)
    for cls in ("RE", "IC", "CELL", "uTco"):
        print(cls, {k: v for k, v in sorted(out.get(cls, {}).items(), key=lambda kv: -kv[1][0])[:14]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
