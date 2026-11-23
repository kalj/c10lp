// D5 = exactly two of D1..D4 high
module top(input A, B, C, D, output Q);
  assign Q = (A + B + C + D) == 2;
endmodule
