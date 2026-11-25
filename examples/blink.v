module blink(input wire K, output wire Q);
  reg [23:0] c = 0;
  always @(posedge K) c <= c + 1;
  assign Q = c[23];
endmodule
