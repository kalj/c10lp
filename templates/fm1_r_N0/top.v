// fm1 probe: frame -1 bits vs LAB occupancy and register use (LAB X14Y10)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t0; reg s0;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) l0 (.dataa(A), .datab(B), .datac(C), .datad(s0), .combout(t0));
  always @(posedge K) s0 <= t0;
  assign Q = s0;
endmodule
