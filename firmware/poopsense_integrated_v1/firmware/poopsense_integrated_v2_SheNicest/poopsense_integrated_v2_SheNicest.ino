/*
  ============================================================================
  PoopSense Integrated V1 - Step 7A
  Unified Sensor Result Interface
  ----------------------------------------------------------------------------
  Included in this version:
    1. Two independent I2C buses
    2. APDS9960 initialization
    3. MLX90640 initialization
    4. AS7341 initialization
    5. BME688 + BSEC + AI Studio initialization
    6. BME688 bsec_iot_loop() in an independent FreeRTOS task
    7. BUS B mutex shared by BME688 and future AS7341 runtime access
    8. Arduino main loop heartbeat to prove coexistence
    9. APDS9960 B-layer raw proximity acquisition
   10. MLX90640 B-layer raw thermal frame acquisition
   11. AS7341 B-layer raw 12-channel acquisition + F1..F8 spectrum
   12. AS7341/BME688 BUS B sensor-operation arbitration with busBMutex
   13. APDS9960 C-layer hysteresis + 3-consecutive-sample NEAR/FAR algorithm
   14. MLX90640 empty-scene background calibration
   15. MLX90640 C-layer mask + noise removal + connected components
   16. MLX90640 shape features + rough shape classification
   17. AS7341 white-reference calibration
   18. AS7341 reflectance + normalization feature extraction
   19. AS7341 cosine-template color classification
   20. AS7341 W/V/M/H command interface
   21. BME688 BSEC/AI-Studio shared result state
   22. Thread-safe BME result snapshot for PoopSense main loop
   23. Stable AIR / ALCOHOL / UNCERTAIN / WARMING_UP system result

  NOT included yet:
    - PoopSense state machine

  Hardware topology verified in Step 3:

    BUS A: GPIO6 / GPIO7
      APDS9960  -> 0x39
      MLX90640  -> 0x33

    BUS B: GPIO8 / GPIO9
      AS7341     -> 0x39
      BME688     -> 0x77

  Important:
    Both buses are started at 100 kHz in this Step 4 initialization test.
    This is intentionally conservative because Step 3 already proved that
    all devices acknowledge correctly at 100 kHz.
  ============================================================================
*/

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_MLX90640.h>
#include <Adafruit_AS7341.h>

#include <Preferences.h>
#include <esp_timer.h>
#include <BSEC3_ESP32S3.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

extern "C" {
#include "bsec_integration.h"
#include "Air_VS_Alcohol_V_354_10.h"
}

// BSEC 3.3 initialization uses sizable work/config/state buffers on the
// Arduino loop task stack. Preserve the requirement from the validated
// standalone BME688 sketch.
SET_LOOP_TASK_STACK_SIZE(24 * 1024);

// ============================================================================
// SYSTEM CONFIGURATION
// ============================================================================

constexpr uint32_t SERIAL_BAUD = 115200;


// Step 4C runtime test settings.
constexpr uint32_t MAIN_LOOP_HEARTBEAT_MS = 2000;
constexpr uint32_t POOPSENSE_RESULT_PRINT_INTERVAL_MS = 1000;

constexpr uint32_t APDS_RAW_SAMPLE_INTERVAL_MS = 50;
constexpr uint32_t APDS_RAW_PRINT_INTERVAL_MS = 250;


// ============================================================================
// STEP 6A APDS9960 C-LAYER ALGORITHM CONFIGURATION
// ============================================================================
// Copied from the validated standalone APDS9960 sketch.
//
// Hysteresis:
//   FAR -> NEAR only when proximity >= 40
//   NEAR -> FAR only when proximity <= 25
//
// Debounce:
//   require 3 consecutive qualifying VALID samples before state transition.

constexpr uint8_t PROXIMITY_NEAR_THRESHOLD = 40;
constexpr uint8_t PROXIMITY_FAR_THRESHOLD = 25;
constexpr uint8_t REQUIRED_CONSECUTIVE_SAMPLES = 3;

// MLX is intentionally sampled every 2 s during this coexistence test.
// A complete getFrame() is blocking and must be kept atomic on BUS A.
constexpr uint32_t MLX_RAW_SAMPLE_INTERVAL_MS = 2000;
constexpr uint32_t MLX_RAW_PRINT_INTERVAL_MS = 1000;

// AS7341 raw coexistence test:
// one hardware spectrum per second is sufficient for B-layer validation.
constexpr uint32_t AS7341_RAW_SAMPLE_INTERVAL_MS = 1000;
constexpr uint32_t AS7341_RAW_PRINT_INTERVAL_MS = 1000;


// ============================================================================
// STEP 6C AS7341 ORIGINAL COLOR-CLASSIFIER PARAMETERS
// ============================================================================
// Preserved from the validated standalone AS7341 color classifier.

constexpr uint8_t AS7341_WHITE_FRAMES = 20;
constexpr uint8_t AS7341_TARGET_FRAMES = 5;
constexpr uint32_t AS7341_PRE_MEASURE_DELAY_MS = 1500;

// These must be declared before AS7341_DIGITAL_FULL_SCALE below.
// Values are unchanged from the validated standalone AS7341 sketch.
constexpr uint8_t AS7341_SENSOR_ATIME = 29;
constexpr uint16_t AS7341_SENSOR_ASTEP = 599;

// With ATIME=29 and ASTEP=599, the digital counter ceiling is 18000.
constexpr uint32_t AS7341_DIGITAL_FULL_SCALE =
    (AS7341_SENSOR_ATIME + 1UL) *
    (AS7341_SENSOR_ASTEP + 1UL);

constexpr float AS7341_SATURATION_LIMIT =
    AS7341_DIGITAL_FULL_SCALE * 0.95f;

// Thresholds validated against the original 40 color-card samples.
constexpr float AS7341_MIN_BEST_SCORE = 0.990f;
constexpr float AS7341_MIN_SCORE_GAP = 0.020f;

// Step 5B timing fix:
// APDS9960 gets its own higher-priority FreeRTOS task so mlx.getFrame()
// cannot reduce APDS sampling to the MLX full-frame cadence.
constexpr uint32_t APDS_TASK_STACK_BYTES = 4 * 1024;
constexpr UBaseType_t APDS_TASK_PRIORITY = 2;
constexpr BaseType_t APDS_TASK_CORE = 1;
constexpr uint32_t BME688_TASK_STACK_BYTES = 32 * 1024;
constexpr UBaseType_t BME688_TASK_PRIORITY = 1;
constexpr BaseType_t BME688_TASK_CORE = 0;

// Application-side post-processing policy preserved from the validated
// standalone Air-vs-Alcohol sketch.
constexpr float MIN_CLASS_PROBABILITY = 0.60f;
constexpr float MIN_CLASS_MARGIN = 0.15f;
constexpr uint8_t ALCOHOL_CONFIRMATION_SCANS = 3;

// BUS A: APDS9960 + MLX90640
constexpr int BUS_A_SDA = 6;
constexpr int BUS_A_SCL = 7;
// Both devices on BUS A support this operating point in this integration.
// APDS9960 supports I2C SCL up to 400 kHz; MLX standalone was validated at
// 400 kHz. Keeping one fixed clock avoids cross-task setClock() races.
constexpr uint32_t BUS_A_FREQUENCY = 400000;

// BUS B: AS7341 + BME688 (BME688 comes later)
constexpr int BUS_B_SDA = 8;
constexpr int BUS_B_SCL = 9;
constexpr uint32_t BUS_B_FREQUENCY = 100000;

// Two independent ESP32-S3 I2C controllers.
TwoWire I2CBusA = TwoWire(0);
TwoWire I2CBusB = TwoWire(1);

// ============================================================================
// SENSOR OBJECTS
// ============================================================================

Adafruit_MLX90640 mlx;
Adafruit_AS7341 as7341;


// ============================================================================
// STEP 4C RUNTIME / CONCURRENCY STATE
// ============================================================================

// BUS B is physically shared by:
//   AS7341 @ 0x39
//   BME688 @ 0x77
//
// BME688 will run in its own FreeRTOS task, so every BME688 I2C transaction
// must take this mutex. Later, every AS7341 runtime transaction must use the
// same mutex too.
SemaphoreHandle_t busBMutex = nullptr;

TaskHandle_t bme688TaskHandle = nullptr;

volatile bool bme688RuntimeStarted = false;
volatile bool bme688RuntimeReturnedUnexpectedly = false;

static uint8_t alcoholStreak = 0;


// ============================================================================
// STEP 6D BME688 SHARED CLASSIFICATION RESULT
// ============================================================================
//
// BME688 classification is produced inside the BME FreeRTOS task.
// The PoopSense main loop runs on another task/core.
//
// Therefore:
//   BME Task  -> writes the latest classification snapshot
//   Main Loop -> reads a consistent snapshot
//
// A dedicated result mutex is used so the main loop never reads a mixture
// of fields from two different BSEC updates.

SemaphoreHandle_t bmeResultMutex = nullptr;

float bmeLastAirProbability = 0.0f;
float bmeLastAlcoholProbability = 0.0f;

uint8_t bmeLastAccuracy = 0;
uint8_t bmeLastAlcoholStreak = 0;

uint32_t bmeLastRawGasIndex = 0;
int32_t bmeLastBsecStatus = 0;

uint32_t bmeLastResultMillis = 0;
uint32_t bmeResultUpdateCount = 0;

char bmeLastInstantClass[24] = "NO_DATA";
char bmeLastDecision[24] = "NO_DATA";

bool bmeHasResult = false;
bool bmeStableResultReady = false;

bool lockBMEResult(
    TickType_t timeoutTicks = pdMS_TO_TICKS(100))
{
  if (bmeResultMutex == nullptr) {
    return false;
  }

  return xSemaphoreTake(
             bmeResultMutex,
             timeoutTicks) == pdTRUE;
}

void unlockBMEResult()
{
  if (bmeResultMutex != nullptr) {
    xSemaphoreGive(bmeResultMutex);
  }
}


// ============================================================================
// STEP 7A POOPSENSE UNIFIED SENSOR RESULT
// ============================================================================

struct PoopSenseUnifiedResult {
  char proximity[8];
  uint8_t proximityRaw;
  bool proximityValid;
  uint32_t proximityUpdatedMs;

  char shape[16];
  bool shapeValid;
  uint32_t shapeUpdatedMs;

  char colorCategory[20];
  float colorConfidence;
  bool colorConfidenceValid;
  bool colorValid;
  uint32_t colorUpdatedMs;

  char odorDeviation[20];
  char odorAbsoluteClass[20];
  float odorConfidence;
  bool odorConfidenceValid;
  bool odorValid;
  bool odorStable;
  uint32_t odorUpdatedMs;

  bool temperatureValid;
  float temperatureC;
  bool humidityValid;
  float humidityPct;
};

PoopSenseUnifiedResult poopSenseResult = {};

SemaphoreHandle_t poopSenseResultMutex = nullptr;

bool lockPoopSenseResult(
    TickType_t timeoutTicks = pdMS_TO_TICKS(100))
{
  if (poopSenseResultMutex == nullptr) return false;
  return xSemaphoreTake(
             poopSenseResultMutex,
             timeoutTicks) == pdTRUE;
}

void unlockPoopSenseResult()
{
  if (poopSenseResultMutex != nullptr) {
    xSemaphoreGive(poopSenseResultMutex);
  }
}

bool lockBusB(TickType_t timeoutTicks = pdMS_TO_TICKS(1000))
{
  if (busBMutex == nullptr) {
    return false;
  }

  return xSemaphoreTake(busBMutex, timeoutTicks) == pdTRUE;
}

void unlockBusB()
{
  if (busBMutex != nullptr) {
    xSemaphoreGive(busBMutex);
  }
}

// ============================================================================
// APDS9960 CONSTANTS
// ============================================================================

constexpr uint8_t APDS9960_ADDRESS = 0x39;

constexpr uint8_t APDS_REG_ENABLE  = 0x80;
constexpr uint8_t APDS_REG_ATIME   = 0x81;
constexpr uint8_t APDS_REG_WTIME   = 0x83;
constexpr uint8_t APDS_REG_PPULSE  = 0x8E;
constexpr uint8_t APDS_REG_CONTROL = 0x8F;
constexpr uint8_t APDS_REG_CONFIG2 = 0x90;
constexpr uint8_t APDS_REG_ID      = 0x92;
constexpr uint8_t APDS_REG_STATUS  = 0x93;
constexpr uint8_t APDS_REG_PDATA   = 0x9C;

constexpr uint8_t APDS_STATUS_PVALID = 0x02;

constexpr uint8_t APDS_ENABLE_PON = 0x01;
constexpr uint8_t APDS_ENABLE_PEN = 0x04;


// ============================================================================
// BUS A SENSOR-LEVEL MUTEX
// ============================================================================
//
// TwoWire protects individual I2C transactions, but MLX getFrame() is a
// multi-transaction sequence. APDS must not interleave inside that sequence.
//
// Lock granularity:
//   APDS -> one complete readAPDS9960Raw()
//   MLX  -> one complete mlx.getFrame()

