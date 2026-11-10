// Limpet-16 firmware: two ADS131M08 converters -> Bluetooth LE notifications.
// Board: Limpet-16 revision B (ESP32-C3-WROOM-02 module soldered on).
// SPDX-License-Identifier: MIT
//
// STATUS: written against the datasheets and unit-tested on a PC with a
// simulated converter (firmware/test). It has not yet run on real hardware.
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <SPI.h>

#include "ads131m08.h"
#include "protocol.h"

// ---- wiring (see docs/DESIGN.md) -------------------------------------------
// GPIO numbers of the ESP32-C3. GPIO2, 8 and 9 are boot-mode pins and GPIO18/19
// are USB; none of them is used for the converters.
static const int PIN_DRDY = 4;     // data ready from ADC A (both run in step)
static const int PIN_RESET = 5;    // SYNC/RESET of both converters
static const int PIN_CS_B = 6;     // ADC B, channels 9-16
static const int PIN_CS_A = 7;     // ADC A, channels 1-8
static const int PIN_SCLK = 10;
static const int PIN_MISO = 20;
static const int PIN_MOSI = 21;
static const int PIN_LED = 3;      // status LED, on when high

// ---- settings ---------------------------------------------------------------
static const uint8_t DEFAULT_GAIN_CODE = 2;   // gain 4: +-300 mV, 0.0358 uV per count
static const uint8_t DCBLOCK = 5;             // built-in high-pass, about 0.6 Hz at 252 SPS
static const uint32_t SPI_HZ = 4000000;

// Same service / data characteristic UUIDs as the PiEEG Octopus 16 stream so
// viewers written for it can find this board. The command characteristic is
// Limpet-specific and deliberately uses a different UUID.
static const char *SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b";
static const char *DATA_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8";
static const char *COMMAND_UUID = "6c696d70-6574-4c31-9601-000000000001";

static SPISettings spiSettings(SPI_HZ, MSBFIRST, SPI_MODE1);

static void transfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t len) {
  int cs = (int)(intptr_t)ctx;
  SPI.beginTransaction(spiSettings);
  digitalWrite(cs, LOW);
  SPI.transferBytes(tx, rx, len);
  digitalWrite(cs, HIGH);
  SPI.endTransaction();
}

static ads131::Device adcA(transfer, (void *)(intptr_t)PIN_CS_A);
static ads131::Device adcB(transfer, (void *)(intptr_t)PIN_CS_B);

static NimBLECharacteristic *dataChar = nullptr;
static NimBLECharacteristic *cmdChar = nullptr;
static volatile bool connected = false;
static volatile bool adcOk = false;
static TaskHandle_t adcTask = nullptr;
static QueueHandle_t packetQueue = nullptr;
static SemaphoreHandle_t spiLock = nullptr;

struct Packet { uint8_t bytes[limpet::kPacketBytes]; };

static void IRAM_ATTR onDrdy() {
  BaseType_t woken = pdFALSE;
  if (adcTask) vTaskNotifyGiveFromISR(adcTask, &woken);
  if (woken) portYIELD_FROM_ISR();
}

// A short low pulse (well under the 2048 clock periods that mean "reset")
// lines up the conversion timing of the two converters.
// It also empties the converters' two-sample output buffers, which the
// datasheet requires before the first read and after any pause in reading
// (otherwise DRDY stays low and no further edges arrive).
// Interrupts are off for these few microseconds so that a task switch cannot
// stretch the pulse into a reset, which would silently undo the configuration.
static portMUX_TYPE syncMux = portMUX_INITIALIZER_UNLOCKED;
static void syncPulse() {
  portENTER_CRITICAL(&syncMux);
  digitalWrite(PIN_RESET, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_RESET, HIGH);
  portEXIT_CRITICAL(&syncMux);
}

static bool startConverters(uint8_t gainCode) {
  digitalWrite(PIN_RESET, LOW);      // hardware reset: low for > 2048 clocks (0.25 ms)
  delay(2);
  digitalWrite(PIN_RESET, HIGH);
  delay(5);
  // A missing clock or a soldering fault on a converter shows up here.
  uint16_t idA = adcA.read_reg(ads131::REG_ID);
  uint16_t idB = adcB.read_reg(ads131::REG_ID);
  Serial.printf("ADC A id 0x%04X, ADC B id 0x%04X\n", idA, idB);
  if ((idA >> 8) != 0x28 || (idB >> 8) != 0x28) return false;
  bool ok = adcA.configure(gainCode, ads131::kOsr16256, DCBLOCK);
  ok = adcB.configure(gainCode, ads131::kOsr16256, DCBLOCK) && ok;
  syncPulse();
  return ok;
}

static void adcLoop(void *) {
  uint8_t counter = 0;
  int32_t a[8], b[8], ch[limpet::kChannels];
  Packet p;
  for (;;) {
    if (!ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(200))) {
      // No data-ready edge for 50 sample periods: reading fell behind and the
      // converters' buffers are full. Clear them and carry on.
      if (adcOk) {
        xSemaphoreTake(spiLock, portMAX_DELAY);
        syncPulse();
        xSemaphoreGive(spiLock);
      }
      continue;
    }
    if (!adcOk) continue;
    xSemaphoreTake(spiLock, portMAX_DELAY);
    adcA.read_samples(a);
    adcB.read_samples(b);
    xSemaphoreGive(spiLock);
    limpet::order_channels(a, b, ch);
    limpet::build_packet(counter++, ch, p.bytes);
    if (connected) xQueueSend(packetQueue, &p, 0);   // drop rather than stall the ADC
  }
}

