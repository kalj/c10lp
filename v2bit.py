#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verilog -> Yosys LUT4 netlist -> tpatch template -> 10CL016 bitstream.

The design's top module must use ports A, B, C, D (inputs = D1..D4) and Q
(output = D5); registers are clocked by B (D2).  Yosys maps it to 4-input
LUTs and D flip-flops.  `init` turns that netlist into a tpatch template
(asymmetric placeholder masks so the base build reveals each LUT's input
order) and lets Quartus place and route it once.  `write` re-synthesizes a
(possibly edited) design: if the LUT/flip-flop netlist has the same structure
as the template, only the LUT contents differ, and the bitstream is written
without Quartus.  `board` checks the result on the Vidor against a simulation
of the Yosys netlist (clocked designs: random inputs, clocked by D2).

  v2bit.py init  design.v NAME          synthesize, make templates/NAME, run tpatch init (2 compiles)
  v2bit.py write design.v NAME -o x.rbf write the bitstream for design.v into NAME's placement
  v2bit.py board design.v NAME x.rbf    load (SRAM) and test, 16 combos or 60 clocked steps
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpos  # noqa: E402

PORTS_IN = "ABCD"
HERE_DIR = HERE


def synth(path: str) -> dict:
    """Yosys: flatten, map to <=4-input LUTs and positive-edge D flip-flops; return the netlist."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "net.json")
        script = (f"read_verilog {path}; synth -flatten -top top; "
                  "dfflegalize -cell $_DFF_P_ 0; abc -lut 4; opt_clean; "
                  f"write_json {out}")
        r = subprocess.run(["yosys", "-q", "-p", script], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("yosys failed:\n" + r.stderr[-1500:])
        mod = json.load(open(out))["modules"]["top"]
    ports = mod["ports"]
    if set(ports) - set("ABCDQ") or "Q" not in ports:
        raise SystemExit(f"top must have ports A, B, C, D (inputs) and Q (output); got {sorted(ports)}")
    bitname = {}
    for p, d in ports.items():
        for b in d["bits"]:
            bitname[b] = p
    luts, ffs = [], []
    for name, c in mod["cells"].items():
        if c["type"] == "$lut":
            w = c["parameters"]["WIDTH"]
            w = int(w, 2) if isinstance(w, str) else w
            m = c["parameters"]["LUT"]
            m = int(m, 2) if isinstance(m, str) else m
            luts.append(dict(ins=c["connections"]["A"], out=c["connections"]["Y"][0], width=w, mask=m))
        elif c["type"] == "$_DFF_P_":
            ffs.append(dict(c=c["connections"]["C"][0], d=c["connections"]["D"][0], q=c["connections"]["Q"][0]))
        else:
            raise SystemExit(f"unsupported cell {c['type']} (only LUTs and $_DFF_P_)")
    for f in ffs:
        if bitname.get(f["c"]) != "B":
            raise SystemExit("registers must be clocked by port B (D2)")
    q = ports["Q"]["bits"][0]
    return dict(luts=luts, ffs=ffs, q=q, bitname=bitname)


def mask16(lut: dict) -> int:
    """The LUT's function as a 16-bit mask that ignores the padded (unused) inputs."""
    w, m = lut["width"], lut["mask"]
    return sum((m >> (i & ((1 << w) - 1)) & 1) << i for i in range(16))


def structure(net: dict) -> list:
    """Connectivity signature (everything except LUT contents)."""
    return [(tuple(map(str, l["ins"])), str(l["out"]), l["width"]) for l in net["luts"]] + \
           [(str(f["d"]), str(f["q"])) for f in net["ffs"]] + [str(net["q"])]


def save_net(net: dict, path: str) -> None:
    json.dump(dict(net, bitname={str(k): v for k, v in net["bitname"].items()}), open(path, "w"))


def load_net(path: str) -> dict:
    net = json.load(open(path))
    net["bitname"] = {int(k): v for k, v in net["bitname"].items()}
    return net


