// fm1 probe: frame -1 bits vs LAB occupancy and register use (LAB X14Y10)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t8; reg s8;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) l8 (.dataa(A), .datab(B), .datac(C), .datad(s8), .combout(t8));
  always @(posedge K) s8 <= t8;
  assign Q = s8;
endmodule
