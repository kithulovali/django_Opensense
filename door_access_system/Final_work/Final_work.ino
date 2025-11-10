#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define CAMERA_MODEL_AI_THINKER
#include "camera_pins.h"

// Enable device-driven verification (motor moves only after OPEN)
#define ENABLE_BACKGROUND_RECOG 1

// ===== WiFi =====
const char* ssid     = "HECA Wireless";
const char* password = "Heca202five";

// ===== Django endpoint =====
static const char* VERIFY_BASE = "http://192.168.0.121:8000/api/verify_open/";

// ===== Motor pins (ULN2003 + 28BYJ-48) =====
#define IN1_PIN 14
#define IN2_PIN 13
#define IN3_PIN 12
#define IN4_PIN 15

// ===== Behavior =====
static const uint32_t RECOG_INTERVAL_MS = 5000;
static const uint32_t COOLDOWN_MS       = 10000;

// Shared with HTTP handlers
SemaphoreHandle_t camera_mutex = nullptr;

// Dynamic username (optional)
Preferences prefs;
String g_username;
volatile bool g_motorBusy = false;

static bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = FRAMESIZE_QVGA;   // 320x240
    config.jpeg_quality = 15;
    config.fb_count     = 3;
  } else {
    config.frame_size   = FRAMESIZE_QQVGA;
    config.jpeg_quality = 15;
    config.fb_count     = 1;
  }
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode   = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed 0x%x\n", err);
    return false;
  }
  return true;
}

// ===== Motor control (CW 5s -> stop 2s -> CCW 5s -> stop) =====
static inline void motorStop() {
  digitalWrite(IN1_PIN, LOW);
  digitalWrite(IN2_PIN, LOW);
  digitalWrite(IN3_PIN, LOW);
  digitalWrite(IN4_PIN, LOW);
}
static inline void step1(){ digitalWrite(IN1_PIN, HIGH); digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, LOW); }
static inline void step2(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, HIGH); digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, LOW); }
static inline void step3(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, HIGH); digitalWrite(IN4_PIN, LOW); }
static inline void step4(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, HIGH); }

static inline void step4_ccw(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, HIGH); }
static inline void step3_ccw(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, HIGH); digitalWrite(IN4_PIN, LOW); }
static inline void step2_ccw(){ digitalWrite(IN1_PIN, LOW);  digitalWrite(IN2_PIN, HIGH); digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, LOW); }
static inline void step1_ccw(){ digitalWrite(IN1_PIN, HIGH); digitalWrite(IN2_PIN, LOW);  digitalWrite(IN3_PIN, LOW);  digitalWrite(IN4_PIN, LOW); }

static void motorStepSequenceCW(uint32_t duration_ms) {
  const uint32_t steps = 100;
  uint32_t stepDelay = duration_ms / (steps * 4);
  if (stepDelay == 0) stepDelay = 1;
  for (uint32_t i = 0; i < steps; i++) {
    step1(); delay(stepDelay);
    step2(); delay(stepDelay);
    step3(); delay(stepDelay);
    step4(); delay(stepDelay);
  }
  motorStop();
}
static void motorStepSequenceCCW(uint32_t duration_ms) {
  const uint32_t steps = 100;
  uint32_t stepDelay = duration_ms / (steps * 4);
  if (stepDelay == 0) stepDelay = 1;
  for (uint32_t i = 0; i < steps; i++) {
    step4_ccw(); delay(stepDelay);
    step3_ccw(); delay(stepDelay);
    step2_ccw(); delay(stepDelay);
    step1_ccw(); delay(stepDelay);
  }
  motorStop();
}

// Made non-static so app_httpd.cpp can call it
void motorOpenCloseCycle() {
  g_motorBusy = true;
  motorStepSequenceCW(7000);
  motorStop(); delay(5000);
  motorStepSequenceCCW(7000);
  motorStop();
  g_motorBusy = false;
}

// ===== Background face verification (OPEN => motor cycle) =====
#if ENABLE_BACKGROUND_RECOG
static bool parseVerifiedFromBody(const String& body) {
  int i = body.indexOf("\"verified\"");
  if (i < 0) return false;
  int colon = body.indexOf(':', i);
  if (colon < 0) return false;
  int j = colon + 1;
  while (j < (int)body.length() && (body[j]==' '||body[j]=='\t'||body[j]=='\n'||body[j]=='\r')) j++;
  if (j >= (int)body.length()) return false;
  return (body.startsWith("true", j) || body.startsWith("1", j));
}

static bool postFrameForVerification(camera_fb_t* fb) {
  if (WiFi.status() != WL_CONNECTED) return false;

  String url = String(VERIFY_BASE);

  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(7000);

  if (!http.begin(url)) return false;
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-ID", WiFi.macAddress());

  int code = http.sendRequest("POST", fb->buf, fb->len);
  if (code <= 0) { http.end(); return false; }

  String body = http.getString();
  http.end();

  if (code != 200) return false;
  return parseVerifiedFromBody(body);
}

static void recognitionTask(void* pv) {
  uint32_t lastOpenAt = 0;
  bool prevVerified = false; // edge-detect to avoid repeated cycles on sustained 'verified'

  for (;;) {
    if (millis() - lastOpenAt < COOLDOWN_MS) { vTaskDelay(pdMS_TO_TICKS(250)); continue; }

    camera_fb_t *fb = nullptr;

    if (camera_mutex && xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(1800))) {
      for (int r = 0; r < 4 && !fb; r++) {
        fb = esp_camera_fb_get();
        if (!fb) vTaskDelay(pdMS_TO_TICKS(60));
      }
      xSemaphoreGive(camera_mutex);
    }
    if (!fb) { vTaskDelay(pdMS_TO_TICKS(800)); continue; }

    bool verified = postFrameForVerification(fb);

    if (camera_mutex && xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(600))) {
      esp_camera_fb_return(fb);
      xSemaphoreGive(camera_mutex);
    } else {
      esp_camera_fb_return(fb);
    }

    // Trigger only on rising edge of 'verified' and respecting cooldown
    if (verified && !prevVerified && (millis() - lastOpenAt >= COOLDOWN_MS) && !g_motorBusy) {
      motorOpenCloseCycle();
      lastOpenAt = millis();
    }

    prevVerified = verified;

    vTaskDelay(pdMS_TO_TICKS(RECOG_INTERVAL_MS));
  }
}
#endif

extern "C" void startCameraServer(); // in app_httpd.cpp

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  delay(200);

  pinMode(IN1_PIN, OUTPUT);
  pinMode(IN2_PIN, OUTPUT);
  pinMode(IN3_PIN, OUTPUT);
  pinMode(IN4_PIN, OUTPUT);
  motorStop();

  initCamera();
  camera_mutex = xSemaphoreCreateMutex();

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid, password);
  for (int i = 0; WiFi.status() != WL_CONNECTED && i < 40; i++) { delay(250); Serial.print("."); }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) { Serial.print("IP: "); Serial.println(WiFi.localIP()); }

  prefs.begin("door", false);
  g_username = prefs.getString("user", "");

  startCameraServer();

#if ENABLE_BACKGROUND_RECOG
  xTaskCreatePinnedToCore(recognitionTask, "recognition", 8192, nullptr, 1, nullptr, 1);
#endif
}

void loop() { delay(1000); }