// ---- Bluetooth --------------------------------------------------------------
class ServerEvents : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *server, NimBLEConnInfo &info) override {
    connected = true;
    server->updateConnParams(info.getConnHandle(), 6, 12, 0, 200);   // 7.5-15 ms interval
  }
  void onDisconnect(NimBLEServer *, NimBLEConnInfo &, int) override {
    connected = false;
    NimBLEDevice::startAdvertising();
  }
};

// Commands (write to the command characteristic, reply comes as a notification):
//   'G' code            set PGA gain code 0..7 (gain 1..128) on all channels -> 'G' code ok
//   'R' adc addr        read a register (adc 0 = A, 1 = B)                   -> 'R' adc addr hi lo
//   'W' adc addr hi lo  write a register                                      -> 'W' adc addr ok
class CommandEvents : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c, NimBLEConnInfo &) override {
    std::string v = c->getValue();
    if (v.empty()) return;
    uint8_t reply[5] = {uint8_t(v[0]), 0, 0, 0, 0};
    size_t n = 1;
    xSemaphoreTake(spiLock, portMAX_DELAY);
    if (v[0] == 'G' && v.size() >= 2) {
      bool ok = adcA.set_gain_code(v[1]) && adcB.set_gain_code(v[1]);
      syncPulse();
      reply[1] = v[1] & 7; reply[2] = ok; n = 3;
    } else if (v[0] == 'R' && v.size() >= 3) {
      uint16_t r = (v[1] ? adcB : adcA).read_reg(v[2]);
      reply[1] = v[1]; reply[2] = v[2]; reply[3] = r >> 8; reply[4] = r & 0xFF; n = 5;
    } else if (v[0] == 'W' && v.size() >= 5) {
      uint16_t val = (uint16_t(uint8_t(v[3])) << 8) | uint8_t(v[4]);
      bool ok = (v[1] ? adcB : adcA).write_reg_verified(v[2], val);
      syncPulse();
      reply[1] = v[1]; reply[2] = v[2]; reply[3] = ok; n = 4;
    } else {
      reply[0] = '?';
    }
    xSemaphoreGive(spiLock);
    cmdChar->setValue(reply, n);
    cmdChar->notify();
  }
};

static void startBluetooth() {
  uint64_t mac = ESP.getEfuseMac();
  char name[20];
  snprintf(name, sizeof(name), "Limpet-16-%04X", (unsigned)((mac >> 32) & 0xFFFF));
  NimBLEDevice::init(name);
  NimBLEDevice::setMTU(128);
  NimBLEServer *server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerEvents());
  NimBLEService *service = server->createService(SERVICE_UUID);
  dataChar = service->createCharacteristic(DATA_UUID, NIMBLE_PROPERTY::NOTIFY);
  cmdChar = service->createCharacteristic(COMMAND_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::NOTIFY);
  cmdChar->setCallbacks(new CommandEvents());
  service->start();
  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setName(name);
  adv->start();
  Serial.printf("advertising as %s\n", name);
}

void setup() {
  // Park the bus before anything else (the board's pull-ups hold it until here).
  pinMode(PIN_CS_A, OUTPUT); digitalWrite(PIN_CS_A, HIGH);
  pinMode(PIN_CS_B, OUTPUT); digitalWrite(PIN_CS_B, HIGH);
  pinMode(PIN_RESET, OUTPUT); digitalWrite(PIN_RESET, HIGH);
  pinMode(PIN_DRDY, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  SPI.begin(PIN_SCLK, PIN_MISO, PIN_MOSI, -1);

  spiLock = xSemaphoreCreateMutex();
  packetQueue = xQueueCreate(64, sizeof(Packet));
  adcOk = startConverters(DEFAULT_GAIN_CODE);
  Serial.println(adcOk ? "converters configured" : "CONVERTERS NOT FOUND: check clock and soldering");
  startBluetooth();
  xTaskCreate(adcLoop, "adc", 4096, nullptr, 10, &adcTask);   // the C3 has one core
  attachInterrupt(digitalPinToInterrupt(PIN_DRDY), onDrdy, FALLING);
  // Bluetooth start-up took many sample periods: begin from clean buffers.
  if (adcOk) syncPulse();
}

void loop() {
  // LED: solid = streaming, slow blink = waiting for a
  // connection, fast double blink = converters not found.
  static uint32_t lastLed = 0;
  Packet p;
  if (xQueueReceive(packetQueue, &p, pdMS_TO_TICKS(20)) == pdTRUE && connected) {
    dataChar->setValue(p.bytes, sizeof(p.bytes));
    dataChar->notify();
  }
  uint32_t now = millis();
  if (now - lastLed >= 50) {
    lastLed = now;
    bool on;
    if (!adcOk) on = ((now / 100) % 10) == 0 || ((now / 100) % 10) == 2;
    else if (connected) on = true;
    else on = ((now / 500) % 2) == 0;
    digitalWrite(PIN_LED, on ? HIGH : LOW);
  }
}
