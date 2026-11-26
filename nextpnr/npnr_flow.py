#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""nextpnr with on-demand mapping (option B): place and route; when no seed routes, probe the missing hops of the net
nextpnr names and try again.

Each round: up to SEEDS nextpnr runs (router1, which names the net it can't route).  If none routes, a place-only run
with the last seed gives that net's source and sink LABs, tapforce.py --job measures exactly that geometry with the
batched RCF oracle, the switch table and the chip database are rebuilt, and the next round starts.  On success the
result goes through npnr2asm.py.  Extra nextpnr arguments (e.g. --pre-place SCRIPT) pass through.

  npnr_flow.py NETLIST.json SIDECAR.json TOP [--rounds N] [--seeds N] [-- nextpnr args ...]
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
OUT = os.path.join(HERE, "out")
NPNR = os.environ.get("NEXTPNR", os.path.join(HERE, "..", "nextpnr", "build", "nextpnr-himbaechel"))


def run(cmd, log, timeout=60):
    """Return code, or 124 on a timeout (router1 can loop on congestion; that seed counts as failed)."""
    with open(log, "w") as f:
        try:
            return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124


def main() -> int:
    args = sys.argv[1:]
    extra = args[args.index("--") + 1:] if "--" in args else []
    args = args[:args.index("--")] if "--" in args else args
    rounds = int(args[args.index("--rounds") + 1]) if "--rounds" in args else 4
    seeds = int(args[args.index("--seeds") + 1]) if "--seeds" in args else 20
    netlist, side, top = args[0], args[1], args[2]
    routed = os.path.join(OUT, f"npnr_{top}_routed.json")
    log = os.path.join(OUT, f"npnr_{top}.log")
    for rnd in range(rounds):
        named = collections.Counter()                   # nets nextpnr reports it can't route, over this round's seeds
        for s in range(1, seeds + 1):
            rc = run([NPNR, "--device", "10CL016", "--json", netlist, "--router", "router1", "--seed", str(s),
                      "--write", routed] + extra, log)
            if rc == 0:
                print(f"round {rnd}: routed with seed {s}", flush=True)
                return subprocess.run([sys.executable, os.path.join(HERE, "nextpnr", "npnr2asm.py"), routed, side, top]).returncode
            mm = re.search(r"Failed to find a route for arc \d+ of net (\S+)\.", open(log).read())
            if mm:
                named[(mm.group(1), s)] += 1
        text = open(log).read()
        m = re.match(r"(\S+)", named.most_common(1)[0][0][0]) if named else None
        seed_of = {n: sd for (n, sd) in named}
        if not m:
            print(f"round {rnd}: no seed routes, and nextpnr names no net:\n{text[-600:]}")
            return 1
        net = m.group(1)
        placed = os.path.join(OUT, f"npnr_{top}_placed.json")
        run([NPNR, "--device", "10CL016", "--json", netlist, "--seed", str(seed_of[net]), "--no-route", "--write", placed]
            + extra, log + ".place")
        mod = next(iter(json.load(open(placed))["modules"].values()))
        bit = mod["netnames"][net]["bits"][0]
        ends = [(c["attributes"]["NEXTPNR_BEL"], p) for c in mod["cells"].values()
                for p, bb in c["connections"].items() if bit in bb]
        lab = lambda b: tuple(map(int, b.split("/")[0][1:].split("Y")))
        src_bel = next(b for b, p in ends if p in ("F", "Q"))
        src = lab(src_bel)
        slot = 2 * int(re.search(r"/LE(\d+)_", src_bel).group(1))
        sinks = sorted({lab(b) for b, p in ends if p not in ("F", "Q")} - {src})
        # xrkn builds whose random source slots include the failing LE's slot (its buffers are what's missing)
        import random
        found = [sd for sd in range(5000 + 1000 * rnd, 6000 + 1000 * rnd)
                 if slot in random.Random(sd).sample(range(0, 32, 2), 8)][:2]
        print(f"round {rnd}: net {net} from LAB {src} slot N{slot} to {sinks}: probing on demand (seeds {found})",
              flush=True)
        for snk in sinks:
            dx, dy = snk[0] - src[0], snk[1] - src[1]
            for sd in found:
                subprocess.run([sys.executable, os.path.join(HERE, "mapping", "tapforce.py"), "--job",
                                f"{src[0]},{src[1]},{dx},{dy},{sd}"])
        subprocess.run([sys.executable, os.path.join(HERE, "lib", "switchmodel.py"), "build"], stdout=subprocess.DEVNULL)
        subprocess.run([os.path.join(HERE, "nextpnr", "build_chipdb.sh")], stdout=subprocess.DEVNULL)
    print(f"no routing after {rounds} rounds")
    return 1


if __name__ == "__main__":
    sys.exit(main())
