// PC-side test of the driver and packet code against a simulated ADS131M08.
// The simulator follows the frame rules in the TI datasheet: the response to a
// command appears in the NEXT frame, registers are 16 bits MSB-aligned in
// 24-bit words, conversion data are 24-bit two's complement.
//   ./run.sh
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstdio>
#include <cstring>

#include "../limpet16/src/ads131m08.h"
#include "../limpet16/src/protocol.h"

struct SimAdc {
  uint16_t reg[64] = {0};
  uint16_t next_response = 0;
  bool have_response = false;
  int32_t sample[8] = {0};
  int frames = 0;
  SimAdc() { power_on(); }
  void power_on() {
    memset(reg, 0, sizeof(reg));
    reg[0x00] = 0x2812; reg[0x01] = 0x0500; reg[0x02] = 0x0510; reg[0x03] = 0xFF0E;
  }
  void exchange(const uint8_t *tx, uint8_t *rx, size_t len) {
    assert(len == ads131::kFrameBytes);            // driver must always send whole frames
    frames++;
    uint16_t resp = have_response ? next_response : reg[0x01];
    have_response = false;
    memset(rx, 0, len);
    rx[0] = resp >> 8; rx[1] = resp & 0xFF;
    for (int ch = 0; ch < 8; ch++) {
      uint32_t v = uint32_t(sample[ch]) & 0xFFFFFF;
      rx[3 + ch * 3] = v >> 16; rx[4 + ch * 3] = v >> 8; rx[5 + ch * 3] = v;
    }
    uint16_t cmd = (uint16_t(tx[0]) << 8) | tx[1];
    assert(tx[2] == 0);                            // 16-bit command, zero padded
    if (cmd == 0x0011) { power_on(); next_response = 0xFF28; have_response = true; }
    else if ((cmd & 0xE000) == 0xA000) {           // RREG, single register
      assert((cmd & 0x7F) == 0);
      next_response = reg[(cmd >> 7) & 0x3F]; have_response = true;
    } else if ((cmd & 0xE000) == 0x6000) {         // WREG, single register
      assert((cmd & 0x7F) == 0);
      uint8_t a = (cmd >> 7) & 0x3F;
      assert(a >= 2);                              // ID and STATUS are read-only
      reg[a] = (uint16_t(tx[3]) << 8) | tx[4];
      next_response = 0x4000 | (cmd & 0x1FFF); have_response = true;
    } else assert(cmd == 0);
  }
};

static void xfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t len) {
  static_cast<SimAdc *>(ctx)->exchange(tx, rx, len);
}

#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main() {
  SimAdc simA, simB;
  ads131::Device a(xfer, &simA), b(xfer, &simB);

  // command encodings, straight from Table 8-11
  CHECK(ads131::cmd_rreg(0x00) == 0xA000);
  CHECK(ads131::cmd_rreg(0x03) == 0xA180);
  CHECK(ads131::cmd_wreg(0x04) == 0x6200);
  CHECK(ads131::clock_reg(7) == 0xFF9E);           // all channels, XTAL off, OSR 16256, HR
  CHECK(ads131::gain_reg(2) == 0x2222);
  CHECK(ads131::sign_extend24(0xFFFFFF) == -1);
  CHECK(ads131::sign_extend24(0x800000) == -8388608);
  CHECK(ads131::sign_extend24(0x7FFFFF) == 8388607);

  CHECK((a.read_reg(ads131::REG_ID) >> 8) == 0x28);
  CHECK(a.reset());
  CHECK(a.configure(2, ads131::kOsr16256, 5));
  CHECK(b.configure(2, ads131::kOsr16256, 5));
  CHECK(simA.reg[0x03] == 0xFF9E && simA.reg[0x04] == 0x2222 && simA.reg[0x05] == 0x2222);
  CHECK(simA.reg[0x08] == 0x0005);
  CHECK(a.write_reg_verified(ads131::REG_GAIN1, 0x2222));

  // conversion data and channel ordering: mark each input with its own value
  for (int k = 0; k < 8; k++) { simA.sample[k] = -(100 + k); simB.sample[k] = 200 + k; }
  int32_t ra[8], rb[8], ch[16];
  CHECK(a.read_samples(ra) == 0x0500);
  b.read_samples(rb);
  for (int k = 0; k < 8; k++) CHECK(ra[k] == -(100 + k) && rb[k] == 200 + k);
  limpet::order_channels(ra, rb, ch);
  CHECK(ch[0] == -100);    // channel 1  = ADC A AIN0
  CHECK(ch[7] == -107);    // channel 8  = ADC A AIN7
  CHECK(ch[8] == 207);     // channel 9  = ADC B AIN7
  CHECK(ch[15] == 200);    // channel 16 = ADC B AIN0

  uint8_t pkt[limpet::kPacketBytes];
  limpet::build_packet(0x42, ch, pkt);
  CHECK(sizeof(pkt) == 51 && pkt[0] == 0xA0 && pkt[1] == 0x42 && pkt[50] == 0xC0);
  CHECK(pkt[2] == 0xFF && pkt[3] == 0xFF && pkt[4] == 0x9C);          // -100
  CHECK(pkt[47] == 0x00 && pkt[48] == 0x00 && pkt[49] == 200);
  double uv = limpet::microvolts_per_count(4);
  CHECK(uv > 0.03576 && uv < 0.03577);
  CHECK(ads131::kSampleRateHz > 251.9 && ads131::kSampleRateHz < 252.0);
  printf("all firmware host tests passed (%d + %d simulated frames)\n", simA.frames, simB.frames);
  return 0;
}
