// nb2 probe: neighbour link from LAB X16 slot 18 (fed by its own register, no input pins) to a sink in LAB X17, row 3
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t, u; reg s;
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(s), .combout(t));
  always @(posedge K) s <= t;
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk (.dataa(t), .combout(u));
  assign Q = u;
endmodule
