// nb3 probe: X8 slot 18 (le30's place in the Yosys blinky) -> X9 line 23, fanout 1
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t; wire [0:0] uu; wire u0;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(1'b1), .datad(1'b1), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk0 (.dataa(t), .combout(u0));
  assign Q = u0;
endmodule
