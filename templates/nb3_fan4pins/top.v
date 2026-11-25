// nb3 probe: X8 slot 18 (le30's place in the Yosys blinky) -> X9 line 23, fanout 4
module fuzz_top(input wire A, B, C, D, input wire K, output wire Q);
  wire t; wire [3:0] uu; wire u0; wire u1; wire u2; wire u3;
  cyclone10lp_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on")) src (.dataa(A), .datab(B), .datac(C), .datad(D), .combout(t));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk0 (.dataa(t), .combout(u0));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk1 (.dataa(t), .combout(u1));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk2 (.dataa(t), .combout(u2));
  cyclone10lp_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on")) snk3 (.dataa(t), .combout(u3));
  assign Q = u0 ^ u1 ^ u2 ^ u3;
endmodule