def match(tmpl: dict, new: dict, max_subst: int = 0, subst_out: list | None = None):
    """Map the new netlist onto the template's: same ports, LUT widths and connectivity, any
    relabelling of internal nets and any reordering of a LUT's inputs.  With max_subst > 0, up to
    that many LUT inputs may instead be driven by a *different* existing template net; those
    (template LUT, template input index, new template net) go to subst_out.  Returns, for each
    template LUT index, the new LUT's mask permuted into the template LUT's input order; or None."""
    tl, nl = tmpl["luts"], new["luts"]
    if len(tl) != len(nl) or len(tmpl["ffs"]) != len(new["ffs"]):
        return None
    import itertools
    fixed = {}
    for b, p in new["bitname"].items():
        tb = [k for k, q in tmpl["bitname"].items() if q == p]
        fixed[b] = tb[0] if tb else None
    def key(b):
        return ("const", b) if isinstance(b, str) else b

    def unify(m, nb, tb):
        nb, tb = key(nb), key(tb)
        if isinstance(nb, tuple) or isinstance(tb, tuple):
            return m if nb == tb else None
        if nb in fixed and fixed[nb] != tb:
            return None
        if m.get(nb, tb) != tb or (tb in m.values() and m.get(nb) != tb):
            return None
        m = dict(m)
        m[nb] = tb
        return m

    q_out = key(new["q"])
    order = sorted(range(len(nl)), key=lambda i: key(nl[i]["out"]) == q_out)   # output LUT last

    def search(ii, m, used, out, subs):
        if ii == len(nl):
            # registers: every new FF must map to a template FF with matching d and q
            for f in new["ffs"]:
                if not any(m.get(key(f["q"])) == key(g["q"]) and m.get(key(f["d"])) == key(g["d"])
                           for g in tmpl["ffs"]):
                    return None
            if m.get(key(new["q"])) != key(tmpl["q"]):
                return None
            if subst_out is not None:
                subst_out[:] = subs
            return m
        i = order[ii]
        L = nl[i]
        for j, T in enumerate(tl):
            if j in used or T["width"] != L["width"]:
                continue
            for perm in itertools.permutations(range(L["width"])):
                m2, s2 = unify(m, L["out"], T["out"]), list(subs)
                for k in range(L["width"]):
                    if m2 is None:
                        break
                    m3 = unify(m2, L["ins"][k], T["ins"][perm[k]])
                    if m3 is None and len(s2) < max_subst and key(L["ins"][k]) in m2 \
                            and not isinstance(key(L["ins"][k]), tuple):
                        # input k now driven by another, already-mapped template net
                        s2.append((j, perm[k], m2[key(L["ins"][k])]))
                        m3 = m2
                    m2 = m3
                if m2 is None:
                    continue
                out[j] = (i, perm)
                r = search(ii + 1, m2, used | {j}, out, s2)
                if r is not None:
                    return r
        return None

    out = {}
    if search(0, {}, frozenset(), out, []) is None:
        return None
    res = {}
    for j, (i, perm) in out.items():
        L, w = nl[i], nl[i]["width"]
        m = 0
        for idx in range(1 << w):                       # new input k sits on template input perm[k]
            tidx = sum((idx >> k & 1) << perm[k] for k in range(w))
            m |= (L["mask"] >> idx & 1) << tidx
        res[j] = m
    return res


def netname(net: dict, b) -> str:
    if isinstance(b, str):                  # Yosys constant "0" / "1"
        return "1'b0" if b == "0" else "1'b1"
    return net["bitname"].get(b, f"n{b}")


