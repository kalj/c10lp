# nextpnr Himbächel uarch for the 10CL016

The chip database comes from c10lp's validated models only (`c10lp_arch_gen.py`), so nextpnr can only produce
routes our assembler can write. `npnr2asm.py` turns nextpnr's result into our route description and runs `asm.py`.

## Setup (once)

```bash
git clone https://github.com/YosysHQ/nextpnr.git ../nextpnr          # next to c10lp
ln -s "$PWD/nextpnr/uarch" ../nextpnr/himbaechel/uarch/c10lp
# add c10lp to the uarch list in ../nextpnr/himbaechel/CMakeLists.txt:
#   set(HIMBAECHEL_UARCHES example gowin xilinx ng-ultra gatemate c10lp)
cmake -S ../nextpnr -B ../nextpnr/build -DARCH=himbaechel -DHIMBAECHEL_UARCH=c10lp -DCMAKE_BUILD_TYPE=Release
ninja -C ../nextpnr/build nextpnr-himbaechel bbasm
```

## Use

```bash
make baseline            # once (one Quartus compile of the empty design)
make npnr-blinky         # chip database -> netlist -> nextpnr -> npnr2asm.py -> out/ypnr_blink.rbf
python3 flow/ycheck.py out/blink.json blink --fresh --timing    # Quartus with nextpnr's placement and routing forced
```

## Limits today

- No vertical routing in the database (C4 wires not modelled): `region_row.py` keeps every cell in one row, X1-X12
  (also the LAB-clock region the clock model covers).
- The clock (a GCLK_DRV cell) and the output pin path stay outside nextpnr, as in `flow/ypnr.py`; the LE driving the
  output is pinned to the one LE with a measured path to D5 (X10Y3 N30).
- nextpnr doesn't know which placements our hops can route, so the Makefile retries placement seeds until one routes.
- Timing in the database is nominal; check designs with Quartus's analysis (`ycheck.py --timing`).
