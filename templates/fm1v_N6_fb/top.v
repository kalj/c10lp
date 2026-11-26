// fm1map probe: LE X9Y3 N6; combinational output to nothing, register to F
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t; reg s;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) le (.dataa(A), .datab(B), .datac(C), .datad(s), .combout(t));
  always @(posedge K) s <= t;
  assign Q = t;
endmodule
