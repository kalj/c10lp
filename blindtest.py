#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blind silicon test of lirule.py: predictions are written (and committed) before any load.

  blindtest.py plan     build new mux4 bases, list candidates (table entries, lone-source pairs
                        only), write out/blind_predictions.json
  blindtest.py board    run rewire.py on each base and score against the saved predictions
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lirule  # noqa: E402
import rewire as R  # noqa: E402
import xdev  # noqa: E402

PRED = os.path.join(HERE, "blind_predictions.json")
# --where: other LABs / dst slots (second blind test); default = X10Y10 dst 16 (first blind test)
WHERE = [((30, 20), 6), ((3, 25), 24), ((37, 5), 30)]
USED = {"0-4-8-12", "2-10-18-24", "0-6-20-28", "10-12-22-26", "2-6-18-30", "12-14-20-28", "0-10-18-24"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "board"])
    ap.add_argument("--bases", type=int, default=6)
    ap.add_argument("--where", action="store_true", help="second blind test: other LABs and dst slots")
    a = ap.parse_args()
    global PRED
    if a.where:
        PRED = os.path.join(HERE, "blind_predictions_2.json")
    if a.cmd == "plan":
        r = random.Random(20261123 + a.where)
        bases = []                                       # (loc, dst, source set)
        places = WHERE if a.where else [((10, 10), 16)]
        while len(bases) < a.bases:
            loc, d = places[len(bases) % len(places)]
            st = "-".join(map(str, sorted(r.sample([s for s in range(0, 32, 2) if s != d], 4))))
            if (a.where or st not in USED) and (loc, d, st) not in bases:
                bases.append((loc, d, st))
        jobs = [xdev.Job("c10_016", f"mux4:{d}:{st}", loc + (0,), "vidorlo") for loc, d, st in bases]
        with cf.ThreadPoolExecutor(6) as ex:
            list(ex.map(lambda j: xdev.build_one(j, R.OUT, False), jobs))
        direct = lirule.load_direct()
        lone = {tuple(p) for p in json.load(open(os.path.join(HERE, "li_lone_pairs.json")))}
        preds = {}
        for loc, d, st in bases:
            R.SRCS, R.LOC, R.D = [int(v) for v in st.split("-")], loc + (0,), d
            base = xdev.load(R.OUT, R.base_name())
            dst = R.Dst(base)
            cur = {dst.perm[i]: R.SRCS[i] for i in range(4)}
            match = dst.region(base) == R.predict(cur)
            print(f"  base X{loc[0]}Y{loc[1]} dst {d} srcs {st}: input order {dst.perm}, low byte {dst.lo}, "
                  f"select region == table prediction: {match}")
            if not match or dst.lo < 6:
                print("    skipped (region mismatch or too close to a byte wrap)")
                continue
            key0 = f"X{loc[0]}Y{loc[1]}N{d}_{st}" if a.where else st
            for i in range(4):
                p = dst.perm[i]
                for s in R.SRCS:
                    if s != cur[p] and (p, s) in lone and (p, s) in R.ENTRIES and (p, cur[p]) in R.ENTRIES:
                        preds[f"{key0}:rewire_in{p}_to_src{s}"] = lirule.predict(direct, cur, {p: s})
        json.dump(preds, open(PRED, "w"), indent=1)
        n = sum(preds.values())
        print(f"{len(bases)} new bases; {len(preds)} candidates: {n} predicted to work, "
              f"{len(preds) - n} predicted to fail -> {PRED}")
        return 0

    preds = json.load(open(PRED))
    bases = sorted({k.split(":")[0] for k in preds})
    for st in bases:
        args = ["--srcs", st]
        if st.startswith("X"):
            xy, n_st = st.split("N", 1)
            nd, srcs = n_st.split("_")
            x, y = xy[1:].split("Y")
            args = ["--srcs", srcs, "--loc", f"{x},{y}", "--dst", nd]
        rc = subprocess.run([sys.executable, os.path.join(HERE, "rewire.py"), "board", "--lone"] + args)
        if rc.returncode not in (0, 1):
            print("STOP: rewire.py stopped (see above)")
            return 1
    hit = n = 0
    for st in bases:
        log = sorted(glob.glob(os.path.join(R.OUT, f"rewire_{st}_*.jsonl")))[-1]
        for line in open(log):
            r = json.loads(line)
            key = f"{st}:{r['file']}"
            if key in preds:
                n += 1
                ok = preds[key] == (not r["wrong"])
                hit += ok
                if not ok:
                    print(f"  MISPREDICTED {key}: predicted {'work' if preds[key] else 'fail'}")
    print(f"\nblind test: rule predicted {hit}/{n} outcomes correctly")
    return 0 if hit == n else 1


if __name__ == "__main__":
    sys.exit(main())