SemaphoreHandle_t busAMutex = nullptr;

bool lockBusA(TickType_t timeoutTicks = pdMS_TO_TICKS(1000))
{
  if (busAMutex == nullptr) return false;
  return xSemaphoreTake(busAMutex, timeoutTicks) == pdTRUE;
}

void unlockBusA()
{
  if (busAMutex != nullptr) xSemaphoreGive(busAMutex);
}

// ============================================================================
// STEP 5A APDS9960 RAW RUNTIME STATE
// ============================================================================

volatile uint8_t lastAPDSProximity = 0;
volatile bool lastAPDSSampleValid = false;

uint32_t lastAPDSPrintMs = 0;

volatile uint32_t apdsValidSampleCount = 0;
volatile uint32_t apdsReadErrorCount = 0;
volatile uint32_t apdsLastValidSampleMs = 0;

TaskHandle_t apdsSamplingTaskHandle = nullptr;
volatile bool apdsSamplingTaskStarted = false;


// ============================================================================
// STEP 6A APDS9960 C-LAYER STATE
// ============================================================================

volatile bool apdsObjectDetected = false;  // false=FAR, true=NEAR

volatile uint8_t apdsNearSampleCount = 0;
volatile uint8_t apdsFarSampleCount = 0;

volatile uint32_t apdsNearTransitionCount = 0;
volatile uint32_t apdsFarTransitionCount = 0;

volatile uint32_t apdsLastTransitionMs = 0;


// ============================================================================
// STEP 5B MLX90640 RAW RUNTIME STATE
// ============================================================================

constexpr uint16_t MLX_WIDTH = 32;
constexpr uint16_t MLX_HEIGHT = 24;
constexpr uint16_t MLX_PIXEL_COUNT = MLX_WIDTH * MLX_HEIGHT;

float mlxFrame[MLX_PIXEL_COUNT];

bool lastMLXFrameValid = false;
float lastMLXMinC = NAN;
float lastMLXMaxC = NAN;
float lastMLXAvgC = NAN;

uint32_t lastMLXSampleMs = 0;
uint32_t lastMLXPrintMs = 0;

uint32_t mlxValidFrameCount = 0;
uint32_t mlxFrameErrorCount = 0;

uint32_t lastMLXReadDurationMs = 0;
uint32_t maxMLXReadDurationMs = 0;


// ============================================================================
// STEP 6B MLX90640 BACKGROUND + C-LAYER STATE
// ============================================================================
// Preserved from the validated standalone mlx90640_shape_improved sketch.

constexpr uint8_t MLX_BACKGROUND_FRAME_COUNT = 8;
constexpr uint16_t MLX_MIN_COMPONENT_PIXELS = 3;

float mlxBackgroundFrame[MLX_PIXEL_COUNT];
uint8_t mlxRawMask[MLX_PIXEL_COUNT];
uint8_t mlxCleanMask[MLX_PIXEL_COUNT];
uint8_t mlxVisited[MLX_PIXEL_COUNT];
uint16_t mlxPixelQueue[MLX_PIXEL_COUNT];

float mlxDifferenceThresholdC = 1.5f;

volatile bool mlxBackgroundReady = false;
bool lastMLXShapeValid = false;

// Arduino .ino preprocessor note:
// Functions below intentionally DO NOT use MLXShapeStats in their
// parameter/return signatures. Arduino auto-generates function prototypes
// before compiling the sketch, which can otherwise place a prototype before
// this custom struct definition and produce:
//   'MLXShapeStats' does not name a type
//
struct MLXShapeStats {
  uint16_t totalPixels;
  uint16_t largestArea;
  uint16_t componentCount;
  uint8_t minX;
  uint8_t minY;
  uint8_t maxX;
  uint8_t maxY;
  float centerX;
  float centerY;
  float fillRatio;
};

MLXShapeStats lastMLXShapeStats = {};
const char *lastMLXShapeClass = "none";
uint32_t mlxShapeProcessCount = 0;
uint32_t mlxLastShapeResultMs = 0;

// ============================================================================
// AS7341 INITIALIZATION CONSTANTS
// ============================================================================

constexpr uint8_t AS7341_ADDRESS = 0x39;



// ============================================================================
// STEP 5C AS7341 B-LAYER CHANNEL MAPPING
// ============================================================================
// Mapping copied from the validated standalone color classifier.
// Adafruit readAllChannels() returns 12 entries. F1..F8 are located here.

const uint8_t AS7341_F_INDEX[8] = {0, 1, 2, 3, 6, 7, 8, 9};

// ============================================================================
// STEP 5C AS7341 RAW RUNTIME STATE
// ============================================================================

uint16_t lastAS7341Raw12[12] = {0};
float lastAS7341Spectrum8[8] = {0.0f};

bool lastAS7341SampleValid = false;

uint32_t lastAS7341SampleMs = 0;
uint32_t lastAS7341PrintMs = 0;

uint32_t as7341ValidSampleCount = 0;
uint32_t as7341ReadErrorCount = 0;
uint32_t as7341MutexTimeoutCount = 0;

uint32_t lastAS7341ReadDurationMs = 0;
uint32_t maxAS7341ReadDurationMs = 0;
uint32_t lastAS7341MutexWaitMs = 0;
uint32_t maxAS7341MutexWaitMs = 0;


// ============================================================================
// STEP 6C AS7341 WHITE-REFERENCE / CLASSIFICATION STATE
// ============================================================================

float as7341WhiteReference[8] = {0.0f};
bool as7341WhiteReady = false;

struct AS7341ColorTemplate {
  const char *name;
  uint32_t displayRgb;
  float spectrum[8];
};

// Mean normalized templates copied from the validated standalone classifier.
const AS7341ColorTemplate AS7341_COLOR_TEMPLATES[] = {
  {
    "RED", 0xFF0000,
    {0.192056f, 0.129937f, 0.179366f, 0.142115f,
     0.136875f, 0.378487f, 0.605073f, 0.604782f}
  },
  {
    "GREEN", 0x00FF00,
    {0.232653f, 0.169144f, 0.276811f, 0.556178f,
     0.485368f, 0.366314f, 0.291271f, 0.276943f}
  },
  {
    "BLUE", 0x0000FF,
    {0.398460f, 0.455989f, 0.472016f, 0.420273f,
     0.267410f, 0.239179f, 0.228850f, 0.229759f}
  },
  {
    "YELLOW", 0xFFFF00,
    {0.193776f, 0.126903f, 0.207988f, 0.395469f,
     0.443396f, 0.444255f, 0.430853f, 0.408773f}
  }
};

constexpr uint8_t AS7341_COLOR_COUNT =
    sizeof(AS7341_COLOR_TEMPLATES) /
    sizeof(AS7341_COLOR_TEMPLATES[0]);

const char *lastAS7341ColorResult = "NOT_CALIBRATED";
float lastAS7341BestScore = 0.0f;
float lastAS7341SecondScore = 0.0f;
float lastAS7341ScoreGap = 0.0f;
float lastAS7341Brightness = 0.0f;
uint32_t as7341ClassificationCount = 0;
uint32_t as7341UnknownCount = 0;
uint32_t as7341LastClassificationMs = 0;


// ============================================================================
// BME688 / BSEC A-INIT CONSTANTS AND STATE
// ============================================================================

constexpr uint8_t BME688_ADDRESS = BME68X_I2C_ADDR_HIGH;  // 0x77

static uint8_t bme688I2CAddress = BME688_ADDRESS;
static Preferences bme688Preferences;

// The AI-Studio-generated config must match the BSEC 3.3 property blob size.
static_assert(sizeof(bsec_config_selectivity) == BSEC_MAX_PROPERTY_BLOB_SIZE,
              "AI-Studio config length does not match BSEC 3.3");

// ============================================================================
// BME688 LOW-LEVEL BUS CALLBACKS - BUS B + MUTEX
// ============================================================================
//
// bsec_iot_loop() will run in another FreeRTOS task. These callbacks therefore
// serialize every BME688 transaction on BUS B.
//
// IMPORTANT FOR LATER AS7341 RUNTIME:
// AS7341 must take the SAME busBMutex around each complete Adafruit_AS7341
// operation before its B/Raw integration is added.

int8_t bmeBusWrite(uint8_t registerAddress,
                   const uint8_t *data,
                   uint32_t length,
                   void *interfacePointer)
{
  if (!lockBusB()) {
    return BME68X_E_COM_FAIL;
  }

  const uint8_t address =
      *static_cast<uint8_t *>(interfacePointer);

  I2CBusB.beginTransmission(address);
  I2CBusB.write(registerAddress);

  if (I2CBusB.write(data, length) != length) {
    I2CBusB.endTransmission(true);
    unlockBusB();
    return BME68X_E_COM_FAIL;
  }

  const uint8_t error = I2CBusB.endTransmission(true);

  unlockBusB();

  return error == 0 ? BME68X_OK : BME68X_E_COM_FAIL;
}

int8_t bmeBusRead(uint8_t registerAddress,
                  uint8_t *data,
                  uint32_t length,
                  void *interfacePointer)
{
  if (!lockBusB()) {
    return BME68X_E_COM_FAIL;
  }

  const uint8_t address =
      *static_cast<uint8_t *>(interfacePointer);

  I2CBusB.beginTransmission(address);
  I2CBusB.write(registerAddress);

  if (I2CBusB.endTransmission(false) != 0) {
    unlockBusB();
    return BME68X_E_COM_FAIL;
  }

  const size_t received =
      I2CBusB.requestFrom(address,
                          static_cast<size_t>(length),
                          true);

  if (received != length) {
    unlockBusB();
    return BME68X_E_COM_FAIL;
  }

  for (uint32_t i = 0; i < length; ++i) {
    data[i] = static_cast<uint8_t>(I2CBusB.read());
  }

  unlockBusB();

  return BME68X_OK;
}

void bmeSleepMicroseconds(uint32_t durationUs, void *)
{
  // No BUS B mutex is held while sleeping. This is essential: it allows
  // AS7341 to use BUS B in the future while BME688 waits for heater/sampling
  // timing.
  if (durationUs >= 1000) {
    delay(durationUs / 1000);
    durationUs %= 1000;
  }

  if (durationUs) {
    delayMicroseconds(durationUs);
  }
}

int64_t bmeTimestampMicroseconds()
{
  return esp_timer_get_time();
}

// ============================================================================
// BME688 / BSEC STATE + AI-STUDIO CONFIG LOAD
// ============================================================================

uint32_t loadBME688BsecState(uint8_t *stateBuffer,
                             uint32_t bufferSize)
{
  if (!bme688Preferences.begin("bsec3_aav1_354", true)) {
    return 0;
  }

  const size_t length =
      bme688Preferences.getBytesLength("state");

  if (length == 0 || length > bufferSize) {
    bme688Preferences.end();
    return 0;
  }

  const size_t loaded =
      bme688Preferences.getBytes("state",
                                 stateBuffer,
                                 length);

  bme688Preferences.end();

  Serial.printf("Loaded BSEC state: %u bytes\n",
                static_cast<unsigned>(loaded));

  return static_cast<uint32_t>(loaded);
}

uint32_t loadBME688BsecConfig(uint8_t *configBuffer,
                              uint32_t bufferSize)
{
  if (bufferSize != sizeof(bsec_config_selectivity)) {
    return 0;
  }

  memcpy(configBuffer,
         bsec_config_selectivity,
         sizeof(bsec_config_selectivity));

  return sizeof(bsec_config_selectivity);
}

// ============================================================================
// SYSTEM HELPER: I2C SCANNER
// ============================================================================

void scanI2CBus(TwoWire &bus, const char *busName)
{
  Serial.println();
  Serial.print("Scanning ");
  Serial.println(busName);

  uint8_t found = 0;

  for (uint8_t address = 1; address < 127; address++) {
    bus.beginTransmission(address);
    uint8_t error = bus.endTransmission();

    if (error == 0) {
      Serial.printf("  Found device at 0x%02X\n", address);
      found++;
    }
  }

  if (found == 0) {
    Serial.println("  No I2C devices found.");
  } else {
    Serial.print("  Total devices found: ");
    Serial.println(found);
  }
}

// ============================================================================
// APDS9960 LOW-LEVEL I2C HELPERS
// ============================================================================
// These preserve the behavior of the existing APDS9960 sketch,
// but explicitly use BUS A instead of the global Wire object.

bool apdsWriteRegister(uint8_t reg, uint8_t value)
{
  I2CBusA.beginTransmission(APDS9960_ADDRESS);
  I2CBusA.write(reg);
  I2CBusA.write(value);

  return I2CBusA.endTransmission() == 0;
}

