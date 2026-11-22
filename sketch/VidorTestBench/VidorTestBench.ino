// SPDX-License-Identifier: GPL-3.0-or-later
// USB-Blaster plus a tiny serial test bench for c10lp/hwtest.py --auto.
//
// The SAMD21 shares the MKR header pins with the FPGA.  This sketch only ever
// drives D1..D4, and only after the host has loaded a test bitstream (in which
// D1..D4 are FPGA inputs) and sent "A".  D5 is never driven: it is read only.
//
// Commands (one per line, 115200 baud, replies end with "\n"):
//   A        arm: D1..D4 become outputs (driven low/high by S)   -> "ok"
//   I        disarm: D1..D4 back to inputs                        -> "ok"
//   S dddd   set D1..D4, e.g. "S 1011" = D1=1 D2=0 D3=1 D4=1     -> "ok" | "err"
//   R        read D5 (and D1..D4 as seen on the pins)             -> "D5=1 D1..4=1011"
//   ?        identify                                             -> "vidor-testbench 1"
#include "Blaster.h"

extern void enableFpgaClock();

static const int IN_PINS[4] = {1, 2, 3, 4};
static const int OUT_PIN = 5;
static bool armed = false;
static char line[32];
static int len = 0;

static void disarm() {
  for (int i = 0; i < 4; i++) pinMode(IN_PINS[i], INPUT);
  armed = false;
}

static void handle(const char *c) {
  if (c[0] == '?') {
    Serial.println("vidor-testbench 1");
  } else if (c[0] == 'I') {
    disarm();
    Serial.println("ok");
  } else if (c[0] == 'A') {
    // Set the level before switching to output so no unintended glitch is driven.
    for (int i = 0; i < 4; i++) {
      digitalWrite(IN_PINS[i], HIGH);
      pinMode(IN_PINS[i], OUTPUT);
    }
    armed = true;
    Serial.println("ok");
  } else if (c[0] == 'S' && armed && strlen(c) >= 6) {
    for (int i = 0; i < 4; i++) {
      char b = c[2 + i];
      if (b != '0' && b != '1') { Serial.println("err"); return; }
    }
    for (int i = 0; i < 4; i++) digitalWrite(IN_PINS[i], c[2 + i] == '1' ? HIGH : LOW);
    Serial.println("ok");
  } else if (c[0] == 'R') {
    delayMicroseconds(200);
    Serial.print("D5=");
    Serial.print(digitalRead(OUT_PIN));
    Serial.print(" D1..4=");
    for (int i = 0; i < 4; i++) Serial.print(digitalRead(IN_PINS[i]));
    Serial.println();
  } else {
    Serial.println("err");
  }
}

void setup() {
  disarm();
  pinMode(OUT_PIN, INPUT);
  Serial.begin(115200);
  USBBlaster.begin(true);
  // Also start the 48 MHz clock feed for the FPGA, as in the library example.
  enableFpgaClock();
}

void loop() {
  USBBlaster.loop();
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (len) {
        line[len] = 0;
        handle(line);
        len = 0;
      }
    } else if (len < (int)sizeof(line) - 1) {
      line[len++] = ch;
    }
  }
}
