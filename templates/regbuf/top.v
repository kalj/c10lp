// regbuf probe: a registered LE at an odd slot (X9Y3 N6) whose register output feeds LEs in the LABs on both sides,
// to see the frame -1 "register" occupancy cell when one or both of the LE's buffers carry the register
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u, w; reg s;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(s), .combout(t));
  always @(posedge K) s <= t;
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snkl (.dataa(s), .combout(u));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snkr (.dataa(s), .combout(w));
  assign Q = u ^ w;
endmodule