bool apdsReadRegister(uint8_t reg, uint8_t &value)
{
  I2CBusA.beginTransmission(APDS9960_ADDRESS);
  I2CBusA.write(reg);

  // Repeated start: keep the bus active.
  if (I2CBusA.endTransmission(false) != 0) {
    return false;
  }

  if (I2CBusA.requestFrom(
        static_cast<uint8_t>(APDS9960_ADDRESS),
        static_cast<uint8_t>(1)) != 1) {
    return false;
  }

  value = I2CBusA.read();
  return true;
}

bool apdsIsDevicePresent()
{
  I2CBusA.beginTransmission(APDS9960_ADDRESS);
  return I2CBusA.endTransmission() == 0;
}

// ============================================================================
// B1. APDS9960 RAW SENSOR READ
// ============================================================================
//
// This function is copied logically from the validated APDS9960 B layer:
//   1) read STATUS
//   2) require PVALID
//   3) read PDATA
//
// It deliberately performs NO thresholding, hysteresis, near/far debounce,
// or USER_DETECTED classification. Those belong to C and are NOT part of
// Step 5A.

bool readAPDS9960Raw(uint8_t &proximity)
{
  uint8_t status = 0;

  if (!apdsReadRegister(APDS_REG_STATUS, status)) {
    apdsReadErrorCount++;
    return false;
  }

  if ((status & APDS_STATUS_PVALID) == 0) {
    // Sensor has not produced a fresh/valid proximity sample yet.
    // This is not counted as an I2C error.
    return false;
  }

  if (!apdsReadRegister(APDS_REG_PDATA, proximity)) {
    apdsReadErrorCount++;
    return false;
  }

  apdsValidSampleCount++;
  return true;
}

// ============================================================================
// A1. APDS9960 SENSOR INIT
// ============================================================================

bool setupAPDS9960()
{
  Serial.println();
  Serial.println("[A] Initializing APDS9960...");

  if (!apdsIsDevicePresent()) {
    Serial.println("APDS9960: FAILED - address 0x39 not detected on BUS A.");
    return false;
  }

  uint8_t deviceID = 0;

  if (!apdsReadRegister(APDS_REG_ID, deviceID)) {
    Serial.println("APDS9960: FAILED - unable to read device ID.");
    return false;
  }

  Serial.printf("APDS9960 ID = 0x%02X\n", deviceID);

  if (deviceID != 0xAB && deviceID != 0x9C) {
    Serial.println("APDS9960: WARNING - unusual device ID; initialization will continue.");
  }

  // Preserve the register configuration from the known-good APDS9960 sketch.

  // Disable all functions before configuration.
  if (!apdsWriteRegister(APDS_REG_ENABLE, 0x00)) {
    Serial.println("APDS9960: FAILED while disabling sensor.");
    return false;
  }

  delay(10);

  // Ambient light integration time.
  if (!apdsWriteRegister(APDS_REG_ATIME, 0xDB)) {
    Serial.println("APDS9960: FAILED while setting ATIME.");
    return false;
  }

  // Wait time.
  if (!apdsWriteRegister(APDS_REG_WTIME, 0xF6)) {
    Serial.println("APDS9960: FAILED while setting WTIME.");
    return false;
  }

  // PPLEN = 16 us, 8 pulses.
  if (!apdsWriteRegister(APDS_REG_PPULSE, 0x87)) {
    Serial.println("APDS9960: FAILED while setting PPULSE.");
    return false;
  }

  // LED drive = 50 mA, proximity gain = 4x, ambient gain = 1x.
  if (!apdsWriteRegister(APDS_REG_CONTROL, 0x48)) {
    Serial.println("APDS9960: FAILED while setting CONTROL.");
    return false;
  }

  // LED boost = 100%.
  if (!apdsWriteRegister(APDS_REG_CONFIG2, 0x01)) {
    Serial.println("APDS9960: FAILED while setting CONFIG2.");
    return false;
  }

  // Power on + enable proximity engine.
  if (!apdsWriteRegister(
        APDS_REG_ENABLE,
        APDS_ENABLE_PON | APDS_ENABLE_PEN)) {
    Serial.println("APDS9960: FAILED while enabling proximity engine.");
    return false;
  }

  delay(20);

  Serial.println("APDS9960: OK");
  return true;
}

// ============================================================================
// B2. MLX90640 RAW SENSOR READ
// ============================================================================
//
// B-layer product:
//   mlxFrame[768] = one complete 32x24 temperature frame.
//
// Step 5B does NOT perform:
//   - background subtraction
//   - object mask
//   - connected components
//   - shape features
//   - shape classification
//
// To keep Serial usable, the full 768 values are NOT printed continuously.
// Instead, D/debug output reports min/max/average while the actual full raw
// frame remains in mlxFrame[] for later C-layer integration.

bool readMLX90640RawFrame()
{
  const uint32_t readStartMs = millis();

  if (!lockBusA(pdMS_TO_TICKS(1500))) {
    lastMLXReadDurationMs = millis() - readStartMs;
    mlxFrameErrorCount++;
    return false;
  }

  bool success = false;

  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (mlx.getFrame(mlxFrame) == 0) {
      success = true;
      break;
    }
    delay(30);
  }

  unlockBusA();

  lastMLXReadDurationMs = millis() - readStartMs;

  if (lastMLXReadDurationMs > maxMLXReadDurationMs) {
    maxMLXReadDurationMs = lastMLXReadDurationMs;
  }

  if (!success) {
    mlxFrameErrorCount++;
    return false;
  }

  float minC = INFINITY;
  float maxC = -INFINITY;
  double sumC = 0.0;
  uint16_t finiteCount = 0;

  for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
    const float t = mlxFrame[i];

    if (!isfinite(t)) {
      continue;
    }

    if (t < minC) minC = t;
    if (t > maxC) maxC = t;

    sumC += t;
    finiteCount++;
  }

  if (finiteCount == 0) {
    mlxFrameErrorCount++;
    return false;
  }

  lastMLXMinC = minC;
  lastMLXMaxC = maxC;
  lastMLXAvgC = static_cast<float>(sumC / finiteCount);

  mlxValidFrameCount++;
  return true;
}

// ============================================================================
// B2b. MLX90640 EMPTY-SCENE BACKGROUND ACQUISITION
// ============================================================================
//
// Same baseline strategy as the standalone MLX sketch:
//   - wait 3 seconds
//   - keep measurement area EMPTY
//   - acquire 8 complete frames
//   - average each pixel into mlxBackgroundFrame[]
//
// busAMutex is already used inside readMLX90640RawFrame().

bool captureMLXBackground()
{
  Serial.println();
  Serial.println("==================================================");
  Serial.println("[MLX BACKGROUND] Calibration starts in 3 seconds.");
  Serial.println("[MLX BACKGROUND] KEEP THE MLX VIEW EMPTY.");
  Serial.println("==================================================");

  delay(3000);

  for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
    mlxBackgroundFrame[i] = 0.0f;
  }

  for (uint8_t n = 0; n < MLX_BACKGROUND_FRAME_COUNT; ++n) {
    if (!readMLX90640RawFrame()) {
      Serial.printf(
          "[MLX BACKGROUND] FAILED at frame %u/%u\n",
          static_cast<unsigned>(n + 1),
          static_cast<unsigned>(MLX_BACKGROUND_FRAME_COUNT));

      mlxBackgroundReady = false;
      return false;
    }

    for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
      mlxBackgroundFrame[i] += mlxFrame[i];
    }

    Serial.printf(
        "[MLX BACKGROUND] frame %u/%u captured\n",
        static_cast<unsigned>(n + 1),
        static_cast<unsigned>(MLX_BACKGROUND_FRAME_COUNT));

    delay(250);
  }

  for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
    mlxBackgroundFrame[i] /= MLX_BACKGROUND_FRAME_COUNT;
  }

  mlxBackgroundReady = true;

  // Baseline frames are calibration data, not runtime measurement frames.
  mlxValidFrameCount = 0;
  mlxFrameErrorCount = 0;
  lastMLXFrameValid = false;
  lastMLXSampleMs = millis();

  Serial.println("[MLX BACKGROUND] COMPLETE");
  Serial.printf(
      "[MLX BACKGROUND] Difference threshold = %.2f C\n",
      mlxDifferenceThresholdC);

  return true;
}

// ============================================================================
// C1. MLX90640 OBJECT MASK + NOISE REMOVAL
// ============================================================================
// Logic preserved from the validated standalone sketch.

void buildMLXObjectMask()
{
  for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
    const float difference =
        mlxFrame[i] - mlxBackgroundFrame[i];

    mlxRawMask[i] =
        difference >= mlxDifferenceThresholdC ? 1 : 0;
  }

  // Remove isolated single-pixel noise.
  // A valid pixel requires at least 2 active neighbours in its 3x3 area.
  for (uint8_t y = 0; y < MLX_HEIGHT; ++y) {
    for (uint8_t x = 0; x < MLX_WIDTH; ++x) {
      uint8_t neighbourCount = 0;

      for (int8_t dy = -1; dy <= 1; ++dy) {
        for (int8_t dx = -1; dx <= 1; ++dx) {
          if (dx == 0 && dy == 0) {
            continue;
          }

          const int nx = x + dx;
          const int ny = y + dy;

          if (nx >= 0 && nx < MLX_WIDTH &&
              ny >= 0 && ny < MLX_HEIGHT) {
            neighbourCount +=
                mlxRawMask[ny * MLX_WIDTH + nx];
          }
        }
      }

      const uint16_t index =
          y * MLX_WIDTH + x;

      mlxCleanMask[index] =
          mlxRawMask[index] && neighbourCount >= 2
              ? 1
              : 0;
    }
  }
}

// ============================================================================
// C2. MLX90640 GEOMETRIC FEATURE EXTRACTION
// ============================================================================
// 8-connected components + largest component bounding box/center/fill ratio.

void calculateMLXShapeStats()
{
  MLXShapeStats result = {};

  result.minX = MLX_WIDTH;
  result.minY = MLX_HEIGHT;

  memset(mlxVisited, 0, sizeof(mlxVisited));

  for (uint16_t i = 0; i < MLX_PIXEL_COUNT; ++i) {
    result.totalPixels += mlxCleanMask[i];
  }

  for (uint16_t start = 0;
       start < MLX_PIXEL_COUNT;
       ++start) {

    if (!mlxCleanMask[start] ||
        mlxVisited[start]) {
      continue;
    }

    uint16_t head = 0;
    uint16_t tail = 0;
    uint16_t area = 0;

    uint32_t sumX = 0;
    uint32_t sumY = 0;

    uint8_t minX = MLX_WIDTH;
    uint8_t minY = MLX_HEIGHT;
    uint8_t maxX = 0;
    uint8_t maxY = 0;

    mlxPixelQueue[tail++] = start;
    mlxVisited[start] = 1;

    while (head < tail) {
      const uint16_t index =
          mlxPixelQueue[head++];

      const uint8_t x =
          index % MLX_WIDTH;

      const uint8_t y =
          index / MLX_WIDTH;

      ++area;
      sumX += x;
      sumY += y;

      minX = min(minX, x);
      minY = min(minY, y);
      maxX = max(maxX, x);
      maxY = max(maxY, y);

      // Eight-connected component search.
      for (int8_t dy = -1; dy <= 1; ++dy) {
        for (int8_t dx = -1; dx <= 1; ++dx) {
          if (dx == 0 && dy == 0) {
            continue;
          }

          const int nx = x + dx;
          const int ny = y + dy;

          if (nx < 0 || nx >= MLX_WIDTH ||
              ny < 0 || ny >= MLX_HEIGHT) {
            continue;
          }

          const uint16_t next =
              ny * MLX_WIDTH + nx;

          if (mlxCleanMask[next] &&
              !mlxVisited[next]) {
            mlxVisited[next] = 1;
            mlxPixelQueue[tail++] = next;
          }
        }
      }
    }

    if (area >= MLX_MIN_COMPONENT_PIXELS) {
      ++result.componentCount;
    }

    if (area > result.largestArea) {
      result.largestArea = area;
      result.minX = minX;
      result.minY = minY;
      result.maxX = maxX;
      result.maxY = maxY;

      result.centerX =
          static_cast<float>(sumX) / area;

      result.centerY =
          static_cast<float>(sumY) / area;
    }
  }

  if (result.largestArea > 0) {
    const uint16_t boxArea =
        (result.maxX - result.minX + 1) *
        (result.maxY - result.minY + 1);

    result.fillRatio =
        static_cast<float>(result.largestArea) /
        boxArea;
  }

  lastMLXShapeStats = result;
}

// ============================================================================
// C3. MLX90640 ROUGH SHAPE CLASSIFICATION
// ============================================================================
// Original hand-written thresholds preserved.

