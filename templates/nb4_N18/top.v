// nb4 probe: dx -1 neighbour link source-side cells (source X15Y10 slot 18, sink in X14Y10)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk (.dataa(t), .combout(u));
  assign Q = u;
endmodule
