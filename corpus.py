#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild the Quartus corpus behind every result in README.md.

corpus.json lists every build in out/ (device, design, LE, pins) with the
SHA-256 of the RBF that Quartus Lite 21.1.1 produced here.  Quartus is
deterministic for these settings, so a rebuild should match byte for byte.

  corpus.py plan   [--only PREFIX] [--jobs 2]   what is missing, time estimate
  corpus.py build  [--only PREFIX] [--jobs 2]   compile what is missing
  corpus.py verify                              SHA-256 of every present RBF vs corpus.json
  corpus.py derived                             regenerate the out/lo_* hardware-test files,
                                                out/sweep/, out/reg/, out/fsm/ (no Quartus) and check them
  corpus.py freeze                              (maintainer) rewrite corpus.json from out/

--only selects jobs whose name starts with PREFIX, e.g. "c10_016__lut0000".
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xdev  # noqa: E402

HERE = xdev.HERE
OUT = os.path.join(HERE, "out")
MANIFEST = os.path.join(HERE, "corpus.json")


def sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_manifest() -> list[dict]:
    with open(MANIFEST) as f:
        return json.load(f)["builds"]


def job_of(e: dict) -> xdev.Job:
    return xdev.Job(e["dev"], e["design"], tuple(e["loc"]), e["pins"])


# Hardware-test files: (name, how it is made).  "copy" = a Quartus build as is.
DERIVED = [
    ("lo_quartus_8888.rbf", ("copy", "c10_016__lut8888_X10Y10N0__vidorlo")),
    ("lo_quartus_0000.rbf", ("copy", "c10_016__lut0000_X10Y10N0__vidorlo")),
    ("lo_x8888.rbf", ("lut", (10, 10, 0), 0x8888, False)),
    ("lo_x8888_hdr.rbf", ("lut", (10, 10, 0), 0x8888, True)),
    ("lo_x8888_X30Y20N12.rbf", ("lut", (30, 20, 12), 0x8888, False)),
    ("lo_tree_atleast2.rbf", ("tree", [0x8888, 0xF000, 0x6666, 0x0FF0, 0xFEEE])),
    ("lo_tree_parity.rbf", ("tree", [0x6666, 0x0FF0, 0x0000, 0x0000, 0x6666])),
]


def make_derived(name: str, how) -> bytes:
    import lutpatch
    import multipatch
    if how[0] == "copy":
        with open(os.path.join(OUT, how[1] + ".rbf"), "rb") as f:
            return f.read()
    if how[0] == "lut":
        _, loc, mask, hdr = how
        return lutpatch.Codec(OUT, "c10_016", loc, model=True, pins="vidorlo").write(mask, hdr)
    return multipatch.Multi(OUT, xdev.TREE_LOCS, "vidorlo").write(how[1], True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "build", "verify", "derived", "freeze"])
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()

    if a.cmd == "freeze":
        builds = []
        for mp in sorted(glob.glob(os.path.join(OUT, "*__*.json"))):
            m = json.load(open(mp))
            rbf = mp[:-5] + ".rbf"
            if m.get("ok") and os.path.exists(rbf):
                builds.append(dict(job=m["job"], dev=m["dev"], design=m["design"],
                                   loc=m["loc"], pins=m["pins"], sha256=sha(rbf)))
        derived = {n: sha(os.path.join(OUT, n)) for n, _ in DERIVED
                   if os.path.exists(os.path.join(OUT, n))}
        with open(MANIFEST, "w") as f:
            json.dump({"quartus": "Quartus Prime Lite 21.1.1 Build 850", "builds": builds,
                       "derived": derived}, f, indent=0)
        print(f"wrote {MANIFEST}: {len(builds)} builds, {len(derived)} derived files")
        return 0

    entries = [e for e in load_manifest() if e["job"].startswith(a.only)]
    jobs = [job_of(e) for e in entries]

    if a.cmd == "plan":
        print(xdev.estimate(jobs, OUT, a.jobs))
        return 0

    if a.cmd == "build":
        print(xdev.estimate(jobs, OUT, a.jobs), flush=True)
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            res = list(ex.map(lambda j: xdev.build_one(j, OUT, False), jobs))
        bad = [m["job"] for m in res if not m["ok"]]
        print(f"{sum(not m.get('cached') for m in res)} compiled, {len(bad)} failed {bad[:5]}")
        return 1 if bad else 0

    if a.cmd == "verify":
        same = diff = missing = 0
        for e in entries:
            p = os.path.join(OUT, e["job"] + ".rbf")
            if not os.path.exists(p):
                missing += 1
            elif sha(p) == e["sha256"]:
                same += 1
            else:
                diff += 1
                print(f"  DIFFERS: {e['job']}")
        print(f"{same} identical, {diff} differ, {missing} not built")
        return 1 if diff else 0

    # derived
    with open(MANIFEST) as f:
        want = json.load(f)["derived"]
    bad = 0
    for name, how in DERIVED:
        try:
            data = make_derived(name, how)
        except (SystemExit, FileNotFoundError, TypeError) as e:
            print(f"  {name}: needs more builds ({e})")
            bad += 1
            continue
        h = hashlib.sha256(data).hexdigest()
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(data)
        ok = h == want.get(name)
        bad += not ok
        print(f"  {name}: {'matches corpus.json' if ok else 'DIFFERS from corpus.json'}")
    rc = 0
    for script in ("silicon_sweep.py", "regtest.py", "fsmtest.py"):
        rc |= subprocess.run([sys.executable, os.path.join(HERE, script), "write"]).returncode
    return 1 if bad or rc else 0


if __name__ == "__main__":
    sys.exit(main())
