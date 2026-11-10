// Minimal ADS131M08 driver, written from the TI datasheet (SBAS950B).
// Hardware independent: it talks through one function that exchanges bytes
// with the chip while its chip-select is low, so it can be unit-tested on a PC.
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace ads131 {

// 24-bit words: 1 command/status word, 8 channel words, 1 CRC word.
constexpr size_t kWordBytes = 3;
constexpr size_t kFrameWords = 10;
constexpr size_t kFrameBytes = kWordBytes * kFrameWords;
constexpr int kChannels = 8;

enum Reg : uint8_t {
  REG_ID = 0x00, REG_STATUS = 0x01, REG_MODE = 0x02, REG_CLOCK = 0x03,
  REG_GAIN1 = 0x04, REG_GAIN2 = 0x05, REG_CFG = 0x06, REG_THRSHLD_LSB = 0x08,
};

constexpr uint16_t kCmdNull = 0x0000;
constexpr uint16_t kCmdReset = 0x0011;
constexpr uint16_t kResetAck = 0xFF28;

// CLOCK register: all eight channels on, external clock (crystal driver off),
// internal reference, high-resolution mode.
constexpr uint16_t kClockBase = 0xFF00 | 0x0080 | 0x0002;
// OSR code 7 = 16256. With the 8.192 MHz clock: 4 096 000 / 16256 = 251.97 SPS.
constexpr uint8_t kOsr16256 = 7;
constexpr double kSampleRateHz = 8192000.0 / 2.0 / 16256.0;

inline uint16_t cmd_rreg(uint8_t addr, uint8_t count = 1) {
  return 0xA000 | (uint16_t(addr & 0x3F) << 7) | ((count - 1) & 0x7F);
}
inline uint16_t cmd_wreg(uint8_t addr, uint8_t count = 1) {
  return 0x6000 | (uint16_t(addr & 0x3F) << 7) | ((count - 1) & 0x7F);
}
inline uint16_t clock_reg(uint8_t osr_code) { return kClockBase | (uint16_t(osr_code & 7) << 2); }
// Same PGA gain code (0..7 = gain 1,2,4,...,128) on all four channels of a GAIN register.
inline uint16_t gain_reg(uint8_t code) {
  code &= 7;
  return uint16_t(code) | (uint16_t(code) << 4) | (uint16_t(code) << 8) | (uint16_t(code) << 12);
}
inline int32_t sign_extend24(uint32_t v) {
  return (v & 0x800000) ? int32_t(v | 0xFF000000u) : int32_t(v);
}

// Exchange `len` bytes with one chip (CS low for the whole call, SPI mode 1).
using Transfer = void (*)(void *ctx, const uint8_t *tx, uint8_t *rx, size_t len);

class Device {
 public:
  Device(Transfer xfer, void *ctx) : xfer_(xfer), ctx_(ctx) {}

  // One full frame: send a command (plus optional register data words),
  // receive status-or-response and the eight conversion results.
  // Returns the 16-bit response word.
  uint16_t frame(uint16_t command, int32_t *samples = nullptr,
                 const uint16_t *data = nullptr, size_t ndata = 0);

  bool reset();                                   // software reset, true if acknowledged
  uint16_t read_reg(uint8_t addr);
  void write_reg(uint8_t addr, uint16_t value);
  bool write_reg_verified(uint8_t addr, uint16_t value);
  bool set_gain_code(uint8_t code);               // all eight channels
  bool configure(uint8_t gain_code, uint8_t osr_code, uint8_t dcblock);
  // Read the latest conversion (call after DRDY falls). Returns the STATUS word.
  uint16_t read_samples(int32_t samples[kChannels]) { return frame(kCmdNull, samples); }

 private:
  Transfer xfer_;
  void *ctx_;
};

}  // namespace ads131
