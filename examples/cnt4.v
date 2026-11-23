// 4-bit counter, counts on D2 rising edges while D1 = 1; D5 = 1 when the count equals K.
module top(input A, B, C, D, output Q);
  localparam [3:0] K = 4'd9;
  reg [3:0] n = 0;
  always @(posedge B) if (A) n <= n + 1;
  assign Q = (n == K);
endmodule