const char *estimateMLXRoughShape()
{
  if (lastMLXShapeStats.largestArea <
      MLX_MIN_COMPONENT_PIXELS) {
    return "none";
  }

  const uint8_t boxWidth =
      lastMLXShapeStats.maxX -
      lastMLXShapeStats.minX + 1;

  const uint8_t boxHeight =
      lastMLXShapeStats.maxY -
      lastMLXShapeStats.minY + 1;

  const float aspectRatio =
      boxWidth > boxHeight
          ? static_cast<float>(boxWidth) /
                boxHeight
          : static_cast<float>(boxHeight) /
                boxWidth;

  if (lastMLXShapeStats.componentCount >= 3 &&
      lastMLXShapeStats.largestArea <
          static_cast<uint16_t>(
              lastMLXShapeStats.totalPixels * 0.7f)) {
    return "scattered";
  }

  if (aspectRatio >= 2.2f) {
    return "elongated";
  }

  if (lastMLXShapeStats.fillRatio >= 0.65f) {
    return "compact";
  }

  return "irregular";
}

// ============================================================================
// C4. MLX90640 PROCESS CURRENT RAW FRAME
// ============================================================================

void processMLXShape()
{
  if (!mlxBackgroundReady) {
    lastMLXShapeValid = false;
    return;
  }

  buildMLXObjectMask();

  calculateMLXShapeStats();

  lastMLXShapeClass =
      estimateMLXRoughShape();

  lastMLXShapeValid = true;
  mlxShapeProcessCount++;
  mlxLastShapeResultMs = millis();
}

// ============================================================================
// A2. MLX90640 SENSOR INIT
// ============================================================================
// Note:
// captureBackground() is deliberately NOT included here because it belongs to
// B (baseline acquisition), not A (sensor initialization).

bool setupMLX90640()
{
  Serial.println();
  Serial.println("[A] Initializing MLX90640...");

  if (!mlx.begin(0x33, &I2CBusA)) {
    Serial.println("MLX90640: FAILED - address 0x33 not initialized on BUS A.");
    return false;
  }

  // Preserve configuration from the known-good MLX90640 sketch.
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_4_HZ);

  Serial.println("MLX90640: OK");
  Serial.println("  Mode       : CHESS");
  Serial.println("  Resolution : 18-bit ADC");
  Serial.println("  Refresh    : 4 Hz");

  return true;
}

// ============================================================================
// B3. AS7341 RAW SENSOR READ - BUS B MUTEX PROTECTED
// ============================================================================
//
// This is the B layer copied logically from the validated AS7341 sketch:
//
//   uint16_t raw[12]
//        ↓
//   as7341.readAllChannels(raw)
//        ↓
//   F_INDEX mapping
//        ↓
//   spectrum[8] = F1..F8
//
// CRITICAL STEP 5C RULE:
// lockBusB() is held for the ENTIRE Adafruit readAllChannels() operation.
// BME688 bsec_iot_loop() uses the same mutex in its low-level callbacks,
// so BME and AS7341 cannot overlap on GPIO8/GPIO9.
//
// NO white reference, averaging, reflectance, normalization, cosine similarity,
// or color classification is performed here.

bool readAS7341RawSpectrum()
{
  const uint32_t waitStartMs = millis();

  if (!lockBusB(pdMS_TO_TICKS(1000))) {
    lastAS7341MutexWaitMs = millis() - waitStartMs;

    if (lastAS7341MutexWaitMs > maxAS7341MutexWaitMs) {
      maxAS7341MutexWaitMs = lastAS7341MutexWaitMs;
    }

    as7341MutexTimeoutCount++;
    as7341ReadErrorCount++;
    return false;
  }

  lastAS7341MutexWaitMs = millis() - waitStartMs;

  if (lastAS7341MutexWaitMs > maxAS7341MutexWaitMs) {
    maxAS7341MutexWaitMs = lastAS7341MutexWaitMs;
  }

  const uint32_t readStartMs = millis();

  uint16_t raw[12] = {0};

  const bool ok = as7341.readAllChannels(raw);

  lastAS7341ReadDurationMs = millis() - readStartMs;

  if (lastAS7341ReadDurationMs > maxAS7341ReadDurationMs) {
    maxAS7341ReadDurationMs = lastAS7341ReadDurationMs;
  }

  // Release BUS B immediately after the complete hardware acquisition.
  unlockBusB();

  if (!ok) {
    as7341ReadErrorCount++;
    return false;
  }

  for (uint8_t i = 0; i < 12; ++i) {
    lastAS7341Raw12[i] = raw[i];
  }

  for (uint8_t i = 0; i < 8; ++i) {
    lastAS7341Spectrum8[i] =
        static_cast<float>(raw[AS7341_F_INDEX[i]]);
  }

  as7341ValidSampleCount++;
  return true;
}

// ============================================================================
// C1. AS7341 MULTI-FRAME AVERAGING
// ============================================================================
//
// Important integrated behavior:
// readAS7341RawSpectrum() takes busBMutex for ONE complete hardware frame and
// releases it immediately afterward. Therefore BME688 may use BUS B between
// color frames rather than being blocked for the entire 20/5-frame sequence.

bool averageAS7341Spectrum(uint8_t frameCount, float output[8])
{
  for (uint8_t i = 0; i < 8; ++i) {
    output[i] = 0.0f;
  }

  for (uint8_t frame = 0; frame < frameCount; ++frame) {
    if (!readAS7341RawSpectrum()) {
      return false;
    }

    for (uint8_t i = 0; i < 8; ++i) {
      output[i] += lastAS7341Spectrum8[i];
    }

    delay(20);
  }

  for (uint8_t i = 0; i < 8; ++i) {
    output[i] /= frameCount;
  }

  return true;
}

// ============================================================================
// C1. AS7341 SIGNAL QUALITY HELPERS
// ============================================================================

float as7341SpectrumMaximum(const float values[8])
{
  float maximum = values[0];

  for (uint8_t i = 1; i < 8; ++i) {
    if (values[i] > maximum) {
      maximum = values[i];
    }
  }

  return maximum;
}

bool as7341SignalIsUsable(
    const float values[8],
    const char *measurementName)
{
  const float maximum =
      as7341SpectrumMaximum(values);

  if (maximum >= AS7341_SATURATION_LIMIT) {
    Serial.printf(
        "[AS7341 COLOR ERROR],%s near saturation,max=%.1f\n",
        measurementName,
        maximum);
    return false;
  }

  for (uint8_t i = 0; i < 8; ++i) {
    if (values[i] < 20.0f) {
      Serial.printf(
          "[AS7341 COLOR ERROR],%s,F%u too low,value=%.1f\n",
          measurementName,
          static_cast<unsigned>(i + 1),
          values[i]);
      return false;
    }
  }

  return true;
}

// ============================================================================
// C2. AS7341 FEATURE EXTRACTION
// ============================================================================

bool calculateAS7341Features(
    const float raw[8],
    float reflectance[8],
    float normalized[8],
    float &brightness)
{
  if (!as7341WhiteReady) {
    return false;
  }

  brightness = 0.0f;
  float sumSquares = 0.0f;

  for (uint8_t i = 0; i < 8; ++i) {
    if (as7341WhiteReference[i] <= 0.0f) {
      return false;
    }

    reflectance[i] =
        raw[i] / as7341WhiteReference[i];

    brightness += reflectance[i];

    sumSquares +=
        reflectance[i] * reflectance[i];
  }

  brightness /= 8.0f;

  const float length = sqrtf(sumSquares);

  if (length < 0.000001f) {
    return false;
  }

  for (uint8_t i = 0; i < 8; ++i) {
    normalized[i] =
        reflectance[i] / length;
  }

  return true;
}

// ============================================================================
// C3. AS7341 COSINE SIMILARITY
// ============================================================================

float as7341CosineSimilarity(
    const float a[8],
    const float b[8])
{
  float score = 0.0f;

  for (uint8_t i = 0; i < 8; ++i) {
    score += a[i] * b[i];
  }

  return score;
}

// ============================================================================
// D HELPER. AS7341 VECTOR OUTPUT
// ============================================================================

void printAS7341Vector(
    const char *name,
    const float values[8],
    uint8_t decimals)
{
  Serial.print(name);
  Serial.print(": ");

  for (uint8_t i = 0; i < 8; ++i) {
    Serial.print(values[i], decimals);

    if (i < 7) {
      Serial.print(", ");
    }
  }

  Serial.println();
}

// ============================================================================
// STEP 6C ORCHESTRATION: WHITE CALIBRATION
// ============================================================================
// Original workflow preserved:
//   W -> wait 1.5 s -> average 20 frames -> signal check -> save baseline

void calibrateAS7341White()
{
  Serial.println();
  Serial.println("==================================================");
  Serial.println("[AS7341 WHITE] CALIBRATION");
  Serial.println("[AS7341 WHITE] Place the SAME white reference card");
  Serial.println("[AS7341 WHITE] at the validated measurement position.");
  Serial.println("[AS7341 WHITE] Move your hand away.");
  Serial.println("[AS7341 WHITE] Measurement starts in 1.5 seconds.");
  Serial.println("==================================================");

  delay(AS7341_PRE_MEASURE_DELAY_MS);

  float newWhite[8];

  if (!averageAS7341Spectrum(
          AS7341_WHITE_FRAMES,
          newWhite)) {
    Serial.println(
        "[AS7341 WHITE] ERROR: failed to acquire white reference.");
    return;
  }

  if (!as7341SignalIsUsable(
          newWhite,
          "white card")) {
    return;
  }

  for (uint8_t i = 0; i < 8; ++i) {
    as7341WhiteReference[i] =
        newWhite[i];
  }

  as7341WhiteReady = true;
  lastAS7341ColorResult = "READY";

  printAS7341Vector(
      "WHITE_RAW",
      as7341WhiteReference,
      1);

  Serial.printf(
      "WHITE_MAX: %.1f\n",
      as7341SpectrumMaximum(
          as7341WhiteReference));

  Serial.println(
      "[AS7341 WHITE] CALIBRATION COMPLETE");
}

// ============================================================================
// STEP 6C ORCHESTRATION: WHITE VERIFICATION
// ============================================================================

void verifyAS7341White()
{
  if (!as7341WhiteReady) {
    Serial.println(
        "[AS7341 WHITE] ERROR: calibrate first with W.");
    return;
  }

  Serial.println();
  Serial.println("[AS7341 WHITE] VERIFICATION");
  Serial.println(
      "[AS7341 WHITE] Keep the white reference in position.");
  Serial.println(
      "[AS7341 WHITE] Measurement starts in 1.5 seconds.");

  delay(AS7341_PRE_MEASURE_DELAY_MS);

  float raw[8];
  float reflectance[8];
  float normalized[8];
  float brightness = 0.0f;

  if (!averageAS7341Spectrum(
          AS7341_TARGET_FRAMES,
          raw) ||
      !as7341SignalIsUsable(
          raw,
          "white check") ||
      !calculateAS7341Features(
          raw,
          reflectance,
          normalized,
          brightness)) {

    Serial.println(
        "[AS7341 WHITE] ERROR: verification failed.");
    return;
  }

  float minR = reflectance[0];
  float maxR = reflectance[0];

  for (uint8_t i = 1; i < 8; ++i) {
    if (reflectance[i] < minR) {
      minR = reflectance[i];
    }

    if (reflectance[i] > maxR) {
      maxR = reflectance[i];
    }
  }

  printAS7341Vector(
      "WHITE_R",
      reflectance,
      4);

  Serial.printf(
      "WHITE_BRIGHTNESS: %.4f\n",
      brightness);

  Serial.printf(
      "WHITE_R_RANGE: %.4f .. %.4f\n",
      minR,
      maxR);

  if (brightness < 0.90f ||
      brightness > 1.10f ||
      minR < 0.85f ||
      maxR > 1.15f) {

    Serial.println(
        "[AS7341 WHITE] WARNING: recalibrate with W before classification.");
  } else {
    Serial.println(
        "[AS7341 WHITE] VERIFICATION PASSED");
  }
}

// ============================================================================
// STEP 6C ORCHESTRATION: COLOR MEASUREMENT + CLASSIFICATION
// ============================================================================
// Original workflow preserved:
//   M -> wait 1.5 s -> average 5 frames -> validate
//     -> reflectance -> normalize -> cosine scores
//     -> best/second/gap -> class or UNKNOWN

