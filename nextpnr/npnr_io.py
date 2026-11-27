#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""nextpnr for designs with I/O cells (c10lp_netlist.py --io): place and route, and when no seed routes, narrow the
LAB sets of the pin-fed LUTs (C10LP_CELL_REGIONS) and try again.

Each round runs up to SEEDS nextpnr seeds (router1, which names the net it can't route).  If none routes, a place-only
run with the last seed shows where that net's ends were placed; the pin-fed cell among them loses the LAB it sat in
(the placer prefers the nearest LAB, which may have no route onward to the rest), and the next round starts.  On
success the result goes through npnr2asm.py.

  npnr_io.py NETLIST.json SIDECAR.json TOP [--region x0,y0,x1,y1[;x0,y0,x1,y1...]] [--rounds N] [--seeds N]

Several regions (";"-separated) are tried in order when a failing net has no pin-fed end to narrow; after the last,
the net's geometry is measured with the RCF oracle (tapforce.py --job, option B) and the regions start again.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
OUT = os.path.join(HERE, "out")
NPNR = os.environ.get("NEXTPNR", os.path.join(HERE, "..", "nextpnr", "build", "nextpnr-himbaechel"))


def run(cmd, log, env, timeout=60):
    with open(log, "w") as f:
        try:
            return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout, env=env).returncode
        except subprocess.TimeoutExpired:
            return 124


def main() -> int:
    args = sys.argv[1:]
    opt = lambda k, d: args[args.index(k) + 1] if k in args else d
    netlist, side, top = [a for i, a in enumerate(args) if not a.startswith("--") and
                          (i == 0 or not args[i - 1].startswith("--"))][:3]
    rounds, seeds = int(opt("--rounds", 6)), int(opt("--seeds", 20))
    all_regions = opt("--region", "3,3,9,9").split(";")
    regions_list = list(all_regions)
    region = regions_list.pop(0)
    probed = {}
    regions_path = netlist.replace(".json", "_regions.json")
    regions = json.load(open(regions_path))
    work = os.path.join(OUT, f"npnr_{top}_io_regions.json")
    routed, log = os.path.join(OUT, f"npnr_{top}_routed.json"), os.path.join(OUT, f"npnr_{top}.log")
    env = dict(os.environ, C10LP_REGION=region, C10LP_CELL_REGIONS=work)
    # a real timing target (the default 12 MHz makes detours free: cnt_sclr's routes wandered from X6 to X30, through
    # many rarely used hops); timing-driven placement and routing then keep nets short
    base = [NPNR, "--device", "10CL016", "--json", netlist, "--pre-place", os.path.join(HERE, "nextpnr", "region_row.py"),
            "--freq", opt("--freq", "100")]
    for rnd in range(rounds):
        json.dump(regions, open(work, "w"))
        net = None
        for s in range(1, seeds + 1):
            if run(base + ["--seed", str(s), "--router", "router1", "--write", routed], log, env) == 0:
                print(f"round {rnd}: routed with seed {s}", flush=True)
                return subprocess.run([sys.executable, os.path.join(HERE, "nextpnr", "npnr2asm.py"), routed, side,
                                       top]).returncode
            mm = re.search(r"Failed to find a route for arc \d+ of net (\S+)\.", open(log).read())
            net = mm.group(1) if mm else net
        if net is None:
            print(f"round {rnd}: no seed routes and nextpnr names no net:\n{open(log).read()[-600:]}")
            return 1
        placed = os.path.join(OUT, f"npnr_{top}_placed.json")
        run(base + ["--seed", str(seeds), "--no-route", "--write", placed], log + ".place", env)
        mod = next(iter(json.load(open(placed))["modules"].values()))
        bit = mod["netnames"][net]["bits"][0]
        ends = {name: c["attributes"]["NEXTPNR_BEL"] for name, c in mod["cells"].items()
                if any(bit in bb for bb in c["connections"].values())}
        cut = None
        for name, bel in sorted(ends.items()):
            own = name[2:] if name.startswith("r_") else name
            lab = list(map(int, re.match(r"X(\d+)Y(\d+)/", bel).groups()))
            if own in regions and len(regions[own]) > 1 and lab in regions[own]:
                regions[own].remove(lab)
                cut = (own, lab)
                break
        if cut is None and regions_list:
            region = regions_list.pop(0)
            env["C10LP_REGION"] = region
            print(f"round {rnd}: net {net} fails, no pin-fed end to narrow: next region {region}", flush=True)
            continue
        if cut is None and not probed.get(net):
            # option B: measure the failing net's geometry with the RCF oracle (tapforce.py --job, as npnr_flow.py),
            # rebuild the switch table and the database, and start again from the first region
            lab = lambda b: tuple(map(int, re.match(r"X(\d+)Y(\d+)/", b).groups()))
            src = next((b for nm, b in ends.items() if mod["cells"][nm]["connections"].get("Q", [None])[0] == bit
                        or mod["cells"][nm]["connections"].get("F", [None])[0] == bit), None)
            if src and re.search(r"/LE(\d+)_", src):
                slot = 2 * int(re.search(r"/LE(\d+)_", src).group(1))
                sx, sy = lab(src)
                import random
                found = [sd for sd in range(5000 + 1000 * rnd, 6000 + 1000 * rnd)
                         if slot in random.Random(sd).sample(range(0, 32, 2), 8)][:2]
                sinks = sorted({lab(b) for b in ends.values() if lab(b) != (sx, sy) and "/LE" in b})
                print(f"round {rnd}: net {net} from X{sx}Y{sy} N{slot} to {sinks}: probing (seeds {found})", flush=True)
                for tx, ty in sinks:
                    for sd in found:
                        subprocess.run([sys.executable, os.path.join(HERE, "mapping", "tapforce.py"), "--job",
                                        f"{sx},{sy},{tx - sx},{ty - sy},{sd}"])
                subprocess.run([sys.executable, os.path.join(HERE, "lib", "switchmodel.py"), "build"],
                               stdout=subprocess.DEVNULL)
                subprocess.run([os.path.join(HERE, "nextpnr", "build_chipdb.sh")], stdout=subprocess.DEVNULL)
                probed[net] = True
                region = all_regions[0]
                regions_list = list(all_regions[1:])
                env["C10LP_REGION"] = region
                continue
        if cut is None:
            print(f"round {rnd}: net {net} fails and no pin-fed end has another LAB to go to ({ends})")
            return 1
        print(f"round {rnd}: net {net} fails; {cut[0]} leaves X{cut[1][0]}Y{cut[1][1]} "
              f"({len(regions[cut[0]])} LABs left)", flush=True)
    print(f"no routing after {rounds} rounds")
    return 1


if __name__ == "__main__":
    sys.exit(main())
