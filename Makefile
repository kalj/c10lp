# Open flow for the blinky: Verilog -> Yosys -> ypnr.py (pack, place, route, assemble) -> out/ypnr_blink.rbf
#   make baseline      the one Quartus step: the all-zero design the assembler starts from (out/lo_quartus_0000.rbf)
#   make blinky        build the bitstream (no Quartus)
#   make blinky-check  also build the same netlist in Quartus with our placement/routing forced, and diff (needs Quartus)
#   make npnr-blinky   the same design placed and routed by nextpnr-himbaechel (c10lp uarch, ../nextpnr built with it)
#                      -> out/ypnr_blink.rbf; blinky-check then cross-checks that file
YOSYS ?= yosys

out/blink.json: examples/blink.v
	$(YOSYS) -q -p "read_verilog $<; synth_intel -family cyclone10lp -nodsp -nobram -top blink; write_json $@"

out/lo_quartus_0000.rbf:
	python3 flow/baseline.py

baseline: out/lo_quartus_0000.rbf

out/ypnr_blink.rbf: out/blink.json out/lo_quartus_0000.rbf flow/ypnr.py flow/ynet.py flow/router.py flow/asm.py lib/switchmodel.py
	python3 flow/ypnr.py $< blink

blinky: out/ypnr_blink.rbf

blinky-check: out/ypnr_blink.rbf
	python3 flow/ycheck.py out/blink.json blink

NEXTPNR ?= ../nextpnr

npnr-blinky: out/blink.json out/lo_quartus_0000.rbf
	nextpnr/build_chipdb.sh $(NEXTPNR)
	python3 nextpnr/c10lp_netlist.py out/blink.json blink out/npnr_blink.json
	# a placement nextpnr can route with the hops we know: retry seeds (each run takes well under a second)
	for s in $$(seq 1 60); do $(NEXTPNR)/build/nextpnr-himbaechel --device 10CL016 --json out/npnr_blink.json \
	    --pre-place nextpnr/region_row.py --seed $$s --write out/npnr_blink_routed.json > out/npnr_blink.log 2>&1 \
	    && echo "nextpnr: routed with seed $$s" && break; done
	python3 nextpnr/npnr2asm.py out/npnr_blink_routed.json out/npnr_blink_side.json blink

.PHONY: baseline blinky blinky-check npnr-blinky
