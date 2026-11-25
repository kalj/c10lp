#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Routing paths of a build, from Quartus's timing report (report_timing -show_routing).

For a job (xdev.Job), compile it (or reuse the cached RBF), run quartus_sta with a max-delay
constraint from each input port to Q, and save every reported path as
  out/<job>.route.json = {"paths": {"A": [[location, element, type], ...], ...}}
A rebuilt RBF must equal the cached one byte for byte, so the labels belong to that exact file.

  routes.py JOB_DESIGN X Y N [PINS]       print the hops of one build
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROW = re.compile(r";\s*([\d.\-]+)\s*;\s*([\d.\-]+)\s*;\s*(\S*)\s*;\s*(\S*)\s*;\s*(\d*)\s*;\s*(\S*)\s*;\s*(.*?)\s*;")
TCL = """project_open fuzz
create_timing_netlist
{constraints}
update_timing_netlist
{reports}
project_close
"""


def _parse_all(path: str) -> list[list[list[str]]]:
    """Every Data Arrival Path in a report file, each as [[location, element, type], ...]."""
    paths, hops, on = [], [], False
    for line in open(path, errors="replace"):
        if "Data Arrival Path" in line:
            on, hops = True, []
            continue
        if on and "Data Required Path" in line:
            on = False
            if hops:
                paths.append(hops)
            continue
        m = ROW.match(line.strip()) if on else None
        if m and m.group(6):
            hops.append([m.group(6), m.group(7), m.group(4)])
    return paths


def _parse(path: str) -> list[list[str]]:
    p = _parse_all(path)
    return p[0] if p else []


def route(job: xdev.Job, out: str = OUT, inputs: str = "ABCD", npaths: int = 1) -> dict | None:
    """Paths of job's build, cached in out/<job>.route.json; None if the design does not build."""
    rp = os.path.join(out, job.name + ".route.json")
    if os.path.exists(rp):
        return json.load(open(rp))
    tmp = os.path.join(out, "routework")
    os.makedirs(tmp, exist_ok=True)
    m = xdev.build_one(job, tmp, True)
    if not m["ok"]:
        return None
    work = os.path.join(tmp, "work", job.name)
    fresh = open(os.path.join(tmp, job.name + ".rbf"), "rb").read()
    cached = xdev.load(out, job.name)
    if cached is None:                                  # first build: adopt it into the cache
        shutil.copy(os.path.join(tmp, job.name + ".rbf"), os.path.join(out, job.name + ".rbf"))
        shutil.copy(os.path.join(tmp, job.name + ".json"), os.path.join(out, job.name + ".json"))
    elif cached != fresh:
        raise SystemExit(f"{job.name}: rebuild differs from the cached RBF")
    cons = "\n".join(f"set_max_delay -from [get_ports {{{p}}}] -to [get_ports {{Q}}] 50" for p in inputs)
    reps = "\n".join(f"report_timing -from [get_ports {{{p}}}] -to [get_ports {{Q}}] -detail full_path "
                     f"-show_routing -npaths {npaths} -file _route_{p}.txt" for p in inputs)
    open(os.path.join(work, "_route.tcl"), "w").write(TCL.format(constraints=cons, reports=reps))
    r = subprocess.run([xdev.tool("quartus_sta"), "-t", "_route.tcl"], cwd=work, capture_output=True, text=True,
                       timeout=600)
    if r.returncode:
        raise SystemExit(f"{job.name}: quartus_sta failed: {(r.stdout + r.stderr)[-400:]}")
    paths = {}
    for p in inputs:
        f = os.path.join(work, f"_route_{p}.txt")
        if os.path.exists(f):
            for i, h in enumerate(_parse_all(f)):
                paths[p if i == 0 else f"{p}#{i + 1}"] = h       # extra paths from the same input: "A#2", ...
    res = {"job": job.name, "paths": paths}
    json.dump(res, open(rp, "w"), indent=0)
    shutil.rmtree(work, ignore_errors=True)
    for ext in (".rbf", ".json"):
        try:
            os.remove(os.path.join(tmp, job.name + ext))
        except FileNotFoundError:
            pass
    return res


def pips(res: dict) -> set[tuple[str, str]]:
    """Programmable hops (from node -> to node) over all paths, routing nodes only.  Cell inputs (type IC, e.g.
    LCCOMB_X12_Y10_N16 with element dst|datac) carry their port: LCCOMB_X12_Y10_N16:datac."""
    out = set()
    for hops in res["paths"].values():
        nodes = []
        for loc, elem, typ in hops:
            if typ == "RE":
                nodes.append(loc)
            elif typ == "IC":
                port = elem.rsplit("|", 1)[-1] if "|" in elem else ""
                nodes.append(f"{loc}:{port}" if port else loc)
        out |= {(a, b) for a, b in zip(nodes, nodes[1:]) if a != b}
    return out


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    design, x, y, n = sys.argv[1], *map(int, sys.argv[2:5])
    pins = sys.argv[5] if len(sys.argv) > 5 else "vidor"
    res = route(xdev.Job("c10_016", design, (x, y, n), pins))
    for p, hops in res["paths"].items():
        print(f"{p}: " + " -> ".join(f"{h[0]}" for h in hops if h[2] in ("RE", "IC")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
