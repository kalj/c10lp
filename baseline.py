#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the assembler's baseline: Quartus's all-zero design (one LUT, mask 0000, at X10Y10N0, Vidor pin set).

This is the only Quartus step the open flow needs; Quartus bitstreams aren't shipped in the repo.  The result must
match the SHA-256 recorded in corpus.json (Quartus Prime Lite 21.1.1); a different version may give a different
file, and then the tables (derived with 21.1.1) may not fit it.

  baseline.py            writes out/lo_quartus_0000.rbf (about 15 s)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
JOB = xdev.Job("c10_016", "lut:0000", (10, 10, 0), "vidorlo")


def main() -> int:
    want = next(e["sha256"] for e in json.load(open(os.path.join(HERE, "corpus.json")))["builds"] if e["job"] == JOB.name)
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        m = xdev.build_one(JOB, tmp, False)
        if not m.get("ok", True):
            print("Quartus build failed")
            return 1
        src = os.path.join(tmp, JOB.name + ".rbf")
        got = hashlib.sha256(open(src, "rb").read()).hexdigest()
        shutil.copy(src, os.path.join(OUT, "lo_quartus_0000.rbf"))
    if got != want:
        print(f"WARNING: out/lo_quartus_0000.rbf has SHA-256 {got}, not the recorded {want} (another Quartus version?)")
        return 1
    print("out/lo_quartus_0000.rbf: matches the recorded build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