def template_verilog(net: dict, seed: int = 1) -> str:
    r = random.Random(seed)
    lines = ["// SPDX-License-Identifier: GPL-3.0-or-later",
             "// Generated by v2bit.py from a Yosys LUT4 netlist. Placeholder masks are random",
             "// asymmetric ones (lutpos.unique_perm_mask); tpatch.py rewrites them.",
             "module fuzz_top(input wire A, B, C, D, output wire Q);"]
    internal = sorted(({b for l in net["luts"] for b in l["ins"] + [l["out"]] if not isinstance(b, str)} |
                       {b for f in net["ffs"] for b in (f["d"], f["q"])}) - set(net["bitname"]))
    regs = {f["q"] for f in net["ffs"]}
    for b in internal:
        # noprune: Quartus must keep every register, even ones the base design doesn't read
        lines.append(f"  {'(* noprune *) reg ' if b in regs else 'wire'} n{b};")
    for k, l in enumerate(net["luts"]):
        while True:
            ph = r.randrange(1, 0xFFFF)
            if lutpos.unique_perm_mask(ph):
                break
        ins = [netname(net, b) for b in l["ins"]] + ["1'b0"] * (4 - l["width"])
        lines.append(f"  cyclone10lp_lcell_comb #(.lut_mask(16'h{ph:04X}), .sum_lutc_input(\"datac\"), "
                     f".dont_touch(\"on\"))\n    l{k} (" +
                     ", ".join(f".data{c}({v})" for c, v in zip("abcd", ins)) +
                     f", .combout({netname(net, l['out'])}));")
    for f in net["ffs"]:
        lines.append(f"  always @(posedge B) n{f['q']} <= {netname(net, f['d'])};")
    if net["bitname"].get(net["q"]) != "Q":
        lines.append(f"  assign Q = {netname(net, net['q'])};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


class Sim:
    """Netlist simulator: LUTs evaluated to a fixed point, registers power up 0, clocked by B."""

    def __init__(self, net: dict):
        self.net = net
        self.state = {f["q"]: 0 for f in net["ffs"]}

    def _eval(self, pins: dict) -> dict:
        v = dict(self.state)
        for b, p in self.net["bitname"].items():
            if p in pins:
                v[b] = pins[p]
        val = lambda b: (0 if b == "0" else 1) if isinstance(b, str) else v.get(b)   # noqa: E731
        for _ in range(len(self.net["luts"]) + 1):
            for l in self.net["luts"]:
                ins = [val(b) for b in l["ins"]]
                if None not in ins:
                    v[l["out"]] = l["mask"] >> sum(x << i for i, x in enumerate(ins)) & 1
        return v

    def q(self, pins: dict) -> int:
        return self._eval(pins)[self.net["q"]]

    def clock(self, pins: dict) -> None:
        v = self._eval(pins)
        self.state = {f["q"]: v[f["d"]] for f in self.net["ffs"]}


def write_design(t, tnet: dict, net: dict, tdir: str):
    """Bitstream for netlist `net` in template t: LUT contents, plus direct rewires (li_direct.json
    rule) when up to 2 LUT inputs changed source.  Returns (bytes, extra gate cells, note)."""
    import gate
    import lutpatch
    import rbfgeom
    import tpatch
    for k in range(3):
        subs = []
        mapped = match(tnet, net, max_subst=k, subst_out=subs)
        if mapped is not None:
            break
    if mapped is None:
        raise SystemExit("the netlist doesn't fit the template's structure; run init again (needs Quartus)")
    masks = {f"l{j}": mask16(dict(tnet["luts"][j], mask=m)) for j, m in mapped.items()}
    data = t.write(masks)
    if not subs:
        return data, set(), ""
    table = {tuple(map(int, k.split(","))): [tuple(v) for v in vs]
             for k, vs in json.load(open(os.path.join(HERE, "li_local_table.json")))["entries"].items()}
    direct = {int(k): set(v) for k, v in json.load(open(os.path.join(HERE, "li_direct.json"))).items()}
    locs = open(os.path.join(tdir, "locs.qsf")).read()
    where = {inst.strip('"'): (kind, int(x), int(y), int(n))
             for kind, x, y, n, inst in tpatch.LOC_RE.findall(locs)}

    def slot_of(b):                       # template net -> (LAB, LE slot) of its driver
        w = where.get(f"n{b}") if not isinstance(b, str) else None
        if w is None:
            return None
        return (w[1], w[2]), (w[3] - 1 if w[0] == "FF" else w[3])

    def readers(b):                       # (LUT instance, physical input) reading template net b
        res = []
        for j, L in enumerate(tnet["luts"]):
            for k, nb in enumerate(L["ins"]):
                if nb == b:
                    res.append((f"l{j}", t.perms[f"l{j}"][k]))
        return res

    buf = bytearray(data)
    v = [lutpatch.header_sum(data)]
    extra = set()
    notes = []
    for j, k, new_b in subs:
        inst = f"l{j}"
        x, y, d = t.les[inst]
        p = t.perms[inst][k]
        old_b = tnet["luts"][j]["ins"][k]
        so, sn = slot_of(old_b), slot_of(new_b)
        if so is None or sn is None or so[0] != (x, y) or sn[0] != (x, y):
            raise SystemExit(f"{inst} input {k}: old or new source isn't an LE in the same LAB")
        s_old, s_new = so[1], sn[1]
        if p not in direct.get(s_new, ()):
            raise SystemExit(f"{inst}: physical input {p} isn't a direct input of slot {s_new} "
                             f"(direct: {sorted(direct.get(s_new, ()))}); needs the second path")
        driven = [(i2, q) for i2, q in readers(new_b) if q in direct[s_new]
                  and t.les[i2][:2] == (x, y) and i2 != inst]
        if not driven:
            raise SystemExit(f"slot {s_new}'s local line isn't driven by a direct reader in the template")
        if (p, s_old) not in table or (p, s_new) not in table:
            raise SystemExit(f"no table entry for input {p} with source {s_old} or {s_new}")
        cells = lutpos._predict_phys(x, y, d)
        f0, lo, bit = min(c[0] for c in cells), min(c[1] for c in cells), cells[0][2]
        flip = (d // 2) % 2
        for df, col in set(table[(p, s_old)]) ^ set(table[(p, s_new)]):
            f, pb = f0 + df, lo + (col - 2 if flip else col)
            off = 32 + f * 255 + pb
            w = lutpos.header_weight(f, pb, bit)
            v[0] += -w if buf[off] >> bit & 1 else w
            buf[off] ^= 1 << bit
            extra.add((f, pb, bit))
        notes.append(f"{inst} input {p}: slot {s_old} -> {s_new}")
    lutpatch.patch_crc(buf, rbfgeom.infer(data))
    lutpatch.set_header_sum(buf, v[0] % (1 << 32))
    new = bytes(buf)
    errs = gate.check(t.zero, new, [t.les[i] for i in t.luts], extra_cells=extra)
    if errs:
        raise SystemExit(f"gate refused the rewired file: {errs}")
    return new, extra, " with rewires (" + "; ".join(notes) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "write", "board", "synth"])
    # synth: print the generated template (no Quartus)
    ap.add_argument("design")
    ap.add_argument("name", nargs="?")
    ap.add_argument("rbf", nargs="?")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    net = synth(a.design)
    if a.cmd == "synth":
        print(f"{len(net['luts'])} LUTs, {len(net['ffs'])} flip-flops")
        print(template_verilog(net))
        return 0
    import gate
    import hwtest
    import tpatch
    import xdev
    tdir = os.path.join(xdev.TEMPLATE_DIR, a.name)
    if a.cmd == "init":
        os.makedirs(tdir, exist_ok=True)
        open(os.path.join(tdir, "top.v"), "w").write(template_verilog(net))
        # Quartus drops registers nothing reads ("lost fanout") unless told to keep them.
        with open(os.path.join(tdir, "extra.qsf"), "w") as f:
            f.write("# v2bit.py: keep every register, even ones the base design doesn't read\n")
            for ff in net["ffs"]:
                f.write(f"set_instance_assignment -name PRESERVE_REGISTER ON -to n{ff['q']}\n")
        save_net(net, os.path.join(tdir, "net.json"))
        print(f"{len(net['luts'])} LUTs, {len(net['ffs'])} flip-flops -> {tdir}")
        return tpatch.init(a.name)

    t = tpatch.Template(a.name)
    data_new, extra, note = write_design(t, load_net(os.path.join(tdir, "net.json")), net, tdir)
    if a.cmd == "write":
        if not a.output:
            raise SystemExit("write needs -o")
        open(a.output, "wb").write(data_new)
        print(f"wrote {a.output}: {len(t.luts)} LUTs from {a.design}{note}, gate PASS")
        return 0

    # board
    data = open(a.rbf, "rb").read()
    errs = gate.check(t.zero, data, [t.les[i] for i in t.luts], extra_cells=extra)
    if errs or data != data_new:
        raise SystemExit(f"{a.rbf} is not this design written into this template: {errs}")
    bench = hwtest.Bench("/dev/ttyACM0")
    bench.cmd("I")
    rc, _ = hwtest.run(["openFPGALoader", "-c", "usb-blaster", a.rbf], False)
    if rc:
        raise SystemExit(f"STOP: load failed (exit {rc})")
    bench.cmd("A")
    sim, wrong = Sim(net), []                # the *new* design's netlist is the reference

    def read(A, B, C, D):
        got, seen = bench.read((A, B, C, D))
        if seen != f"{A}{B}{C}{D}":
            bench.cmd("I")
            raise SystemExit(f"STOP: D1..D4 read back {seen}")
        return int(got == "h")
    if not net["ffs"]:
        for ds in hwtest.COMBOS4:
            pins = dict(zip(PORTS_IN, ds))
            if read(*ds) != sim.q(pins):
                wrong.append("".join(map(str, ds)))
        n = 16
    else:
        rnd, n = random.Random(1), 60
        A = C = D = 1
        read(A, 0, C, D)
        for step in range(n):
            A, C, D = rnd.randrange(2), rnd.randrange(2), rnd.randrange(2)
            pins = dict(A=A, B=0, C=C, D=D)
            if read(A, 0, C, D) != sim.q(pins):
                wrong.append(f"before edge {step}")
            sim.clock(pins)
            if read(A, 1, C, D) != sim.q(dict(pins, B=1)):
                wrong.append(f"after edge {step}")
            read(A, 0, C, D)
    bench.cmd("I")
    print(f"{a.rbf}: " + ("PASS" if not wrong else f"FAIL {wrong[:6]}") +
          f" ({n} {'clocked steps' if net['ffs'] else 'input combinations'})")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
