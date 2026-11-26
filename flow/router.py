#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Our own router for a placed tpatch template: chooses every LUT input's source and physical port.

For each LUT input (signal s into LE d), candidates are
  - the source LE's local line (LOCAL_LINE, I = slot / 2) if s comes from d's own LAB;
  - a LAB line L of d's LAB reached from one of the source LE's buffers by a switch the model prices
    (local feedback in the same LAB, neighbour links at dx = +/-1: switchmodel.Model.bits);
and the (d, physical input, source node) code must be known (measured at this placement: out/posmux_NAME.json).
The LE's own register feedback is hard-wired to input 0; constant inputs take a free input.  A LAB line carries one
signal.  Backtracking over LEs, most-constrained first.  Nets that don't end in a LUT (the output to the pin) keep the
given path (the output-path bundle's path).  Writes the routes as .rcf text (dest logical ports as in the reference
.rcf, which uses Quartus's synthesised port names) for asm.py and for a Quartus build with the route forced.

  router.py NAME [--counter] [--dw]     (--dw: only (input, source) pairs with a die-wide code, limux_dw.py)
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import asm  # noqa: E402
import rcfforce as F  # noqa: E402
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
INV = {v: k for k, v in asm.PHYS.items()}            # lutpos input -> .rcf port name


PAIRS = os.path.join(OUT, "neighbour_pairs.json")


def seen_neighbour_pairs(rebuild: bool = False) -> set:
    """(buffer index, dx, line index) of LE_BUFFER -> LAB line hops seen in a real route (corpus exact solves and every
    RCF project's routing).  Read from out/neighbour_pairs.json (shipped); rebuild=True rescans the sources (the
    corpus and this machine's RCF work dirs) and rewrites it."""
    if not rebuild and os.path.exists(PAIRS):
        return {tuple(t) for t in json.load(open(PAIRS))}
    import glob
    seen_nb = set()
    for k in json.load(open(os.path.join(OUT, "hopsolve.json"))):
        mm = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)->LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", k)
        if mm and mm.group(2) == mm.group(5):
            seen_nb.add((int(mm.group(3)), int(mm.group(4)) - int(mm.group(1)), int(mm.group(6))))
    for f in glob.glob(os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcf*", "work", "*", "base.rcf")):
        for bl in F.branches(open(f).read()).values():
            for path, _d in bl:
                for u, v in zip(path, path[1:]):
                    mu = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$", u)
                    mv = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", v)
                    if mu and mv and mu.group(2) == mv.group(2):
                        seen_nb.add((int(mu.group(3)), int(mv.group(1)) - int(mu.group(1)), int(mv.group(3))))
    json.dump(sorted(seen_nb), open(PAIRS, "w"))
    return seen_nb


_WP = {}


def wire_paths(m, buf: str, dx: int, dy: int, avoid: frozenset = frozenset(), maxwires: int = 3) -> list:
    """[buf, R4, (R4, ...), LAB line of LAB (dx, dy)] paths over hops the switch model m prices, shortest first."""
    key = (buf, dx, dy, avoid, maxwires)
    if key in _WP:
        return _WP[key]
    out, frontier = [], [[buf]]
    for _depth in range(maxwires):
        nxt = []
        for path in frontier:
            for v in dict(m.fanout(path[-1])):
                if v in path or v in avoid:
                    continue
                if v.startswith("LOCAL_INTERCONNECT") and len(path) > 1:
                    pv = S.parse(v)
                    if (pv[1], pv[2]) == (dx, dy):
                        out.append(path + [v])
                elif v.startswith("R4_"):
                    nxt.append(path + [v])
        frontier = nxt[:400]
    _WP[key] = out
    return out


def route(name: str, les: dict, ref_rcf: str, masks: dict | None = None, dw: dict | None = None,
          insts: dict | None = None, avoid: set | None = None, multihop: bool = False):
    """insts: a design dict (ynet.py) instead of the template `name`'s netlist; ref_rcf may then be empty (dest logical
    ports default to the physical port name).  avoid: resources not to use (e.g. ones Quartus rejected as illegal).
    multihop: also route between LABs of one row over priced wire hops (buffer -> R4 [-> R4 ...] -> LAB line)."""
    insts = insts if insts is not None else asm.instances(name)
    for i, m in (masks or {}).items():
        insts[i]["mask"] = m
    known = collections.defaultdict(set)              # (x, y, n) -> {(input, source node)}
    if dw is not None:
        # die-wide codes (limux_dw.py): every placed LE accepts the (input, source) pairs whose key has a code
        for inst, (x, y, n) in les.items():
            for inp in range(4):
                for k in range(38):
                    if f"LI|{k}|{inp}|{(n // 2) % 2}" in dw:
                        known[(x, y, n)].add((inp, f"LOCAL_INTERCONNECT_X{x}_Y{y}_N0_I{k}"))
                for k in range(16):
                    if f"LL|{k}|{inp}|{(n // 2) % 2}" in dw:
                        known[(x, y, n)].add((inp, f"LOCAL_LINE_X{x}_Y{y}_N0_I{k}"))
    else:
        pm = json.load(open(os.path.join(OUT, f"posmux_{name}.json")))
        for k in pm:
            x, y, n, inp, src = k.split("|")
            known[(int(x), int(y), int(n))].add((int(inp), src))
    m = S.Model()
    # neighbour links: the driver bits are per source slot, the same for both of its buffers, so they don't tell which
    # buffer reaches which line.  Use only (buffer index, dx, line index) seen in a real route: corpus exact solves and
    # every RCF project's routing (blink24p: buffer I30 -> line 29 at dx +1 is illegal, I31 -> 29 is legal)
    seen_nb = seen_neighbour_pairs()
    src_le = {}                                       # signal -> source LE
    for inst, d in insts.items():
        if inst in les:
            src_le[d["net"]] = les[inst]
            if d.get("registered"):
                src_le[d["q"]] = les[inst]
    lport = {}                                        # (inst, signal) -> logical port name used by Quartus's netlist
    by_net = {d["net"]: i for i, d in insts.items()}
    for sig, bl in F.branches(ref_rcf).items():
        for path, (dinst, lp, pp) in bl:
            inst = dinst if dinst in insts else by_net.get(dinst)
            if inst:
                lport[(inst, sig)] = (dinst, lp)

    def sources(sig, d):
        """Candidate (source node, [hop path]) for signal sig at destination LE d."""
        sx, sy, sn = src_le[sig]
        dx, dy, _ = d
        out = []
        if (sx, sy) == (dx, dy):
            out.append((f"LOCAL_LINE_X{sx}_Y{sy}_N0_I{sn // 2}", [f"LOCAL_LINE_X{sx}_Y{sy}_N0_I{sn // 2}"]))
        if dy == sy and abs(dx - sx) <= 1:
            for b in (sn, sn + 1):
                buf = f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}"
                for li in range(38):
                    L = f"LOCAL_INTERCONNECT_X{dx}_Y{dy}_N0_I{li}"
                    if m.bits(buf, L) is not None and (b, dx - sx, li) in seen_nb and buf not in (avoid or ()):
                        out.append((L, [buf, L]))
        if dy == sy and (sx, sy) != (dx, dy) and multihop:
            for b in (sn, sn + 1):
                for path in wire_paths(m, f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}", dx, dy, frozenset(avoid or ())):
                    out.append((path[-1], path))
        return out

    # what each LE needs
    needs = {}
    for inst, d in insts.items():
        if inst not in les:
            continue
        loc = les[inst]
        sigs = []
        for p in asm.PORTS:
            s = d["inputs"].get(p)
            if s is None or s.startswith("1'b"):
                continue
            if d.get("registered") and s == d["q"]:
                continue                              # own register feedback: input 0, hard-wired
            if s in src_le:
                sigs.append(s)
        needs[inst] = (loc, sigs)
    line_owner = {}                                   # LAB line -> signal
    choice = {}                                       # (inst, signal) -> (input, source node, path)

    def options(inst):
        loc, sigs = needs[inst]
        own = 0 if insts[inst].get("registered") and any(
            insts[inst]["inputs"].get(p) == insts[inst]["q"] for p in asm.PORTS) else None
        opts = {}
        for s in sigs:
            opts[s] = [(inp, node, path) for node, path in sources(s, loc) for inp in range(4)
                       if (inp, node) in known[loc] and inp != own]
        return opts

    order = sorted(needs, key=lambda i: sum(len(v) for v in options(i).values()))

    def solve(k):
        if k == len(order):
            return True
        inst = order[k]
        opts = options(inst)
        sigs = sorted(opts, key=lambda s: len(opts[s]))

        def assign(j, used_inputs):
            if j == len(sigs):
                return solve(k + 1)
            s = sigs[j]
            for inp, node, path in opts[s]:
                if inp in used_inputs:
                    continue
                # every routing node (LAB lines and wires) carries one signal; the source buffer is the LE's own
                held = [n for n in path if not n.startswith(("LE_BUFFER", "LOCAL_LINE"))]
                if any(line_owner.get(n, s) != s for n in held):
                    continue
                fresh = [n for n in held if n not in line_owner]
                for n in fresh:
                    line_owner[n] = s
                choice[(inst, s)] = (inp, node, path)
                if assign(j + 1, used_inputs | {inp}):
                    return True
                del choice[(inst, s)]
                for n in fresh:
                    del line_owner[n]
            return False

        return assign(0, set())

    if not solve(0):
        return None, None
    # emit .rcf blocks: one branch per (signal, destination); nets that don't end in a LUT keep the reference path
    # Branches sharing a multi-resource path: the first lists it with a label on its last resource, the others start
    # from it with branch_point (Quartus rejects the same resource listed twice in one net, local lines included).
    # A branch that shares a prefix with an earlier branch of the same signal starts with branch_point at the last
    # shared resource; every resource written gets a label, so later branches can start from any of them.
    blocks = collections.defaultdict(list)
    written = collections.defaultdict(list)            # signal -> paths written so far
    for (inst, s), (inp, node, path) in sorted(choice.items()):
        # Quartus names a LUT cell by its output net; the logical port is where s enters it in the netlist
        logical = next((p for p, v in insts[inst]["inputs"].items() if v == s), INV[inp])
        dname, lp = lport.get((inst, s), (insts[inst]["net"], logical))
        dest = f"\tdest = ( {dname}, {lp} ), route_port = {INV[inp]};"
        share = max((next((i for i, (a, b) in enumerate(zip(q, path)) if a != b), min(len(q), len(path)))
                     for q in written[s]), default=0)
        text = f"\tbranch_point = Label_{F.rcf_name(path[share - 1])};\n" if share else ""
        text += "".join(f"\tlabel = Label_{F.rcf_name(n)}, {F.rcf_name(n)};\n" for n in path[share:])
        written[s].append(path)
        blocks[s].append(text + dest)
    text = []
    for m_ in re.finditer(r"signal_name = (\S+) \{(.*?)\n\}", ref_rcf, re.S):
        sig = m_.group(1)
        if sig in blocks:
            text.append(f"signal_name = {sig} {{\n" + "\n\n".join(blocks[sig]) + "\n}")
        else:
            text.append(m_.group(0))
    done = {m_.group(1) for m_ in re.finditer(r"signal_name = (\S+) \{", ref_rcf)}
    for sig in sorted(blocks):                         # signals the reference doesn't have (no reference: all of them)
        if sig not in done:
            text.append(f"signal_name = {sig} {{\n" + "\n\n".join(blocks[sig]) + "\n}")
    head = ref_rcf[:ref_rcf.index("signal_name")] if "signal_name" in ref_rcf else ""
    return head + "\n".join(text) + "\n", choice


def main() -> int:
    import explain as E
    import tpatch
    name = sys.argv[1]
    masks = asm.counter_masks(name) if "--counter" in sys.argv else None
    job = tpatch.job(name, [masks[i] if masks else mk for i, mk in xdev.tpl_luts(name)])
    pr = F.Project(job, E.ROOT)
    t = tpatch.Template(name, partial=True)
    dw = json.load(open(os.path.join(OUT, "limux_dw.json"))) if "--dw" in sys.argv else None
    rcf, choice = route(name, t.les, pr.base_rcf, masks, dw)
    if rcf is None:
        print("no routing found with known switches and measured codes")
        return 1
    p = os.path.join(OUT, f"route_{name}{'_counter' if masks else ''}{'_dw' if dw else ''}.rcf")
    open(p, "w").write(rcf)
    same = sum(1 for (inst, s), (inp, node, path) in choice.items()
               if any(path == bp and asm.PHYS.get(d[2]) == inp for bp, d in F.branches(pr.base_rcf).get(s, [])))
    print(f"routed {len(choice)} LUT inputs; {same} identical to Quartus's choice, {len(choice) - same} different -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
