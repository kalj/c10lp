#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Force a route for one net with a Routing Constraints File (.rcf) and let Quartus be the oracle.

Quartus writes a routing back-annotation (quartus_cdb --back_annotate=routing -> fuzz.rcf) listing each net's
routing resources in order, and reads one back when the project has
  ROUTING_BACK_ANNOTATION_FILE fuzz.rcf, ROUTING_BACK_ANNOTATION_MODE NORMAL.
Replacing one net's path in that file and refitting gives:
  - legality: the fitter reports "Error on line N in Routing Constraints File" for a hop that doesn't exist and
    reroutes that fan-out itself (force() reports it as "rcf error at hop k", k counted from the net's first
    resource); an honoured route reappears unchanged in a fresh back-annotation;
  - bits: base and forced builds differ in exactly that net, so their XOR is the bits of the old and new hops.
Raw .rcf files stay in the scratch work directory; nothing here is committed except derived results.

  rcfforce.py demo
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xdev  # noqa: E402

Q = os.path.dirname(xdev.tool("quartus_cdb"))
NODE = re.compile(r"^(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$")


def rcf_name(node: str) -> str:
    """R4_X14_Y22_N0_I18 -> R4:X14Y22S0I18 (the .rcf spelling)."""
    t, x, y, i = NODE.match(node).groups()
    return f"{t}:X{x}Y{y}S0I{i}"


def node_name(r: str) -> str:
    m = re.match(r"(\w+):X(\d+)Y(\d+)S0I(\d+)$", r)
    t, x, y, i = m.groups()
    return f"{t}_X{x}_Y{y}_N0_I{i}"


def run(work: str, *args, tool="quartus_cdb"):
    r = subprocess.run([os.path.join(Q, tool), "fuzz", "-c", "fuzz", *args], cwd=work, capture_output=True, text=True,
                       timeout=1200)
    return r.returncode, r.stdout + r.stderr


def nets(rcf: str) -> dict[str, list[str]]:
    """signal name -> [resource, ...] (one path per signal; multi-fanout signals keep the first branch)."""
    out = {}
    for m in re.finditer(r"signal_name = (\S+) \{(.*?)\n\}", rcf, re.S):
        out[m.group(1)] = re.findall(r"^\t(\w+:X\d+Y\d+S0I\d+);", m.group(2), re.M)
    return out


