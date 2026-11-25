# Open flow for the blinky: Verilog -> Yosys -> ypnr.py (pack, place, route, assemble) -> out/ypnr_blink.rbf
#   make baseline      the one Quartus step: the all-zero design the assembler starts from (out/lo_quartus_0000.rbf)
#   make blinky        build the bitstream (no Quartus)
#   make blinky-check  also build the same netlist in Quartus with our placement/routing forced, and diff (needs Quartus)
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

.PHONY: baseline blinky blinky-check
