// sp probe: second-path output select byte vs source slot and buffer (source LAB X14Y10, sink in X15Y10)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk (.dataa(t), .combout(u));
  assign Q = u;
endmodule