void classifyAS7341Card()
{
  if (!as7341WhiteReady) {
    Serial.println(
        "[AS7341 COLOR] ERROR: calibrate white first with W.");
    lastAS7341ColorResult =
        "NOT_CALIBRATED";
    return;
  }

  Serial.println();
  Serial.println("==================================================");
  Serial.println("[AS7341 COLOR] MEASUREMENT");
  Serial.println(
      "[AS7341 COLOR] Insert the color card at the validated position.");
  Serial.println(
      "[AS7341 COLOR] Move your hand away.");
  Serial.println(
      "[AS7341 COLOR] Measurement starts in 1.5 seconds.");
  Serial.println("==================================================");

  delay(AS7341_PRE_MEASURE_DELAY_MS);

  float raw[8];
  float reflectance[8];
  float normalized[8];
  float brightness = 0.0f;

  if (!averageAS7341Spectrum(
          AS7341_TARGET_FRAMES,
          raw)) {
    Serial.println(
        "[AS7341 COLOR] ERROR: spectrum read failed.");
    return;
  }

  if (!as7341SignalIsUsable(
          raw,
          "target card")) {
    return;
  }

  if (!calculateAS7341Features(
          raw,
          reflectance,
          normalized,
          brightness)) {
    Serial.println(
        "[AS7341 COLOR] ERROR: feature calculation failed.");
    return;
  }

  float scores[AS7341_COLOR_COUNT];

  int8_t bestIndex = -1;
  int8_t secondIndex = -1;

  for (uint8_t i = 0;
       i < AS7341_COLOR_COUNT;
       ++i) {

    scores[i] =
        as7341CosineSimilarity(
            normalized,
            AS7341_COLOR_TEMPLATES[i].spectrum);

    if (bestIndex < 0 ||
        scores[i] > scores[bestIndex]) {

      secondIndex = bestIndex;
      bestIndex = i;

    } else if (
        secondIndex < 0 ||
        scores[i] > scores[secondIndex]) {

      secondIndex = i;
    }
  }

  if (bestIndex < 0 ||
      secondIndex < 0) {
    Serial.println(
        "[AS7341 COLOR] ERROR: template scoring failed.");
    return;
  }

  const float bestScore =
      scores[bestIndex];

  const float secondScore =
      scores[secondIndex];

  const float scoreGap =
      bestScore - secondScore;

  const bool accepted =
      bestScore >= AS7341_MIN_BEST_SCORE &&
      scoreGap >= AS7341_MIN_SCORE_GAP;

  lastAS7341BestScore = bestScore;
  lastAS7341SecondScore = secondScore;
  lastAS7341ScoreGap = scoreGap;
  lastAS7341Brightness = brightness;

  as7341ClassificationCount++;
  as7341LastClassificationMs = millis();

  // Preserve original diagnostic outputs.
  printAS7341Vector(
      "RAW",
      raw,
      1);

  printAS7341Vector(
      "REFLECTANCE",
      reflectance,
      4);

  printAS7341Vector(
      "NORMALIZED",
      normalized,
      6);

  Serial.printf(
      "BRIGHTNESS: %.4f\n",
      brightness);

  Serial.print("SCORES: ");

  for (uint8_t i = 0;
       i < AS7341_COLOR_COUNT;
       ++i) {

    Serial.print(
        AS7341_COLOR_TEMPLATES[i].name);

    Serial.print("=");

    Serial.print(
        scores[i] * 100.0f,
        2);

    Serial.print("%");

    if (i < AS7341_COLOR_COUNT - 1) {
      Serial.print(", ");
    }
  }

  Serial.println();

  Serial.printf(
      "SECOND: %s (%.2f%%)\n",
      AS7341_COLOR_TEMPLATES[
          secondIndex].name,
      secondScore * 100.0f);

  Serial.printf(
      "SCORE_GAP: %.2f percentage points\n",
      scoreGap * 100.0f);

  if (!accepted) {
    lastAS7341ColorResult = "UNKNOWN";
    as7341UnknownCount++;

    Serial.println("COLOR: UNKNOWN");
    Serial.println("RGB_HEX: N/A");

    Serial.printf(
        "[AS7341 COLOR RESULT],class=UNKNOWN,"
        "best=%s,best_score=%.4f,"
        "second=%s,second_score=%.4f,"
        "gap=%.4f,brightness=%.4f\n",
        AS7341_COLOR_TEMPLATES[
            bestIndex].name,
        bestScore,
        AS7341_COLOR_TEMPLATES[
            secondIndex].name,
        secondScore,
        scoreGap,
        brightness);

    return;
  }

  lastAS7341ColorResult =
      AS7341_COLOR_TEMPLATES[
          bestIndex].name;

  Serial.print("COLOR: ");
  Serial.println(
      lastAS7341ColorResult);

  Serial.printf(
      "MATCH: %.2f%%\n",
      bestScore * 100.0f);

  Serial.print("RGB_HEX: #");

  Serial.printf(
      "%06lX\n",
      static_cast<unsigned long>(
          AS7341_COLOR_TEMPLATES[
              bestIndex].displayRgb));

  Serial.printf(
      "[AS7341 COLOR RESULT],class=%s,"
      "best_score=%.4f,"
      "second=%s,second_score=%.4f,"
      "gap=%.4f,brightness=%.4f\n",
      lastAS7341ColorResult,
      bestScore,
      AS7341_COLOR_TEMPLATES[
          secondIndex].name,
      secondScore,
      scoreGap,
      brightness);
}

// ============================================================================
// STEP 6C COMMAND MENU / DISPATCH
// ============================================================================

void printAS7341ColorMenu()
{
  Serial.println();
  Serial.println("AS7341 Step 6C commands:");
  Serial.println("  W = calibrate white reference");
  Serial.println("  V = verify white calibration");
  Serial.println("  M = measure + classify color card");
  Serial.println("  H = show this menu");
}

void handleAS7341ColorCommand()
{
  if (Serial.available() == 0) {
    return;
  }

  char command = Serial.read();

  if (command >= 'a' &&
      command <= 'z') {
    command -= 32;
  }

  if (command == '\r' ||
      command == '\n' ||
      command == ' ') {
    return;
  }

  switch (command) {
    case 'W':
      calibrateAS7341White();
      break;

    case 'V':
      verifyAS7341White();
      break;

    case 'M':
      classifyAS7341Card();
      break;

    case 'H':
      printAS7341ColorMenu();
      break;

    default:
      Serial.println(
          "[AS7341 COLOR] Unknown command. Enter H for help.");
      break;
  }
}

// ============================================================================
// A3. AS7341 SENSOR INIT
// ============================================================================
// Note:
// White reference calibration is deliberately NOT included here.
// That is baseline acquisition / processing and comes later.

bool setupAS7341()
{
  Serial.println();
  Serial.println("[A] Initializing AS7341...");

  if (!as7341.begin(AS7341_ADDRESS, &I2CBusB)) {
    Serial.println("AS7341: FAILED - address 0x39 not initialized on BUS B.");
    return false;
  }

  // Preserve configuration from the known-good AS7341 sketch.
  as7341.setATIME(AS7341_SENSOR_ATIME);
  as7341.setASTEP(AS7341_SENSOR_ASTEP);
  as7341.setGain(AS7341_GAIN_256X);

  Serial.println("AS7341: OK");
  Serial.println("  ATIME = 29");
  Serial.println("  ASTEP = 599");
  Serial.println("  Gain  = 256X");

  return true;
}



// ============================================================================
// BME688 BSEC STATE SAVE CALLBACK
// ============================================================================

void saveBME688BsecState(const uint8_t *stateBuffer, uint32_t length)
{
  if (length == 0 || length > BSEC_MAX_STATE_BLOB_SIZE) {
    return;
  }

  if (!bme688Preferences.begin("bsec3_aav1_354", false)) {
    return;
  }

  const size_t saved =
      bme688Preferences.putBytes("state",
                                 stateBuffer,
                                 length);

  bme688Preferences.end();

  Serial.printf("[BME TASK] Saved BSEC state: %u bytes\n",
                static_cast<unsigned>(saved));
}

// ============================================================================
// STEP 6D: STORE LATEST BME688 CLASSIFICATION RESULT
// ============================================================================
//
// Stable result policy:
//   AIR      -> stable
//   ALCOHOL  -> stable only after the original 3-scan confirmation
//
// Not stable:
//   WARMING_UP
//   UNCERTAIN
//   CONFIRMING_ALCOHOL
//
// No classification thresholds are changed here.

void updateBME688SharedResult(
    uint32_t rawGasIndex,
    float airProbability,
    float alcoholProbability,
    uint8_t accuracy,
    const char *instantClass,
    const char *decision,
    uint8_t currentAlcoholStreak,
    int32_t bsecStatus)
{
  if (!lockBMEResult()) {
    return;
  }

  bmeLastRawGasIndex =
      rawGasIndex;

  bmeLastAirProbability =
      airProbability;

  bmeLastAlcoholProbability =
      alcoholProbability;

  bmeLastAccuracy =
      accuracy;

  bmeLastAlcoholStreak =
      currentAlcoholStreak;

  bmeLastBsecStatus =
      bsecStatus;

  bmeLastResultMillis =
      millis();

  bmeResultUpdateCount++;

  snprintf(
      bmeLastInstantClass,
      sizeof(bmeLastInstantClass),
      "%s",
      instantClass);

  snprintf(
      bmeLastDecision,
      sizeof(bmeLastDecision),
      "%s",
      decision);

  bmeHasResult = true;

  bmeStableResultReady =
      strcmp(decision, "AIR") == 0 ||
      strcmp(decision, "ALCOHOL") == 0;

  unlockBMEResult();
}

// ============================================================================
// BME688 BSEC / AI-STUDIO OUTPUT HANDLER
// ============================================================================
// This is preserved from the validated standalone Air-vs-Alcohol sketch.
// It is used in Step 4C because bsec_iot_loop() needs its output callback.
//
// Step 4C is NOT yet integrating B Raw Read for the other three sensors.

void handleBME688Output(output_t *outputs,
                        bsec_library_return_t bsecStatus)
{
  if (!outputs->has_gas_estimate_1 ||
      !outputs->has_gas_estimate_2) {
    return;
  }

  const float air = outputs->gas_estimate_1;
  const float alcohol = outputs->gas_estimate_2;

  const uint8_t accuracy =
      min(outputs->gas_accuracy_1,
          outputs->gas_accuracy_2);

  const float best = max(air, alcohol);
  const float margin = fabsf(air - alcohol);

  const char *instantClass = "WARMING_UP";
  const char *decision = "WARMING_UP";

  if (accuracy >= 3) {
    if (best < MIN_CLASS_PROBABILITY ||
        margin < MIN_CLASS_MARGIN) {
      instantClass = "UNCERTAIN";
      decision = "UNCERTAIN";
      alcoholStreak = 0;
    }
    else if (alcohol > air) {
      instantClass = "ALCOHOL";

      if (alcoholStreak < ALCOHOL_CONFIRMATION_SCANS) {
        ++alcoholStreak;
      }

      decision =
          alcoholStreak >= ALCOHOL_CONFIRMATION_SCANS
              ? "ALCOHOL"
              : "CONFIRMING_ALCOHOL";
    }
    else {
      instantClass = "AIR";
      decision = "AIR";
      alcoholStreak = 0;
    }
  }
  else {
    alcoholStreak = 0;
  }

  // STEP 6D:
  // Store the complete application-level classification result so the
  // PoopSense main loop can consume it safely.
  updateBME688SharedResult(
      outputs->raw_gas_index,
      air,
      alcohol,
      accuracy,
      instantClass,
      decision,
      alcoholStreak,
      static_cast<int32_t>(bsecStatus));

  Serial.printf(
      "[BME DATA],%lld,%u,%.5f,%.5f,%u,%s,%s,%u,%d\n",
      outputs->timestamp / INT64_C(1000000),
      outputs->raw_gas_index,
      air,
      alcohol,
      accuracy,
      instantClass,
      decision,
      alcoholStreak,
      static_cast<int>(bsecStatus));
}

// ============================================================================
// BME688 FREERTOS RUNTIME TASK
// ============================================================================
//
// This is the core of Step 4C.
//
// bsec_iot_loop() still owns Bosch timing/heater scheduling exactly as before,
// but it now owns ONLY this FreeRTOS task, not Arduino's system setup().
//
// Arduino loop() remains available for the future PoopSense orchestrator.

void bme688RuntimeTask(void *parameter)
{
  (void)parameter;

  bme688RuntimeStarted = true;

  Serial.println();
  Serial.printf(
      "[BME TASK] Started on ESP32 core %d\n",
      xPortGetCoreID());

  Serial.println(
      "[BME TASK] bsec_iot_loop() is now running independently.");

  Serial.println(
      "[BME TASK] CSV: timestamp_ms,gas_index,air_probability,"
      "alcohol_probability,accuracy,instant_class,decision,"
      "alcohol_streak,bsec_status");

  bsec_iot_loop(
      bmeSleepMicroseconds,
      bmeTimestampMicroseconds,
      handleBME688Output,
      saveBME688BsecState,
      1000);

  // Bosch's loop should not return during normal operation.
  bme688RuntimeReturnedUnexpectedly = true;

  Serial.println(
      "[BME TASK] ERROR: bsec_iot_loop() returned unexpectedly.");

  vTaskDelete(nullptr);
}

