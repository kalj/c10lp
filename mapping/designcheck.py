#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stress test of the open flow on random designs: how general are the models? (option B, design-driven gaps)

Each design: NREG registers on the 48 MHz clock K, r_i <= a random 3-4 input function of D1..D4 (A..D) and other
registers, Q = r_0; some registers get a clock enable from a pin.  Yosys -> c10lp_netlist --io -> nextpnr
(npnr_io.py) -> npnr2asm -> flow/ycheck.py (Quartus with our placement and routing forced).  Per design: routed or
not, RCF errors, branches honoured, core cells differing (besides the RCF-mode bit).  No board runs.
Output: out/designcheck.json {name: {...}} and a summary line.

  designcheck.py [N] [SEED0]
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
OUT = os.path.join(HERE, "out")
RES = os.path.join(OUT, "designcheck.json")
OPS = ["&", "|", "^"]


def design(seed: int) -> str:
    rnd = random.Random(seed)
    nreg = rnd.randint(3, 8)
    sig = ["A", "B", "C", "D"] + [f"r[{i}]" for i in range(nreg)]
    lines = [f"// random design {seed} (mapping/designcheck.py)",
             f"module rd{seed}(input wire K, input wire A, input wire B, input wire C, input wire D, output wire Q);",
             f"  reg [{nreg - 1}:0] r = 0;"]
    en = rnd.choice(["A", "B", None, None])
    for i in range(nreg):
        terms = rnd.sample(sig, rnd.randint(2, 4))
        expr = terms[0]
        for t in terms[1:]:
            expr = f"({expr} {rnd.choice(OPS)} {'~' if rnd.random() < 0.3 else ''}{t})"
        cond = f"if ({en}) " if en and i % 2 else ""
        lines.append(f"  always @(posedge K) {cond}r[{i}] <= {expr};")
    lines += ["  assign Q = r[0];", "endmodule"]
    return "\n".join(lines) + "\n"


def run(cmd, timeout=1800):
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout} s"           # a design that can't be routed in time counts as such
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    s0 = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    for seed in range(s0, s0 + n):
        top = f"rd{seed}"
        if top in res:
            continue
        v = os.path.join(OUT, f"{top}.v")
        open(v, "w").write(design(seed))
        e = {}
        rc, out = run(["yosys", "-q", "-p", f"read_verilog {v}; synth_intel -family cyclone10lp -nodsp -nobram -top {top};"
                       f" write_json out/{top}.json"])
        rc, out = run([sys.executable, "nextpnr/c10lp_netlist.py", f"out/{top}.json", top, f"out/npnr_{top}.json", "--io",
                       "--out-le", "auto"])
        if rc:
            e["status"] = "netlist: " + out.strip().splitlines()[-1][:120]
        for attempt in range(3 if not rc else 0):
            rc, out = run([sys.executable, "nextpnr/npnr_io.py", f"out/npnr_{top}.json", f"out/npnr_{top}_side.json", top,
                           "--region", "4,5,8,8;5,6,7,7;3,4,9,9;2,3,10,10", "--seeds", "20", "--rounds", "12"])
            if rc:
                e["status"] = "no route: " + (out.strip().splitlines() or [""])[-1][:120]
            else:
                rc, out = run([sys.executable, "flow/ycheck.py", f"out/{top}.json", top, "--fresh"])
                m = re.search(r"RCF errors (\d+).*branches honoured (\d+) / (\d+)", out)
                d = re.search(r"core bits differing (\d+)", out)
                e.update(rcf_errors=int(m[1]) if m else None, honoured=f"{m[2]}/{m[3]}" if m else None,
                         differing=int(d[1]) - 1 if d else None,
                         detail=next((ln for ln in out.splitlines() if ln.startswith("core bits")), "")[:300],
                         not_honoured=[ln.strip()[:200] for ln in out.splitlines() if "not honoured" in ln][:3])
                e["status"] = "exact" if e.get("differing") == 0 and e.get("rcf_errors") == 0 else "differs"
                # option B at the cross-check: hops Quartus refused go into hopfix.json ("refused"), the database
                # gets their LABs' own tile types, and the design runs again
                ref = json.load(open(os.path.join(OUT, f"ycheck_{top}_refused.json"))) if os.path.exists(
                    os.path.join(OUT, f"ycheck_{top}_refused.json")) else []
                if ref and attempt < 2:
                    fp = os.path.join(OUT, "hopfix.json")
                    fix = json.load(open(fp))
                    for u, v in ref:
                        fix[f"{u}->{v}"] = {"refused": True, "evidence": f"RCF error in the {top} cross-check"}
                    json.dump(fix, open(fp, "w"), indent=1)
                    run(["nextpnr/build_chipdb.sh"])
                    e["learned"] = e.get("learned", []) + ref
                    continue
            break
        res[top] = e
        json.dump(res, open(RES, "w"), indent=1)
        print(f"{top}: {e.get('status')} {e.get('honoured', '')} {e.get('differing', '')}", flush=True)
    st = [r.get("status", "").split(":")[0] for r in res.values()]
    print({s: st.count(s) for s in set(st)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
