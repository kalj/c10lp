#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-check a ypnr.py build against Quartus: build the same netlist (template yblink) with our placement and our
routing forced (RCF), report RCF errors (illegal hops) and honoured branches, and diff the two bitstreams.

Quartus is only the check here; the file we load is ypnr.py's.  Writes out/quartus_yblink_forced.rbf.

  ycheck.py NETLIST.json TOP [--timing] [--fresh]   (--timing: setup/hold slack at 48 MHz, every corner;
                                                     --fresh: a template from ypnr's current output, not yblink)
"""
from __future__ import annotations

import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import explain as E  # noqa: E402
import rcfforce as F  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402
import ynet  # noqa: E402

OUT = os.path.join(HERE, "out")


STA = """project_open fuzz
create_timing_netlist
create_clock -name K -period 20.833 [get_ports {K}]
update_timing_netlist
foreach_in_collection op [get_available_operating_conditions] {
  set_operating_conditions $op
  update_timing_netlist
  set s [lindex [report_timing -setup -npaths 1 -panel_name s] 1]
  set h [lindex [report_timing -hold -npaths 1 -panel_name h] 1]
  puts "CORNER [get_operating_conditions_info $op -display_name] setup $s hold $h"
}
"""


def timing(work: str):
    """Setup and hold slack of the 48 MHz clock K at every operating corner (Quartus's forced build = our placement
    and routing).  Prints one line per corner; all slacks must be positive."""
    import subprocess
    open(os.path.join(work, "_sta.tcl"), "w").write(STA)
    r = subprocess.run([xdev.tool("quartus_sta"), "-t", "_sta.tcl"], cwd=work, capture_output=True, text=True,
                       timeout=600)
    lines = [ln for ln in r.stdout.splitlines() if "CORNER" in ln]
    for ln in lines:
        print(" ", ln.split("CORNER ", 1)[1])
    ok = bool(lines) and all(float(ln.split("setup ")[1].split()[0]) > 0 and float(ln.split("hold ")[1]) > 0
                             for ln in lines)
    print("timing:", "PASS" if ok else f"FAIL {(r.stdout + r.stderr)[-300:] if not lines else ''}")


def main() -> int:
    path, top = sys.argv[1], sys.argv[2]
    luts, regs, _ports, _dirs = ynet.read(path, top)
    design, _ = ynet.pack(luts, regs)
    # Quartus names a register-output net by the register's name
    qname = {d["q"]: f"r_{i}" for i, d in design.items() if d["registered"]}
    ours = re.sub(r"signal_name = (\S+) \{", lambda m: f"signal_name = {qname.get(m.group(1), m.group(1))} {{",
                  open(os.path.join(OUT, f"ypnr_{top}.rcf")).read())
    tpl = "yblink"
    if "--fresh" in sys.argv:
        # a template from ypnr's current output (netlist, placement), e.g. after --labs: templates/ycheck_TOP_HASH
        # named by a hash of netlist and placement: the oracle caches its Quartus project by template name, so a
        # reused name would check against an older placement
        import hashlib
        h = hashlib.sha1((open(os.path.join(OUT, f"ypnr_{top}.v")).read()
                          + open(os.path.join(OUT, f"ypnr_{top}_locs.qsf")).read()).encode()).hexdigest()[:8]
        tpl = f"ycheck_{top}_{h}"
        d = os.path.join(HERE, "templates", tpl)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "top.v"), "w").write(
            f"// ypnr.py output for {top} (ycheck --fresh): our packed netlist, placement in locs.qsf.\n"
            + open(os.path.join(OUT, f"ypnr_{top}.v")).read())
        shutil.copy(os.path.join(OUT, f"ypnr_{top}_locs.qsf"), os.path.join(d, "locs.qsf"))
        shutil.copy(os.path.join(HERE, "templates", "yblink", "extra.qsf"), os.path.join(d, "extra.qsf"))
    pr = F.Project(tpatch.job(tpl, [m for _, m in xdev.tpl_luts(tpl)]), E.ROOT)
    keep = [m.group(0) for m in re.finditer(r"signal_name = (\S+) \{(.*?)\n\}", pr.base_rcf, re.S)
            if m.group(1) in ("K", "K~input", "Q~output")]
    full = pr.base_rcf[:pr.base_rcf.index("signal_name")] + ours + "\n".join(keep) + "\n"
    open(pr.work + "/fuzz.rcf", "w").write(full)
    pr._qsf(True)
    try:
        rc, out = F.run(pr.work, tool="quartus_fit")
        errs = re.findall(r"Error on line number (\d+) in Routing Constraints File", out)
        F.run(pr.work, tool="quartus_asm")
        q = pr.rbf()
        if "--timing" in sys.argv:
            timing(pr.work)
        F.run(pr.work, "--back_annotate=routing")
        got = open(pr.work + "/fuzz.rcf").read()
    finally:
        pr._qsf(False)
        shutil.copy(pr.work + "/base.rcf", pr.work + "/fuzz.rcf")
    L = full.splitlines()
    # Quartus's back-annotation leaves out the IO_DATAIN node of some pads (X3Y0's): compare without it
    strip = lambda p: tuple(nd for nd in p if not nd.startswith("IO_DATAIN"))
    want = {(s, strip(p), d[0]) for s, bl in F.branches(full).items() for p, d in bl}
    have = {(s, strip(p), d[0]) for s, bl in F.branches(got).items() for p, d in bl}
    print(f"fit rc {rc}; RCF errors {len(errs)} {[L[int(e) - 1].strip() for e in errs[:3]]}; "
          f"branches honoured {len(want & have)} / {len(want)}")
    for w in sorted(want - have)[:6]:
        alt = [h for h in have if h[0] == w[0] and h[2] == w[2]]
        print(f"  not honoured: {w[0]} -> {w[2]}: ours {' '.join(w[1])}; Quartus {' '.join(alt[0][1]) if alt else '(none)'}")
    open(os.path.join(OUT, "quartus_yblink_forced.rbf"), "wb").write(q)
    mine = open(os.path.join(OUT, f"ypnr_{top}.rbf"), "rb").read()
    d = sorted(E.core_diff(mine, q))
    on = lambda b, c: b[32 + c[0] * 255 + c[1]] >> c[2] & 1  # noqa: E731
    print(f"core bits differing {len(d)} | ours 1: {[c for c in d if on(mine, c)][:15]} "
          f"| Quartus 1: {[c for c in d if on(q, c)][:15]}  ((47,197,4) is the RCF-mode bit)")
    print("periphery bytes differing:", sum(1 for i in range(32 + 255, 32 + 37 * 255) if mine[i] != q[i]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
