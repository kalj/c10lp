// 4-bit counter, counts on D2 rising edges while D1 = 1; D5 = n[I] ^ n[J].
// Changing I or J changes which register feeds the output LUT: a wiring edit inside the LAB,
// which v2bit.py write can do without Quartus when the direct-rewire rule allows it.
module top(input A, B, C, D, output Q);
  localparam I = 0, J = 1;
  (* keep *) reg [3:0] n = 0;   // keep: all four bits stay, whichever two feed the output
  always @(posedge B) if (A) n <= n + 1;
  (* keep *) wire x = n[I] ^ n[J];     // keep: the output LUT stays separate from the counter
  assign Q = x;
endmodule
