// fm1 probe: frame -1 bits vs LAB occupancy and register use (LAB X14Y10)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t2; reg s2;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) l2 (.dataa(A), .datab(B), .datac(C), .datad(s2), .combout(t2));
  always @(posedge K) s2 <= t2;
  assign Q = s2;
endmodule
