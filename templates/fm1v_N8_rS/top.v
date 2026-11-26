// fm1map probe: LE X9Y3 N8; combinational output to nothing, register to S
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire o0;
  wire t; reg s;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) le (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  always @(posedge K) s <= t;
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) k0 (.dataa(s), .combout(o0));
  assign Q = o0;
endmodule