class Project:
    """A kept Quartus work directory for one job, with its own back-annotated .rcf as the base."""

    def __init__(self, job: xdev.Job, root: str):
        self.work = os.path.join(root, "work", job.name)
        if not os.path.isdir(self.work):
            for ext in (".rbf", ".json"):                  # build_one skips jobs whose outputs already exist
                if os.path.exists(os.path.join(root, job.name + ext)):
                    os.remove(os.path.join(root, job.name + ext))
            m = xdev.build_one(job, root, True)
            if not m["ok"]:
                raise SystemExit(f"{job.name}: build failed")
        self.rbf = lambda: open(self._rbf_path(), "rb").read()
        if not os.path.exists(os.path.join(self.work, "base.rcf")):
            cached = xdev.load(os.path.join(HERE, "out"), job.name)
            if cached is not None and cached != self.rbf():
                raise SystemExit(f"{job.name}: rebuilt RBF differs from the cached one")
            rc, out = run(self.work, "--back_annotate=routing")
            if rc:
                raise SystemExit(out[-500:])
            shutil.copy(os.path.join(self.work, "fuzz.rcf"), os.path.join(self.work, "base.rcf"))
            shutil.copy(self._rbf_path(), os.path.join(self.work, "base.rbf"))
        self.base_rcf = open(os.path.join(self.work, "base.rcf")).read()
        self.base_rbf = open(os.path.join(self.work, "base.rbf"), "rb").read()

    def _rbf_path(self):
        """Convert the current SOF to an uncompressed RBF, as xdev.build_one does."""
        p = os.path.join(self.work, "current.rbf")
        r = subprocess.run([os.path.join(Q, "quartus_cpf"), "-c", "-o", "bitstream_compression=off",
                            "output_files/fuzz.sof", p], cwd=self.work, capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise SystemExit("quartus_cpf failed: " + (r.stdout + r.stderr)[-300:])
        return p

    def force(self, signal: str, old: list[str], new: list[str]):
        """Replace the consecutive resources old (node names) of signal by new, refit.  Returns
        (honoured, rbf, message): honoured is True if a fresh back-annotation shows exactly the new resources."""
        rcf = self.base_rcf
        blk0 = rcf.index(f"signal_name = {signal} {{")
        blk1 = rcf.index("\n}", blk0)
        o = "".join(f"\t{rcf_name(n)};\n" for n in old)
        n = "".join(f"\t{rcf_name(x)};\n" for x in new)
        blk = rcf[blk0:blk1 + 1]
        if o not in blk:
            raise ValueError(f"{old} not in {signal}'s path")
        open(os.path.join(self.work, "fuzz.rcf"), "w").write(rcf[:blk0] + blk.replace(o, n, 1) + rcf[blk1 + 1:])
        sig_line = rcf[:blk0].count("\n") + 1                # file line of "signal_name = ..."; resources follow
        self._qsf(True)
        try:
            rc, out = run(self.work, tool="quartus_fit")
            errs = re.findall(r"Error on line number (\d+) in Routing Constraints File", out)
            if rc:
                return False, None, "fit failed"
            rc, _ = run(self.work, tool="quartus_asm")
            data = self.rbf()
            run(self.work, "--back_annotate=routing")
            got = nets(open(os.path.join(self.work, "fuzz.rcf")).read()).get(signal, [])
            want = [rcf_name(x) for x in new]
            ok = any(got[i:i + len(want)] == want for i in range(len(got)))
            # an error is reported by line; hop k = k-th resource line of this net (0 = first resource)
            return ok and not errs, data, (f"rcf error at hop {int(errs[0]) - sig_line - 1}" if errs
                                           else "honoured" if ok else "rerouted")
        finally:
            self._qsf(False)
            shutil.copy(os.path.join(self.work, "base.rcf"), os.path.join(self.work, "fuzz.rcf"))

    def _qsf(self, on: bool):
        p = os.path.join(self.work, "fuzz.qsf")
        lines = [ln for ln in open(p) if "ROUTING_BACK_ANNOTATION" not in ln]
        if on:
            lines += ["set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE fuzz.rcf\n",
                      "set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL\n"]
        open(p, "w").writelines(lines)


def xor_cells(a: bytes, b: bytes):
    """Differing core bits as (frame, byte, plane), CRC bytes excluded."""
    out = []
    for i in range(32 + 37 * 255, min(len(a), len(b))):
        x = a[i] ^ b[i]
        if x:
            f, p = divmod(i - 32, 255)
            if p < 253:
                out += [(f, p, k, (b[i] >> k) & 1) for k in range(8) if x >> k & 1]
    return out


def _clone(pr: "Project", k: int) -> "Project":
    """Copy of pr's work directory for parallel probing (one CPU per fit)."""
    dst = pr.work + f".w{k}"
    if not os.path.isdir(dst):
        shutil.copytree(pr.work, dst)
        p = os.path.join(dst, "fuzz.qsf")
        lines = [ln for ln in open(p) if "NUM_PARALLEL_PROCESSORS" not in ln]
        open(p, "w").writelines(lines + ["set_global_assignment -name NUM_PARALLEL_PROCESSORS 1\n"])
    c = Project.__new__(Project)
    c.work = dst
    c.rbf = lambda: open(c._rbf_path(), "rb").read()
    c.base_rcf, c.base_rbf = pr.base_rcf, pr.base_rbf
    return c


def scan(pr: "Project", probes: list, workers: int = 6, want_bits: bool = False):
    """Run force() for each (signal, old, new) probe on `workers` clones in parallel.
    Returns [(probe, honoured, message, xor cells or None)] in probe order."""
    import concurrent.futures as cf
    clones = [_clone(pr, k) for k in range(workers)]
    chunks = [probes[k::workers] for k in range(workers)]

    def work(k):
        out = []
        for pb in chunks[k]:
            ok, data, msg = clones[k].force(*pb)
            out.append((pb, ok, msg, xor_cells(pr.base_rbf, data) if (want_bits and ok and data) else None))
        return out

    with cf.ThreadPoolExecutor(workers) as ex:
        res = [r for part in ex.map(work, range(workers)) for r in part]
    order = {id(pb): i for i, pb in enumerate(probes)}
    return sorted(res, key=lambda r: order[id(r[0])])
