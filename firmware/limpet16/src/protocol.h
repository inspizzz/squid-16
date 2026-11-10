// Limpet-16 wire format and channel mapping. Pure C++, shared with the PC test.
// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace limpet {

constexpr int kChannels = 16;
// Data packet, one per sample (same layout as the PiEEG "Octopus 16" stream,
// so existing viewers that speak that format can read it):
//   0xA0, counter, 16 x 24-bit big-endian two's complement, 0xC0
constexpr size_t kPacketBytes = 2 + kChannels * 3 + 1;
constexpr uint8_t kPacketStart = 0xA0;
constexpr uint8_t kPacketEnd = 0xC0;

// Board revision B. ADC B is mounted turned by 180 degrees, so its inputs run
// the other way round the board:
//   channel n (1..8)  = ADC A input AIN(n - 1)
//   channel n (9..16) = ADC B input AIN(16 - n)
inline void order_channels(const int32_t adc_a[8], const int32_t adc_b[8], int32_t out[kChannels]) {
  for (int n = 1; n <= 8; n++) out[n - 1] = adc_a[n - 1];
  for (int n = 9; n <= 16; n++) out[n - 1] = adc_b[16 - n];
}

inline void build_packet(uint8_t counter, const int32_t ch[kChannels], uint8_t out[kPacketBytes]) {
  out[0] = kPacketStart;
  out[1] = counter;
  for (int i = 0; i < kChannels; i++) {
    uint32_t v = uint32_t(ch[i]) & 0xFFFFFF;
    out[2 + i * 3] = uint8_t(v >> 16);
    out[3 + i * 3] = uint8_t(v >> 8);
    out[4 + i * 3] = uint8_t(v);
  }
  out[kPacketBytes - 1] = kPacketEnd;
}

// Microvolts per count for a PGA gain (1, 2, 4 ... 128); full scale is +-1.2 V / gain.
inline double microvolts_per_count(int gain) { return 1.2 / gain / 8388608.0 * 1e6; }

}  // namespace limpet