bool startBME688RuntimeTask()
{
  if (bme688TaskHandle != nullptr) {
    Serial.println("BME688 runtime task: already created.");
    return true;
  }

  const BaseType_t result =
      xTaskCreatePinnedToCore(
          bme688RuntimeTask,
          "BME688_BSEC",
          BME688_TASK_STACK_BYTES,
          nullptr,
          BME688_TASK_PRIORITY,
          &bme688TaskHandle,
          BME688_TASK_CORE);

  if (result != pdPASS) {
    bme688TaskHandle = nullptr;
    Serial.println(
        "BME688 runtime task: FAILED to create FreeRTOS task.");
    return false;
  }

  Serial.println(
      "BME688 runtime task: CREATED");

  return true;
}

// ============================================================================
// A4. BME688 + BSEC + AI STUDIO SENSOR INIT
// ============================================================================
// CRITICAL DESIGN DECISION FOR STEP 4B:
//
// We DO call bsec_iot_init() here because it belongs to initialization.
//
// We DO NOT call bsec_iot_loop() inside this initialization function.
// Step 4C starts it AFTER all four A-init checks pass, inside a dedicated
// FreeRTOS task. This keeps Arduino loop() available for PoopSense.

bool setupBME688AOnly()
{
  Serial.println();
  Serial.println("[A] Initializing BME688 + BSEC + AI Studio config...");

  // Confirm that 0x77 still responds on BUS B before entering Bosch init.
  I2CBusB.beginTransmission(BME688_ADDRESS);
  if (I2CBusB.endTransmission() != 0) {
    Serial.println("BME688: FAILED - address 0x77 not detected on BUS B.");
    return false;
  }

  struct bme68x_dev device = {};

  device.intf = BME68X_I2C_INTF;
  device.read = bmeBusRead;
  device.write = bmeBusWrite;
  device.delay_us = bmeSleepMicroseconds;
  device.intf_ptr = &bme688I2CAddress;
  device.amb_temp = 25;

  // Preserve the memory setup used by the validated standalone BME sketch.
  allocateMemory(bsec_mem_block[0], 0);

  const return_values_init result =
      bsec_iot_init(
          SAMPLE_RATE,
          0.0f,
          bmeBusWrite,
          bmeBusRead,
          bmeSleepMicroseconds,
          loadBME688BsecState,
          loadBME688BsecConfig,
          device,
          0);

  if (result.bme68x_status != BME68X_OK ||
      result.bsec_status < BSEC_OK) {
    Serial.printf(
        "BME688: FAILED - BME68x=%d, BSEC=%d\n",
        result.bme68x_status,
        result.bsec_status);
    return false;
  }

  // Verify the same BSEC runtime version required by the validated sketch.
  bsec_version_t version = {};

  const bsec_library_return_t versionStatus =
      bsec_get_version(bsecInstance[0], &version);

  if (versionStatus != BSEC_OK ||
      version.major != 3 ||
      version.minor != 3 ||
      version.major_bugfix != 0 ||
      version.minor_bugfix != 0) {
    Serial.printf(
        "BME688: FAILED - unexpected BSEC runtime. status=%d, version=%u.%u.%u.%u\n",
        static_cast<int>(versionStatus),
        version.major,
        version.minor,
        version.major_bugfix,
        version.minor_bugfix);
    return false;
  }

  Serial.printf("BSEC library version %u.%u.%u.%u\n",
                version.major,
                version.minor,
                version.major_bugfix,
                version.minor_bugfix);

  Serial.println("BME688 hardware + BSEC + AI Studio config: OK");
  Serial.println("BME688 runtime loop: intentionally NOT started in Step 4B.");

  return true;
}

// ============================================================================
// C1/C2/C3. APDS9960 NEAR/FAR ALGORITHM
// ============================================================================
//
// Exact logic preserved from the validated standalone APDS sketch:
//
// FAR state:
//   proximity >= 40 for 3 consecutive valid samples -> NEAR
//
// NEAR state:
//   proximity <= 25 for 3 consecutive valid samples -> FAR
//
// Values between 26 and 39 are the hysteresis zone.
// In that zone the CURRENT state is preserved.
//
// This function consumes B-layer raw proximity only.
// It does not perform any additional I2C reads.

void updateAPDSDetectionState(uint8_t proximity)
{
  if (!apdsObjectDetected) {
    // Current state = FAR
    if (proximity >= PROXIMITY_NEAR_THRESHOLD) {
      if (apdsNearSampleCount < REQUIRED_CONSECUTIVE_SAMPLES) {
        apdsNearSampleCount++;
      }
    } else {
      apdsNearSampleCount = 0;
    }

    // far counter is irrelevant while current state is FAR
    apdsFarSampleCount = 0;

    if (apdsNearSampleCount >= REQUIRED_CONSECUTIVE_SAMPLES) {
      apdsObjectDetected = true;
      apdsNearSampleCount = 0;
      apdsFarSampleCount = 0;

      apdsNearTransitionCount++;
      apdsLastTransitionMs = millis();

      Serial.printf(
          "[APDS EVENT],FAR->NEAR,proximity=%u,time_ms=%lu,"
          "near_transitions=%lu\n",
          static_cast<unsigned>(proximity),
          static_cast<unsigned long>(apdsLastTransitionMs),
          static_cast<unsigned long>(apdsNearTransitionCount));
    }
  } else {
    // Current state = NEAR
    if (proximity <= PROXIMITY_FAR_THRESHOLD) {
      if (apdsFarSampleCount < REQUIRED_CONSECUTIVE_SAMPLES) {
        apdsFarSampleCount++;
      }
    } else {
      apdsFarSampleCount = 0;
    }

    // near counter is irrelevant while current state is NEAR
    apdsNearSampleCount = 0;

    if (apdsFarSampleCount >= REQUIRED_CONSECUTIVE_SAMPLES) {
      apdsObjectDetected = false;
      apdsNearSampleCount = 0;
      apdsFarSampleCount = 0;

      apdsFarTransitionCount++;
      apdsLastTransitionMs = millis();

      Serial.printf(
          "[APDS EVENT],NEAR->FAR,proximity=%u,time_ms=%lu,"
          "far_transitions=%lu\n",
          static_cast<unsigned>(proximity),
          static_cast<unsigned long>(apdsLastTransitionMs),
          static_cast<unsigned long>(apdsFarTransitionCount));
    }
  }
}

// ============================================================================
// STEP 5B TIMING FIX: APDS9960 DEDICATED SAMPLING TASK
// ============================================================================
//
// Why:
// Adafruit_MLX90640::getFrame() waits for the two MLX subpages needed to
// assemble a complete 32x24 frame. If APDS and MLX are both called from the
// same Arduino loop(), that blocking wait collapses APDS sampling toward the
// MLX full-frame rate.
//
// Fix:
// APDS is scheduled independently with vTaskDelayUntil() every 50 ms.
// I2CBusA is a single shared TwoWire object; Arduino-ESP32 serializes its
// individual transactions internally. Both devices use a fixed 400 kHz bus.
//
// No APDS C-classification is performed here.

void apdsSamplingTask(void *parameter)
{
  (void)parameter;

  apdsSamplingTaskStarted = true;

  Serial.println();
  Serial.printf(
      "[APDS TASK] Started on core %d, target interval=%lu ms (~%.1f Hz)\n",
      xPortGetCoreID(),
      static_cast<unsigned long>(APDS_RAW_SAMPLE_INTERVAL_MS),
      1000.0f / APDS_RAW_SAMPLE_INTERVAL_MS);

  TickType_t lastWakeTime = xTaskGetTickCount();
  const TickType_t periodTicks =
      pdMS_TO_TICKS(APDS_RAW_SAMPLE_INTERVAL_MS);

  for (;;) {
    uint8_t proximity = 0;

    if (lockBusA(pdMS_TO_TICKS(500))) {
      const bool ok = readAPDS9960Raw(proximity);
      unlockBusA();

      if (ok) {
        lastAPDSProximity = proximity;
        lastAPDSSampleValid = true;
        apdsLastValidSampleMs = millis();

        // STEP 6A: B raw -> C NEAR/FAR state algorithm
        updateAPDSDetectionState(proximity);
      }
    } else {
      apdsReadErrorCount++;
    }

    vTaskDelayUntil(&lastWakeTime, periodTicks);
  }
}

bool startAPDSSamplingTask()
{
  if (apdsSamplingTaskHandle != nullptr) {
    return true;
  }

  const BaseType_t result =
      xTaskCreatePinnedToCore(
          apdsSamplingTask,
          "APDS_20HZ",
          APDS_TASK_STACK_BYTES,
          nullptr,
          APDS_TASK_PRIORITY,
          &apdsSamplingTaskHandle,
          APDS_TASK_CORE);

  if (result != pdPASS) {
    apdsSamplingTaskHandle = nullptr;
    Serial.println(
        "APDS sampling task: FAILED to create.");
    return false;
  }

  Serial.println(
      "APDS sampling task: CREATED");

  return true;
}

// ============================================================================
// STEP 7A: REFRESH UNIFIED RESULT
// ============================================================================

void refreshPoopSenseUnifiedResult()
{
  bool localBMEHasResult = false;
  bool localBMEStable = false;
  float localAirProbability = 0.0f;
  float localAlcoholProbability = 0.0f;
  uint32_t localBMEUpdatedMs = 0;
  char localBMEDecision[24] = "NO_DATA";

  if (lockBMEResult()) {
    localBMEHasResult = bmeHasResult;
    localBMEStable = bmeStableResultReady;
    localAirProbability = bmeLastAirProbability;
    localAlcoholProbability = bmeLastAlcoholProbability;
    localBMEUpdatedMs = bmeLastResultMillis;

    snprintf(
        localBMEDecision,
        sizeof(localBMEDecision),
        "%s",
        bmeLastDecision);

    unlockBMEResult();
  }

  if (!lockPoopSenseResult()) return;

  // APDS9960
  snprintf(
      poopSenseResult.proximity,
      sizeof(poopSenseResult.proximity),
      "%s",
      apdsObjectDetected ? "NEAR" : "FAR");

  poopSenseResult.proximityRaw =
      static_cast<uint8_t>(lastAPDSProximity);

  poopSenseResult.proximityValid =
      lastAPDSSampleValid;

  poopSenseResult.proximityUpdatedMs =
      static_cast<uint32_t>(apdsLastValidSampleMs);

  // MLX90640
  snprintf(
      poopSenseResult.shape,
      sizeof(poopSenseResult.shape),
      "%s",
      lastMLXShapeValid
          ? lastMLXShapeClass
          : "none");

  poopSenseResult.shapeValid =
      mlxBackgroundReady &&
      lastMLXShapeValid &&
      strcmp(lastMLXShapeClass, "none") != 0;

  poopSenseResult.shapeUpdatedMs =
      mlxLastShapeResultMs;

  // AS7341
  snprintf(
      poopSenseResult.colorCategory,
      sizeof(poopSenseResult.colorCategory),
      "%s",
      lastAS7341ColorResult);

  poopSenseResult.colorConfidence =
      lastAS7341BestScore;

  poopSenseResult.colorConfidenceValid =
      as7341ClassificationCount > 0;

  poopSenseResult.colorValid =
      as7341WhiteReady &&
      as7341ClassificationCount > 0 &&
      strcmp(lastAS7341ColorResult, "UNKNOWN") != 0 &&
      strcmp(lastAS7341ColorResult, "NOT_CALIBRATED") != 0 &&
      strcmp(lastAS7341ColorResult, "READY") != 0;

  poopSenseResult.colorUpdatedMs =
      as7341LastClassificationMs;

  // BME688
  poopSenseResult.odorValid =
      localBMEHasResult;

  poopSenseResult.odorStable =
      localBMEStable;

  poopSenseResult.odorUpdatedMs =
      localBMEUpdatedMs;

  poopSenseResult.odorConfidenceValid = false;
  poopSenseResult.odorConfidence = 0.0f;

  snprintf(
      poopSenseResult.odorDeviation,
      sizeof(poopSenseResult.odorDeviation),
      "%s",
      "unknown");

  poopSenseResult.odorAbsoluteClass[0] = '\0';

  if (localBMEHasResult) {
    if (strcmp(localBMEDecision, "AIR") == 0) {
      snprintf(
          poopSenseResult.odorDeviation,
          sizeof(poopSenseResult.odorDeviation),
          "%s",
          "baseline_like");

      snprintf(
          poopSenseResult.odorAbsoluteClass,
          sizeof(poopSenseResult.odorAbsoluteClass),
          "%s",
          "AIR");

      poopSenseResult.odorConfidence =
          localAirProbability;

      poopSenseResult.odorConfidenceValid = true;

    } else if (strcmp(localBMEDecision, "ALCOHOL") == 0) {
      snprintf(
          poopSenseResult.odorDeviation,
          sizeof(poopSenseResult.odorDeviation),
          "%s",
          "abnormal");

      snprintf(
          poopSenseResult.odorAbsoluteClass,
          sizeof(poopSenseResult.odorAbsoluteClass),
          "%s",
          "ALCOHOL");

      poopSenseResult.odorConfidence =
          localAlcoholProbability;

      poopSenseResult.odorConfidenceValid = true;

    } else if (
        strcmp(localBMEDecision, "CONFIRMING_ALCOHOL") == 0) {

      snprintf(
          poopSenseResult.odorDeviation,
          sizeof(poopSenseResult.odorDeviation),
          "%s",
          "suspected");

      snprintf(
          poopSenseResult.odorAbsoluteClass,
          sizeof(poopSenseResult.odorAbsoluteClass),
          "%s",
          "ALCOHOL");

      poopSenseResult.odorConfidence =
          localAlcoholProbability;

      poopSenseResult.odorConfidenceValid = true;
    }
  }

  // Not yet exposed in current integrated BME pipeline.
  poopSenseResult.temperatureValid = false;
  poopSenseResult.temperatureC = 0.0f;
  poopSenseResult.humidityValid = false;
  poopSenseResult.humidityPct = 0.0f;

  unlockPoopSenseResult();
}

