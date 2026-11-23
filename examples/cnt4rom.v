// 4-bit counter, counts on D2 rising edges while D1 = 1; D5 = TABLE[count].
// Editing TABLE keeps the LUT/flip-flop netlist the same, so v2bit.py write
// can produce the new bitstream without Quartus.
module top(input A, B, C, D, output Q);
  localparam [15:0] TABLE = 16'h8421;
  reg [3:0] n = 0;
  always @(posedge B) if (A) n <= n + 1;
  assign Q = TABLE[n];
endmodule
