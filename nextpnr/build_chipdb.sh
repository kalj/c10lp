#!/bin/sh
# Regenerate the c10lp chip database from the current models and install it for nextpnr-himbaechel.
# usage: nextpnr/build_chipdb.sh [NEXTPNR_DIR]      (default ../nextpnr, built in NEXTPNR_DIR/build)
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
NPNR=${1:-$HERE/../nextpnr}
python3 "$HERE/nextpnr/c10lp_arch_gen.py" "$NPNR" "$HERE/out/chipdb-10CL016.bba"
mkdir -p "$NPNR/build/share/himbaechel/c10lp"
"$NPNR/build/bba/bbasm" --l "$HERE/out/chipdb-10CL016.bba" "$NPNR/build/share/himbaechel/c10lp/chipdb-10CL016.bin"