// ============================================================================
// STEP 7A: MACHINE-READABLE JSON LINE
// ============================================================================

void printPoopSenseUnifiedJson()
{
  refreshPoopSenseUnifiedResult();

  if (!lockPoopSenseResult()) return;

  const uint32_t now = millis();

  const uint32_t proximityAgeMs =
      poopSenseResult.proximityValid &&
      poopSenseResult.proximityUpdatedMs > 0
          ? now - poopSenseResult.proximityUpdatedMs
          : 0;

  const uint32_t shapeAgeMs =
      poopSenseResult.shapeUpdatedMs > 0
          ? now - poopSenseResult.shapeUpdatedMs
          : 0;

  const uint32_t colorAgeMs =
      poopSenseResult.colorUpdatedMs > 0
          ? now - poopSenseResult.colorUpdatedMs
          : 0;

  const uint32_t odorAgeMs =
      poopSenseResult.odorUpdatedMs > 0
          ? now - poopSenseResult.odorUpdatedMs
          : 0;

  char colorConfidenceJson[24] = "null";
  char odorConfidenceJson[24] = "null";
  char odorAbsoluteClassJson[32] = "null";
  char temperatureJson[24] = "null";
  char humidityJson[24] = "null";

  if (poopSenseResult.colorConfidenceValid) {
    snprintf(
        colorConfidenceJson,
        sizeof(colorConfidenceJson),
        "%.4f",
        poopSenseResult.colorConfidence);
  }

  if (poopSenseResult.odorConfidenceValid) {
    snprintf(
        odorConfidenceJson,
        sizeof(odorConfidenceJson),
        "%.4f",
        poopSenseResult.odorConfidence);
  }

  if (strlen(poopSenseResult.odorAbsoluteClass) > 0) {
    snprintf(
        odorAbsoluteClassJson,
        sizeof(odorAbsoluteClassJson),
        "\"%s\"",
        poopSenseResult.odorAbsoluteClass);
  }

  if (poopSenseResult.temperatureValid) {
    snprintf(
        temperatureJson,
        sizeof(temperatureJson),
        "%.2f",
        poopSenseResult.temperatureC);
  }

  if (poopSenseResult.humidityValid) {
    snprintf(
        humidityJson,
        sizeof(humidityJson),
        "%.2f",
        poopSenseResult.humidityPct);
  }

  static char jsonLine[1200];

  snprintf(
      jsonLine,
      sizeof(jsonLine),
      "{"
      "\"type\":\"sensor_result\","
      "\"uptime_ms\":%lu,"
      "\"proximity\":\"%s\","
      "\"proximity_raw\":%u,"
      "\"proximity_valid\":%s,"
      "\"proximity_age_ms\":%lu,"
      "\"shape\":\"%s\","
      "\"shape_valid\":%s,"
      "\"shape_age_ms\":%lu,"
      "\"color_category\":\"%s\","
      "\"color_confidence\":%s,"
      "\"color_valid\":%s,"
      "\"color_age_ms\":%lu,"
      "\"odor_deviation\":\"%s\","
      "\"odor_change_pct\":null,"
      "\"odor_absolute_class\":%s,"
      "\"odor_confidence\":%s,"
      "\"odor_valid\":%s,"
      "\"odor_stable\":%s,"
      "\"odor_age_ms\":%lu,"
      "\"temperature_c\":%s,"
      "\"humidity_pct\":%s,"
      "\"sample_quality\":\"pending\""
      "}",
      static_cast<unsigned long>(now),

      poopSenseResult.proximity,
      static_cast<unsigned>(poopSenseResult.proximityRaw),
      poopSenseResult.proximityValid ? "true" : "false",
      static_cast<unsigned long>(proximityAgeMs),

      poopSenseResult.shape,
      poopSenseResult.shapeValid ? "true" : "false",
      static_cast<unsigned long>(shapeAgeMs),

      poopSenseResult.colorCategory,
      colorConfidenceJson,
      poopSenseResult.colorValid ? "true" : "false",
      static_cast<unsigned long>(colorAgeMs),

      poopSenseResult.odorDeviation,
      odorAbsoluteClassJson,
      odorConfidenceJson,
      poopSenseResult.odorValid ? "true" : "false",
      poopSenseResult.odorStable ? "true" : "false",
      static_cast<unsigned long>(odorAgeMs),

      temperatureJson,
      humidityJson);

  Serial.print("POOPSENSE_JSON:");
  Serial.println(jsonLine);

  unlockPoopSenseResult();
}

// ============================================================================
// SYSTEM SETUP
// ============================================================================

void setup()
{
  Serial.begin(SERIAL_BAUD);
  delay(1500);

  Serial.println();
  Serial.println("==================================================");
  Serial.println("PoopSense Integrated V1 - Step 7A");
  Serial.println("Integrated Sensors + Shared BME Classification Result");
  Serial.println("Sensors: APDS9960 + MLX90640 + AS7341");
  Serial.println("==================================================");

  // --------------------------------------------------------------------------
  // SYSTEM / SHARED I2C INITIALIZATION
  // --------------------------------------------------------------------------

  Serial.println();
  Serial.println("Starting BUS A...");
  bool busAStarted = I2CBusA.begin(
      BUS_A_SDA,
      BUS_A_SCL,
      BUS_A_FREQUENCY
  );
  I2CBusA.setTimeOut(50);

  Serial.print("BUS A (GPIO6/GPIO7, 100 kHz): ");
  Serial.println(busAStarted ? "OK" : "FAILED");

  Serial.println("Starting BUS B...");
  bool busBStarted = I2CBusB.begin(
      BUS_B_SDA,
      BUS_B_SCL,
      BUS_B_FREQUENCY
  );
  I2CBusB.setTimeOut(50);

  Serial.print("BUS B (GPIO8/GPIO9, 100 kHz): ");
  Serial.println(busBStarted ? "OK" : "FAILED");

  // If either controller itself fails to start, do not attempt sensor init.
  if (!busAStarted || !busBStarted) {
    Serial.println();
    Serial.println("STEP 4C RESULT: FAIL - I2C bus initialization failed.");
    return;
  }

  // --------------------------------------------------------------------------
  // CREATE SHARED BUS MUTEXES
  // --------------------------------------------------------------------------

  busAMutex = xSemaphoreCreateMutex();

  if (busAMutex == nullptr) {
    Serial.println();
    Serial.println("STEP 5B V2 RESULT: FAIL - could not create BUS A mutex.");
    return;
  }

  Serial.println("BUS A sensor-level mutex: OK");

  busBMutex = xSemaphoreCreateMutex();

  if (busBMutex == nullptr) {
    Serial.println();
    Serial.println("STEP 4C RESULT: FAIL - could not create BUS B mutex.");
    return;
  }

  Serial.println("BUS B mutex: OK");

  // --------------------------------------------------------------------------
  // STEP 6D: CREATE BME SHARED-RESULT MUTEX
  // --------------------------------------------------------------------------

  bmeResultMutex = xSemaphoreCreateMutex();

  if (bmeResultMutex == nullptr) {
    Serial.println();
    Serial.println(
        "STEP 6D RESULT: FAIL - could not create BME result mutex.");
    return;
  }

  Serial.println("BME shared-result mutex: OK");

  poopSenseResultMutex = xSemaphoreCreateMutex();

  if (poopSenseResultMutex == nullptr) {
    Serial.println();
    Serial.println(
        "STEP 7A RESULT: FAIL - could not create unified result mutex.");
    return;
  }

  Serial.println("PoopSense unified-result mutex: OK");


  // --------------------------------------------------------------------------
  // SYSTEM DIAGNOSTIC: confirm the same physical topology proven in Step 3
  // --------------------------------------------------------------------------

  scanI2CBus(I2CBusA, "BUS A (GPIO6 / GPIO7)");
  scanI2CBus(I2CBusB, "BUS B (GPIO8 / GPIO9)");

  // --------------------------------------------------------------------------
  // A — SENSOR INIT
  // --------------------------------------------------------------------------

  bool apdsOK = setupAPDS9960();
  bool mlxOK = setupMLX90640();
  bool as7341OK = setupAS7341();
  bool bme688OK = setupBME688AOnly();

  // --------------------------------------------------------------------------
  // STEP 4 SUMMARY
  // --------------------------------------------------------------------------

  Serial.println();
  Serial.println("==================================================");
  Serial.println("STEP 4 SENSOR INIT SUMMARY");
  Serial.println("==================================================");

  Serial.print("APDS9960 : ");
  Serial.println(apdsOK ? "OK" : "FAILED");

  Serial.print("MLX90640 : ");
  Serial.println(mlxOK ? "OK" : "FAILED");

  Serial.print("AS7341   : ");
  Serial.println(as7341OK ? "OK" : "FAILED");

  Serial.print("BME688   : ");
  Serial.println(bme688OK ? "OK (A-only)" : "FAILED");

  Serial.println();

  if (apdsOK && mlxOK && as7341OK && bme688OK) {
    Serial.println("All 4 sensor A-init checks: PASS");

    // ------------------------------------------------------------------------
    // STEP 6B: MLX EMPTY-SCENE BACKGROUND BEFORE RUNTIME TASKS START
    // ------------------------------------------------------------------------
    // APDS/BME runtime tasks are intentionally started AFTER this calibration,
    // so the baseline acquisition gets exclusive startup access to BUS A.

    const bool mlxBackgroundOK =
        captureMLXBackground();

    if (mlxBackgroundOK) {
      Serial.println(
          "STEP 6B BACKGROUND: PASS");
    } else {
      Serial.println(
          "STEP 6B BACKGROUND: FAIL - shape processing will remain disabled.");
    }

    Serial.println();
    Serial.println("Starting Step 4C BME688 runtime task...");

    const bool bmeTaskOK = startBME688RuntimeTask();

    if (bmeTaskOK) {
      Serial.println();
      Serial.println("STEP 4C RESULT: STARTED");

      Serial.println();
      Serial.println("Starting Step 5B timing-fix APDS sampling task...");

      const bool apdsTaskOK = startAPDSSamplingTask();

      if (apdsTaskOK) {
        Serial.println(
            "STEP 5B TIMING FIX: APDS task started.");
        Serial.println(
            "Target APDS sampling rate: ~20 Hz independent of MLX getFrame().");
        Serial.println(
            "APDS C algorithm: FAR->NEAR >=40 x3; NEAR->FAR <=25 x3.");

        Serial.println();
        Serial.println(
            "AS7341 Step 6C color algorithm is ready.");
        Serial.println(
            "White calibration is required after every reset.");
        printAS7341ColorMenu();

        Serial.println();
        Serial.println(
            "BME688 Step 6D shared result is ready.");
        Serial.println(
            "Look for [BME RESULT] in the main-loop output.");
      } else {
        Serial.println(
            "STEP 5B TIMING FIX: FAIL - APDS task not created.");
      }
    } else {
      Serial.println(
          "STEP 4C RESULT: FAIL - BME688 runtime task was not created.");
    }
  } else {
    Serial.println(
        "STEP 4C RESULT: FAIL - one or more sensor initializations failed.");
    Serial.println(
        "BME688 runtime task was NOT started.");
  }
}

// ============================================================================
// SYSTEM LOOP - STEP 5C
// ============================================================================
//
// Runtime structure now:
//
//   APDS Task (BUS A, busAMutex)  -> raw proximity
//   Main Loop:
//       MLX90640 (BUS A, busAMutex) -> frame[768]
//       AS7341   (BUS B, busBMutex) -> raw[12] + spectrum[8]
//   BME Task (BUS B, busBMutex)   -> BSEC / AI Studio
//
// Step 6A APDS C-layer NEAR/FAR remains active.
// Step 6B MLX shape algorithm remains active.
// Step 6C restores the original AS7341 white-reference + color classifier.
// W/V/M/H commands are processed by the main loop.

