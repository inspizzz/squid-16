// SPDX-License-Identifier: MIT
#include "ads131m08.h"

#include <string.h>

namespace ads131 {

uint16_t Device::frame(uint16_t command, int32_t *samples, const uint16_t *data, size_t ndata) {
  uint8_t tx[kFrameBytes] = {0};
  uint8_t rx[kFrameBytes] = {0};
  tx[0] = uint8_t(command >> 8);
  tx[1] = uint8_t(command);
  for (size_t i = 0; i < ndata && i + 1 < kFrameWords; i++) {
    tx[(i + 1) * kWordBytes] = uint8_t(data[i] >> 8);
    tx[(i + 1) * kWordBytes + 1] = uint8_t(data[i]);
  }
  // The chip only treats a frame as read when every word has been clocked out,
  // so a full ten-word frame is always exchanged.
  xfer_(ctx_, tx, rx, kFrameBytes);
  if (samples) {
    for (int ch = 0; ch < kChannels; ch++) {
      const uint8_t *p = rx + (ch + 1) * kWordBytes;
      samples[ch] = sign_extend24((uint32_t(p[0]) << 16) | (uint32_t(p[1]) << 8) | p[2]);
    }
  }
  return uint16_t((uint16_t(rx[0]) << 8) | rx[1]);
}

bool Device::reset() {
  frame(kCmdReset);
  // The acknowledgement arrives as the response word of the next frame.
  return frame(kCmdNull) == kResetAck;
}

uint16_t Device::read_reg(uint8_t addr) {
  frame(cmd_rreg(addr));
  return frame(kCmdNull);
}

void Device::write_reg(uint8_t addr, uint16_t value) {
  frame(cmd_wreg(addr), nullptr, &value, 1);
}

bool Device::write_reg_verified(uint8_t addr, uint16_t value) {
  write_reg(addr, value);
  return read_reg(addr) == value;
}

bool Device::set_gain_code(uint8_t code) {
  return write_reg_verified(REG_GAIN1, gain_reg(code)) &&
         write_reg_verified(REG_GAIN2, gain_reg(code));
}

bool Device::configure(uint8_t gain_code, uint8_t osr_code, uint8_t dcblock) {
  bool ok = write_reg_verified(REG_CLOCK, clock_reg(osr_code));
  ok = set_gain_code(gain_code) && ok;
  ok = write_reg_verified(REG_THRSHLD_LSB, dcblock & 0x0F) && ok;
  return ok;
}

}  // namespace ads131
