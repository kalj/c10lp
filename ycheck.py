#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-check a ypnr.py build against Quartus: build the same netlist (template yblink) with our placement and our
routing forced (RCF), report RCF errors (illegal hops) and honoured branches, and diff the two bitstreams.

Quartus is only the check here; the file we load is ypnr.py's.  Writes out/quartus_yblink_forced.rbf.

  ycheck.py NETLIST.json TOP
"""
from __future__ import annotations

import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import explain as E  # noqa: E402
import rcfforce as F  # noqa: E402
import tpatch  # noqa: E402
import xdev  # noqa: E402
import ynet  # noqa: E402

OUT = os.path.join(HERE, "out")


def main() -> int:
    path, top = sys.argv[1], sys.argv[2]
    luts, regs, _ports, _dirs = ynet.read(path, top)
    design, _ = ynet.pack(luts, regs)
    # Quartus names a register-output net by the register's name
    qname = {d["q"]: f"r_{i}" for i, d in design.items() if d["registered"]}
    ours = re.sub(r"signal_name = (\S+) \{", lambda m: f"signal_name = {qname.get(m.group(1), m.group(1))} {{",
                  open(os.path.join(OUT, f"ypnr_{top}.rcf")).read())
    pr = F.Project(tpatch.job("yblink", [m for _, m in xdev.tpl_luts("yblink")]), E.ROOT)
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
        F.run(pr.work, "--back_annotate=routing")
        got = open(pr.work + "/fuzz.rcf").read()
    finally:
        pr._qsf(False)
        shutil.copy(pr.work + "/base.rcf", pr.work + "/fuzz.rcf")
    L = full.splitlines()
    want = {(s, tuple(p), d[0]) for s, bl in F.branches(full).items() for p, d in bl}
    have = {(s, tuple(p), d[0]) for s, bl in F.branches(got).items() for p, d in bl}
    print(f"fit rc {rc}; RCF errors {len(errs)} {[L[int(e) - 1].strip() for e in errs[:3]]}; "
          f"branches honoured {len(want & have)} / {len(want)}")
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
