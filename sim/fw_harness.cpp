// Runs the board's real firmware code on a PC: the ADS131M08 driver
// (firmware/squid16/src/ads131m08.cpp) and the packet/channel-order code
// (protocol.h) talk to two simulated converters. main.cpp itself (interrupts,
// Bluetooth, FreeRTOS) is NOT run here.
//
//   stdin:  int32 little-endian samples, 16 per time step:
//           converter on PIN_CS_A inputs AIN0..7, then converter on PIN_CS_B AIN0..7
//   stdout: one 51-byte packet per time step
//   argv[1]: PGA gain code the firmware should configure (default 2 = gain 4)
// The simulated converter follows the frame rules of the TI datasheet as I
// read them: 24-bit words, response to a command in the next frame.
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "../firmware/squid16/src/ads131m08.h"
#include "../firmware/squid16/src/protocol.h"

struct SimAdc {
  uint16_t reg[64];
  uint16_t next = 0;
  bool have = false;
  int32_t sample[8] = {0};
  SimAdc() { memset(reg, 0, sizeof(reg)); reg[0] = 0x2812; reg[1] = 0x0500; reg[2] = 0x0510; reg[3] = 0xFF0E; }
  void exchange(const uint8_t *tx, uint8_t *rx, size_t len) {
    if (len != ads131::kFrameBytes) { fprintf(stderr, "short frame\n"); exit(2); }
    uint16_t resp = have ? next : reg[1];
    have = false;
    memset(rx, 0, len);
    rx[0] = resp >> 8; rx[1] = resp & 0xFF;
    for (int ch = 0; ch < 8; ch++) {
      uint32_t v = uint32_t(sample[ch]) & 0xFFFFFF;
      rx[3 + ch * 3] = v >> 16; rx[4 + ch * 3] = v >> 8; rx[5 + ch * 3] = v;
    }
    uint16_t cmd = (uint16_t(tx[0]) << 8) | tx[1];
    if ((cmd & 0xE000) == 0xA000) { next = reg[(cmd >> 7) & 0x3F]; have = true; }
    else if ((cmd & 0xE000) == 0x6000) {
      reg[(cmd >> 7) & 0x3F] = (uint16_t(tx[3]) << 8) | tx[4];
      next = 0x4000 | (cmd & 0x1FFF); have = true;
    }
  }
};

static void xfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t len) {
  static_cast<SimAdc *>(ctx)->exchange(tx, rx, len);
}

int main(int argc, char **argv) {
  uint8_t gain_code = argc > 1 ? uint8_t(atoi(argv[1])) : 2;
  SimAdc simA, simB;
  ads131::Device a(xfer, &simA), b(xfer, &simB);
  // same calls, in the same order, as startConverters() in main.cpp
  if ((a.read_reg(ads131::REG_ID) >> 8) != 0x28 || (b.read_reg(ads131::REG_ID) >> 8) != 0x28) return 3;
  if (!a.configure(gain_code, ads131::kOsrMax, 5) || !b.configure(gain_code, ads131::kOsrMax, 5)) return 4;
  fprintf(stderr, "configured: CLOCK=0x%04X GAIN1=0x%04X GAIN2=0x%04X DCBLOCK=0x%04X\n",
          simA.reg[3], simA.reg[4], simA.reg[5], simA.reg[8]);
  int32_t in[16], ra[8], rb[8], ch[squid::kChannels];
  uint8_t pkt[squid::kPacketBytes];
  uint8_t counter = 0;
  while (fread(in, sizeof(int32_t), 16, stdin) == 16) {
    memcpy(simA.sample, in, sizeof(simA.sample));
    memcpy(simB.sample, in + 8, sizeof(simB.sample));
    a.read_samples(ra);
    b.read_samples(rb);
    squid::order_channels(ra, rb, ch);
    squid::build_packet(counter++, ch, pkt);
    fwrite(pkt, 1, sizeof(pkt), stdout);
  }
  return 0;
}