void loop()
{
  // Step 6C manual color workflow (W/V/M/H).
  // Commands may briefly block the MAIN loop while averaging AS7341 frames.
  // APDS and BME688 continue in their independent FreeRTOS tasks.
  handleAS7341ColorCommand();

  const uint32_t now = millis();

  // --------------------------------------------------------------------------
  // MLX90640 B RAW THERMAL FRAME
  // --------------------------------------------------------------------------
  if (now - lastMLXSampleMs >= MLX_RAW_SAMPLE_INTERVAL_MS) {
    lastMLXSampleMs = now;

    if (readMLX90640RawFrame()) {
      lastMLXFrameValid = true;

      // STEP 6B: B raw frame -> C mask/features/classification
      processMLXShape();

      if (lastMLXShapeValid) {
        const uint8_t boxWidth =
            lastMLXShapeStats.largestArea
                ? lastMLXShapeStats.maxX -
                      lastMLXShapeStats.minX + 1
                : 0;

        const uint8_t boxHeight =
            lastMLXShapeStats.largestArea
                ? lastMLXShapeStats.maxY -
                      lastMLXShapeStats.minY + 1
                : 0;

        Serial.printf(
            "[MLX SHAPE],process=%lu,shape=%s,"
            "pixels=%u,components=%u,largest=%u,"
            "bbox_x=%u,bbox_y=%u,bbox_w=%u,bbox_h=%u,"
            "cx=%.2f,cy=%.2f,fill=%.2f,threshold=%.2f\n",
            static_cast<unsigned long>(
                mlxShapeProcessCount),
            lastMLXShapeClass,
            lastMLXShapeStats.totalPixels,
            lastMLXShapeStats.componentCount,
            lastMLXShapeStats.largestArea,
            lastMLXShapeStats.largestArea
                ? lastMLXShapeStats.minX
                : 0,
            lastMLXShapeStats.largestArea
                ? lastMLXShapeStats.minY
                : 0,
            boxWidth,
            boxHeight,
            lastMLXShapeStats.centerX,
            lastMLXShapeStats.centerY,
            lastMLXShapeStats.fillRatio,
            mlxDifferenceThresholdC);
      }
    }
  }

  // --------------------------------------------------------------------------
  // STEP 5C: AS7341 B RAW SPECTRUM
  // --------------------------------------------------------------------------
  if (now - lastAS7341SampleMs >= AS7341_RAW_SAMPLE_INTERVAL_MS) {
    lastAS7341SampleMs = now;

    if (readAS7341RawSpectrum()) {
      lastAS7341SampleValid = true;
    }
  }

  // --------------------------------------------------------------------------
  // APDS RAW DEBUG OUTPUT
  // --------------------------------------------------------------------------
  if (now - lastAPDSPrintMs >= APDS_RAW_PRINT_INTERVAL_MS) {
    lastAPDSPrintMs = now;

    if (lastAPDSSampleValid) {
      Serial.printf(
          "[APDS],proximity=%u,state=%s,near_count=%u,far_count=%u,"
          "valid_samples=%lu,read_errors=%lu\n",
          static_cast<unsigned>(lastAPDSProximity),
          apdsObjectDetected ? "NEAR" : "FAR",
          static_cast<unsigned>(apdsNearSampleCount),
          static_cast<unsigned>(apdsFarSampleCount),
          static_cast<unsigned long>(apdsValidSampleCount),
          static_cast<unsigned long>(apdsReadErrorCount));
    } else {
      Serial.printf(
          "[APDS],NO_VALID_SAMPLE,state=%s,valid_samples=%lu,read_errors=%lu\n",
          apdsObjectDetected ? "NEAR" : "FAR",
          static_cast<unsigned long>(apdsValidSampleCount),
          static_cast<unsigned long>(apdsReadErrorCount));
    }
  }

  // --------------------------------------------------------------------------
  // MLX RAW DEBUG OUTPUT
  // --------------------------------------------------------------------------
  if (now - lastMLXPrintMs >= MLX_RAW_PRINT_INTERVAL_MS) {
    lastMLXPrintMs = now;

    if (lastMLXFrameValid) {
      Serial.printf(
          "[MLX RAW],frame=%lu,pixels=%u,minC=%.2f,maxC=%.2f,avgC=%.2f,"
          "read_ms=%lu,max_read_ms=%lu,read_errors=%lu\n",
          static_cast<unsigned long>(mlxValidFrameCount),
          MLX_PIXEL_COUNT,
          lastMLXMinC,
          lastMLXMaxC,
          lastMLXAvgC,
          static_cast<unsigned long>(lastMLXReadDurationMs),
          static_cast<unsigned long>(maxMLXReadDurationMs),
          static_cast<unsigned long>(mlxFrameErrorCount));
    } else {
      Serial.printf(
          "[MLX RAW],NO_VALID_FRAME,frames=%lu,read_errors=%lu\n",
          static_cast<unsigned long>(mlxValidFrameCount),
          static_cast<unsigned long>(mlxFrameErrorCount));
    }
  }

  // --------------------------------------------------------------------------
  // AS7341 RAW DEBUG OUTPUT
  // --------------------------------------------------------------------------
  if (now - lastAS7341PrintMs >= AS7341_RAW_PRINT_INTERVAL_MS) {
    lastAS7341PrintMs = now;

    if (lastAS7341SampleValid) {
      Serial.printf(
          "[AS7341 RAW],sample=%lu,"
          "F1=%.0f,F2=%.0f,F3=%.0f,F4=%.0f,"
          "F5=%.0f,F6=%.0f,F7=%.0f,F8=%.0f,"
          "mutex_wait_ms=%lu,read_ms=%lu,"
          "read_errors=%lu,mutex_timeouts=%lu\n",
          static_cast<unsigned long>(as7341ValidSampleCount),
          lastAS7341Spectrum8[0],
          lastAS7341Spectrum8[1],
          lastAS7341Spectrum8[2],
          lastAS7341Spectrum8[3],
          lastAS7341Spectrum8[4],
          lastAS7341Spectrum8[5],
          lastAS7341Spectrum8[6],
          lastAS7341Spectrum8[7],
          static_cast<unsigned long>(lastAS7341MutexWaitMs),
          static_cast<unsigned long>(lastAS7341ReadDurationMs),
          static_cast<unsigned long>(as7341ReadErrorCount),
          static_cast<unsigned long>(as7341MutexTimeoutCount));
    } else {
      Serial.printf(
          "[AS7341 RAW],NO_VALID_SAMPLE,samples=%lu,"
          "read_errors=%lu,mutex_timeouts=%lu\n",
          static_cast<unsigned long>(as7341ValidSampleCount),
          static_cast<unsigned long>(as7341ReadErrorCount),
          static_cast<unsigned long>(as7341MutexTimeoutCount));
    }
  }

  // --------------------------------------------------------------------------
  // STEP 7A UNIFIED SENSOR RESULT
  // --------------------------------------------------------------------------

  static uint32_t lastPoopSenseResultPrintMs = 0;

  if (now - lastPoopSenseResultPrintMs >=
      POOPSENSE_RESULT_PRINT_INTERVAL_MS) {

    lastPoopSenseResultPrintMs = now;
    printPoopSenseUnifiedJson();
  }

  // --------------------------------------------------------------------------
  // EFFECTIVE-RATE / COEXISTENCE HEARTBEAT
  // --------------------------------------------------------------------------
  static uint32_t lastHeartbeatMs = 0;
  static uint32_t previousAPDSSampleCount = 0;
  static uint32_t previousMLXFrameCount = 0;
  static uint32_t previousAS7341SampleCount = 0;

  if (now - lastHeartbeatMs >= MAIN_LOOP_HEARTBEAT_MS) {
    const uint32_t elapsedMs =
        (lastHeartbeatMs == 0)
            ? MAIN_LOOP_HEARTBEAT_MS
            : now - lastHeartbeatMs;

    lastHeartbeatMs = now;

    const uint32_t currentAPDS =
        static_cast<uint32_t>(apdsValidSampleCount);

    const uint32_t currentMLX =
        mlxValidFrameCount;

    const uint32_t currentAS =
        as7341ValidSampleCount;

    const uint32_t apdsDelta =
        currentAPDS - previousAPDSSampleCount;

    const uint32_t mlxDelta =
        currentMLX - previousMLXFrameCount;

    const uint32_t asDelta =
        currentAS - previousAS7341SampleCount;

    previousAPDSSampleCount = currentAPDS;
    previousMLXFrameCount = currentMLX;
    previousAS7341SampleCount = currentAS;

    const float apdsHz =
        elapsedMs > 0
            ? (1000.0f * apdsDelta / elapsedMs)
            : 0.0f;

    const float mlxFps =
        elapsedMs > 0
            ? (1000.0f * mlxDelta / elapsedMs)
            : 0.0f;

    const float asHz =
        elapsedMs > 0
            ? (1000.0f * asDelta / elapsedMs)
            : 0.0f;

    // ------------------------------------------------------------------------
    // STEP 6D: THREAD-SAFE BME RESULT SNAPSHOT
    // ------------------------------------------------------------------------

    bool bmeSnapshotAvailable = false;
    bool bmeSnapshotStable = false;

    float bmeSnapshotAir = 0.0f;
    float bmeSnapshotAlcohol = 0.0f;

    uint8_t bmeSnapshotAccuracy = 0;
    uint8_t bmeSnapshotStreak = 0;

    uint32_t bmeSnapshotGasIndex = 0;
    uint32_t bmeSnapshotAgeMs = 0;
    uint32_t bmeSnapshotUpdates = 0;

    char bmeSnapshotDecision[24] = "NO_DATA";

    if (lockBMEResult()) {
      bmeSnapshotAvailable =
          bmeHasResult;

      bmeSnapshotStable =
          bmeStableResultReady;

      bmeSnapshotAir =
          bmeLastAirProbability;

      bmeSnapshotAlcohol =
          bmeLastAlcoholProbability;

      bmeSnapshotAccuracy =
          bmeLastAccuracy;

      bmeSnapshotStreak =
          bmeLastAlcoholStreak;

      bmeSnapshotGasIndex =
          bmeLastRawGasIndex;

      bmeSnapshotUpdates =
          bmeResultUpdateCount;

      if (bmeHasResult) {
        bmeSnapshotAgeMs =
            now - bmeLastResultMillis;
      }

      snprintf(
          bmeSnapshotDecision,
          sizeof(bmeSnapshotDecision),
          "%s",
          bmeLastDecision);

      unlockBMEResult();
    }

    if (bmeSnapshotAvailable) {
      Serial.printf(
          "[BME RESULT],decision=%s,stable=%s,"
          "air=%.4f,alcohol=%.4f,accuracy=%u,"
          "gas_index=%lu,alcohol_streak=%u,"
          "age_ms=%lu,updates=%lu\\n",
          bmeSnapshotDecision,
          bmeSnapshotStable ? "YES" : "NO",
          bmeSnapshotAir,
          bmeSnapshotAlcohol,
          static_cast<unsigned>(bmeSnapshotAccuracy),
          static_cast<unsigned long>(bmeSnapshotGasIndex),
          static_cast<unsigned>(bmeSnapshotStreak),
          static_cast<unsigned long>(bmeSnapshotAgeMs),
          static_cast<unsigned long>(bmeSnapshotUpdates));
    } else {
      Serial.println(
          "[BME RESULT],decision=NO_DATA,stable=NO");
    }

    Serial.printf(
        "[MAIN LOOP] alive | core=%d | uptime=%lu ms | "
        "BME_task=%s | APDS_task=%s | "
        "APDS_state=%s | APDS_rate=%.1fHz | APDS_errors=%lu | "
        "NEAR_events=%lu | FAR_events=%lu | "
        "MLX_rate=%.2ffps | MLX_errors=%lu | MLX_shape=%s | "
        "AS_rate=%.2fHz | AS_errors=%lu | AS_mutex_timeouts=%lu | "
        "AS_white=%s | AS_color=%s | "
        "BME_decision=%s | BME_stable=%s | free_heap=%u\n",
        xPortGetCoreID(),
        static_cast<unsigned long>(now),
        bme688RuntimeStarted ? "YES" : "NO",
        apdsSamplingTaskStarted ? "YES" : "NO",
        apdsObjectDetected ? "NEAR" : "FAR",
        apdsHz,
        static_cast<unsigned long>(apdsReadErrorCount),
        static_cast<unsigned long>(apdsNearTransitionCount),
        static_cast<unsigned long>(apdsFarTransitionCount),
        mlxFps,
        static_cast<unsigned long>(mlxFrameErrorCount),
        lastMLXShapeValid ? lastMLXShapeClass : "NO_BG",
        asHz,
        static_cast<unsigned long>(as7341ReadErrorCount),
        static_cast<unsigned long>(as7341MutexTimeoutCount),
        as7341WhiteReady ? "YES" : "NO",
        lastAS7341ColorResult,
        bmeSnapshotAvailable
            ? bmeSnapshotDecision
            : "NO_DATA",
        bmeSnapshotStable
            ? "YES"
            : "NO",
        static_cast<unsigned>(ESP.getFreeHeap()));
  }

  delay(5);
}
