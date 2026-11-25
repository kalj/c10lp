// nbsel probe: neighbour link LE_BUFFER X10 I19 -> a line of LAB X11 (destination selects per column class)
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk (.dataa(t), .combout(u));
  assign Q = u;
endmodule
