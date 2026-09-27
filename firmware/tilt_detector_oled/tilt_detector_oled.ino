/*
 * Landsafe AI — Animated Intro + Sensor Display
 * Hardware: ESP32 + MPU-6500 + H9 Moisture + 0.96" SSD1306 OLED
 *
 * Wiring:
 *   MPU-6500:  SDA→GPIO21, SCL→GPIO22, VCC→3.3V, GND→GND
 *   Moisture:  A0→GPIO34, VCC→3.3V, GND→GND
 *   OLED:      SDA→GPIO21, SCL→GPIO22, VDD→3.3V(or 5V), GND→GND
 *
 * Libraries: Adafruit SSD1306, Adafruit GFX Library
 */

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ===== CONFIGURATION =====
const char* WIFI_SSID = "Redmi Note 6 Pro";
const char* WIFI_PASS = "";
const char* SERVER_URL = "https://landsafe-ai.onrender.com/api/tilt";
const char* DEVICE_ID = "esp32-ner-001";

// ===== OLED =====
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ===== MPU-6500 =====
#define MPU_ADDR 0x68
#define SENSITIVITY_4G 8192.0

// ===== PINS =====
#define MOISTURE_PIN 34
#define LED_PIN 2

// ===== THRESHOLDS =====
#define TILT_WARN 10.0
#define TILT_DANGER 60.0
#define DEAD_ZONE 2.0
#define MOISTURE_WARN 60.0
#define MOISTURE_DANGER 80.0

// ===== AccelData =====
struct AccelData { float x; float y; float z; };

// ===== STATE =====
float tilt = 0.0;
float moisturePct = 0.0;
float rawAx = 0, rawAy = 0, rawAz = 0;
String status = "safe";
unsigned long lastSend = 0;
unsigned long lastDisplayUpdate = 0;
int displayPage = 0;
bool introDone = false;
float refX = 0, refY = 0, refZ = 0;

// ===== I2C HELPERS =====
void writeRegister(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

uint8_t readRegister(uint8_t reg) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, (uint8_t)1);
  return Wire.read();
}

AccelData readAccelOnce() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, (uint8_t)6);
  int16_t rawX = (Wire.read() << 8) | Wire.read();
  int16_t rawY = (Wire.read() << 8) | Wire.read();
  int16_t rawZ = (Wire.read() << 8) | Wire.read();
  AccelData d;
  d.x = rawX / SENSITIVITY_4G;
  d.y = rawY / SENSITIVITY_4G;
  d.z = rawZ / SENSITIVITY_4G;
  return d;
}

float medianOf9(float *arr) {
  float temp[9];
  for (int i = 0; i < 9; i++) temp[i] = arr[i];
  for (int i = 1; i < 9; i++) {
    float key = temp[i];
    int j = i - 1;
    while (j >= 0 && temp[j] > key) { temp[j+1] = temp[j]; j--; }
    temp[j+1] = key;
  }
  return temp[4];
}

AccelData readAccelFiltered() {
  float rawX[9], rawY[9], rawZ[9];
  for (int i = 0; i < 9; i++) {
    AccelData a = readAccelOnce();
    rawX[i] = a.x; rawY[i] = a.y; rawZ[i] = a.z;
    delay(2);
  }
  AccelData d;
  d.x = medianOf9(rawX);
  d.y = medianOf9(rawY);
  d.z = medianOf9(rawZ);
  return d;
}

float readMoisture() {
  long sum = 0;
  for (int i = 0; i < 10; i++) {
    sum += analogRead(MOISTURE_PIN);
    delay(5);
  }
  float raw = sum / 10.0;
  float pct = map((long)raw, 3200, 1400, 0, 100);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

bool initMPU() {
  uint8_t id = readRegister(0x75);
  Serial.printf("WHO_AM_I: 0x%02X\n", id);
  if (id != 0x68 && id != 0x70) {
    Serial.println("MPU not found!");
    return false;
  }
  writeRegister(0x6B, 0x80); delay(100);
  writeRegister(0x6B, 0x00); delay(10);
  writeRegister(0x19, 0x09);
  writeRegister(0x1A, 0x03);
  writeRegister(0x1B, 0x00);
  writeRegister(0x1C, 0x08);
  Serial.println("MPU-6500 ready");
  return true;
}

void calibrateSensor() {
  Serial.println("\n=== CALIBRATION ===");
  Serial.println("Keep sensor FLAT and STILL!");
  delay(3000);
  for (int i = 0; i < 50; i++) { readAccelOnce(); delay(10); }
  float sx = 0, sy = 0, sz = 0;
  for (int i = 0; i < 500; i++) {
    AccelData a = readAccelOnce();
    sx += a.x; sy += a.y; sz += a.z;
    delay(4);
  }
  refX = sx / 500.0;
  refY = sy / 500.0;
  refZ = sz / 500.0;
  Serial.printf("Calibration done: X=%.4f Y=%.4f Z=%.4f\n\n", refX, refY, refZ);
}

// ============================================================
//  ANIMATED INTRO SEQUENCE
// ============================================================

// --- LITTLE MOUNTAIN LOGO (drawn procedurally) ---
void drawMountain(int cx, int baseY, int w, int h) {
  // Main peak
  display.fillTriangle(cx, baseY - h, cx - w/2, baseY, cx + w/2, baseY, SSD1306_WHITE);
  // Snow cap
  display.fillTriangle(cx, baseY - h, cx - w/6, baseY - h + h/3, cx + w/6, baseY - h + h/3, SSD1306_BLACK);
  display.drawTriangle(cx, baseY - h, cx - w/6, baseY - h + h/3, cx + w/6, baseY - h + h/3, SSD1306_WHITE);
}

// --- Scene 1: LANDSLIDE (falling rocks) ---
void animateLandslide() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(30, 0);
  display.print(F("LANDSLIDE"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // Mountain outline
  display.fillTriangle(64, 18, 10, 55, 118, 55, SSD1306_WHITE);
  display.fillTriangle(64, 20, 15, 54, 113, 54, SSD1306_BLACK); // hollow

  // Animate falling rocks
  for (int frame = 0; frame < 8; frame++) {
    display.fillTriangle(64, 20, 15, 54, 113, 54, SSD1306_BLACK);

    // Redraw mountain
    display.drawTriangle(64, 18, 10, 55, 118, 55, SSD1306_WHITE);

    // Falling rocks at different positions
    for (int r = 0; r <= frame; r++) {
      int rx = 55 + r * 5 - frame * 2;
      int ry = 22 + frame * 4 + r * 3;
      if (ry > 54) ry = 54;
      display.fillCircle(rx, ry, 2, SSD1306_WHITE);
      // Debris trail
      if (r < frame) {
        display.drawPixel(rx + 3, ry - 2, SSD1306_WHITE);
        display.drawPixel(rx - 2, ry - 1, SSD1306_WHITE);
      }
    }

    // Crumble line at base
    for (int x = 10; x < 118; x += 4) {
      display.drawPixel(x, 55 - frame, SSD1306_WHITE);
    }

    display.display();
    delay(150);
  }

  // Impact flash
  display.fillRect(0, 12, 128, 52, SSD1306_WHITE);
  display.display();
  delay(80);
  display.fillRect(0, 12, 128, 52, SSD1306_BLACK);
  display.display();
  delay(50);

  // Final shake frames
  for (int s = 0; s < 3; s++) {
    display.fillTriangle(64 + (s%2 ? 3 : -3), 18, 10, 55, 118, 55, SSD1306_WHITE);
    display.drawTriangle(64 + (s%2 ? 3 : -3), 18, 10, 55, 118, 55, SSD1306_BLACK);
    display.setCursor(15, 56);
    display.print(F("Slope failure detected"));
    display.display();
    delay(120);
  }
}

// --- Scene 2: FLOOD (rising water waves) ---
void animateFlood() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(38, 0);
  display.print(F("FLOOD"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // Small houses
  display.fillRect(20, 30, 12, 12, SSD1306_WHITE);
  display.fillTriangle(20, 30, 26, 22, 32, 30, SSD1306_WHITE);
  display.fillRect(60, 32, 12, 10, SSD1306_WHITE);
  display.fillTriangle(60, 32, 66, 24, 72, 32, SSD1306_WHITE);
  display.fillRect(100, 28, 12, 14, SSD1306_WHITE);
  display.fillTriangle(100, 28, 106, 20, 112, 28, SSD1306_WHITE);

  // Animate rising water
  for (int level = 0; level < 6; level++) {
    int waterY = 54 - level * 4;

    // Draw waves
    for (int x = 0; x < 128; x += 2) {
      int waveY = waterY + ((x + level * 10) % 6 < 3 ? 0 : -1);
      display.drawPixel(x, waveY, SSD1306_WHITE);
      display.drawPixel(x, waveY + 1, SSD1306_WHITE);
    }

    // Fill water below wave
    display.fillRect(0, waterY + 1, 128, 64 - waterY, SSD1306_WHITE);

    // Redraw houses (so water goes "around" them)
    display.fillRect(20, 30, 12, 12, SSD1306_BLACK);
    display.fillRect(60, 32, 12, 10, SSD1306_BLACK);
    display.fillRect(100, 28, 12, 14, SSD1306_BLACK);

    // Only draw houses above water
    if (waterY > 30) {
      display.fillRect(20, 30, 12, waterY - 30, SSD1306_WHITE);
      display.fillRect(60, 32, 12, waterY - 32, SSD1306_WHITE);
      display.fillRect(100, 28, 12, waterY - 28, SSD1306_WHITE);
    }

    display.display();
    delay(200);
  }

  // Final: everything underwater
  display.setCursor(25, 56);
  display.print(F("Water level critical"));
  display.display();
  delay(300);
}

// --- Scene 3: EARTHQUAKE (shaking buildings) ---
void animateEarthquake() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(28, 0);
  display.print(F("EARTHQUAKE"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  // Ground line
  display.drawLine(0, 55, 128, 55, SSD1306_WHITE);

  // Buildings
  int bx[] = {15, 40, 65, 90, 110};
  int bw[] = {12, 16, 10, 14, 10};
  int bh[] = {25, 32, 20, 28, 18};

  for (int frame = 0; frame < 10; frame++) {
    display.clearDisplay();
    display.setCursor(28, 0);
    display.print(F("EARTHQUAKE"));
    display.drawLine(0, 10, 127, 10, SSD1306_WHITE);
    display.drawLine(0, 55, 128, 55, SSD1306_WHITE);

    // Shake intensity increases
    int shake = (frame < 5) ? frame : (10 - frame);
    int dx = (frame % 2 == 0) ? shake : -shake;

    for (int b = 0; b < 5; b++) {
      int x = bx[b] + dx;
      int y = 55 - bh[b];
      // Building body
      display.fillRect(x, y, bw[b], bh[b], SSD1306_WHITE);
      // Windows (black dots)
      for (int wy = y + 3; wy < 53; wy += 5) {
        for (int wx = x + 2; wx < x + bw[b] - 2; wx += 4) {
          display.drawPixel(wx, wy, SSD1306_BLACK);
        }
      }
      // Cracks if shaking hard
      if (shake >= 3) {
        display.drawLine(x + bw[b]/2, y, x + bw[b]/2 + shake, y + bh[b]/3, SSD1306_BLACK);
      }
    }

    // Seismic waves at bottom
    for (int x = 0; x < 128; x += 2) {
      int sy = 58 + ((x + frame * 5) % 6 < 3 ? 0 : 1);
      display.drawPixel(x, sy, SSD1306_WHITE);
      display.drawPixel(x, sy + 1, SSD1306_WHITE);
    }

    display.display();
    delay(100);
  }

  // Final: crack down center
  display.setCursor(20, 56);
  display.print(F("Seismic activity!"));
  display.display();
  delay(300);
}

// --- Scene 4: LANDSAFE AI LOGO REVEAL ---
void animateLogoReveal() {
  display.clearDisplay();
  display.display();
  delay(200);

  // Diamond/radar scan effect
  for (int r = 0; r < 40; r += 3) {
    display.clearDisplay();
    display.drawCircle(64, 32, r, SSD1306_WHITE);
    display.drawCircle(64, 32, r - 2, SSD1306_WHITE);
    display.display();
    delay(30);
  }

  display.clearDisplay();
  display.display();
  delay(100);

  // Draw mountain logo centered
  drawMountain(64, 38, 40, 20);

  // Title fades in letter by letter
  display.display();
  delay(200);

  const char* title = "LANDSAFE AI";
  int len = strlen(title);
  for (int i = 0; i <= len; i++) {
    display.clearDisplay();
    drawMountain(64, 38, 40, 20);
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);

    // Title centered
    int tx = (128 - len * 6) / 2;
    for (int c = 0; c < i; c++) {
      display.setCursor(tx + c * 6, 42);
      display.print(title[c]);
    }
    display.display();
    delay(50);
  }

  // Subtitle
  display.setCursor(32, 54);
  display.print(F("by scapegoats"));
  display.display();
  delay(500);

  // Flash
  display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
  display.display();
  delay(50);
  display.clearDisplay();
  display.drawBitmap(48, 2, logo_bmp, 32, 32, SSD1306_WHITE);
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(20, 38);
  display.print(F("LANDSAFE AI"));
  display.setCursor(28, 50);
  display.print(F("by scapegoats"));
  display.display();
  delay(1000);
}

// --- Scene 5: System Info ---
void showSystemInfo() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 5);
  display.print(F("AI-Powered Landslide"));
  display.setCursor(10, 18);
  display.print(F("Monitoring System"));
  display.drawLine(10, 30, 118, 30, SSD1306_WHITE);
  display.setCursor(10, 38);
  display.print(F("NER Region Early"));
  display.setCursor(10, 48);
  display.print(F("Warning Platform"));

  // Loading dots
  for (int d = 0; d < 6; d++) {
    display.setCursor(10 + d * 16, 58);
    display.print(F("."));
    display.display();
    delay(200);
  }
  delay(500);
}

// ===== MAIN INTRO SEQUENCE =====
void runIntro() {
  // Scene 1: Landslide
  animateLandslide();
  delay(300);

  // Scene 2: Flood
  animateFlood();
  delay(300);

  // Scene 3: Earthquake
  animateEarthquake();
  delay(300);

  // Scene 4: Logo reveal
  animateLogoReveal();

  // Scene 5: System info
  showSystemInfo();
}

// ===== WIFI CONNECT =====
void connectWiFi() {
  display.clearDisplay();
  display.setCursor(10, 10);
  display.print(F("Connecting WiFi..."));
  display.setCursor(10, 24);
  display.print(WIFI_SSID);
  display.display();

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  display.clearDisplay();
  display.setCursor(10, 20);
  if (WiFi.status() == WL_CONNECTED) {
    display.print(F("WiFi Connected!"));
    display.setCursor(10, 35);
    display.print(WiFi.localIP());
    Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    display.print(F("WiFi Failed!"));
    display.setCursor(10, 35);
    display.print(F("Check credentials"));
  }
  display.display();
  delay(1500);
}

// ===== LOGO BITMAP (for final reveal) =====
static const unsigned char PROGMEM logo_bmp[] = {
  0x00,0x00,0x03,0xC0,0x00,0x00,0x00,0x00,
  0x00,0x00,0x0F,0xF0,0x00,0x00,0x00,0x00,
  0x00,0x01,0xFF,0xFF,0x80,0x00,0x00,0x00,
  0x00,0x07,0xFF,0xFF,0xE0,0x00,0x00,0x00,
  0x00,0x1F,0xFF,0xFF,0xF8,0x00,0x00,0x00,
  0x00,0x7F,0xC0,0x03,0xFE,0x00,0x00,0x00,
  0x01,0xF8,0x00,0x00,0x1F,0x80,0x00,0x00,
  0x07,0xE0,0x00,0x00,0x07,0xE0,0x00,0x00,
  0x1F,0x00,0x00,0x00,0x01,0xF8,0x00,0x00,
  0x7C,0x00,0x00,0x00,0x00,0x7E,0x00,0x00,
  0xF0,0x00,0x00,0x00,0x00,0x1F,0x00,0x00,
  0xFF,0xFF,0xFF,0xFF,0xFF,0xFF,0x00,0x00,
  0x7F,0xFF,0xFF,0xFF,0xFF,0xFE,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
  0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00
};

// ===== OLED PAGES =====
void updateDisplay() {
  unsigned long now = millis();
  if (now - lastDisplayUpdate < 500) return;
  lastDisplayUpdate = now;

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.print(F("LANDSAFE AI"));
  display.setCursor(95, 0);
  display.print(WiFi.status() == WL_CONNECTED ? F("[OK]") : F("[--]"));
  display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

  switch (displayPage) {
    case 0: drawTiltPage(); break;
    case 1: drawMoisturePage(); break;
    case 2: drawStatusPage(); break;
  }

  display.drawLine(0, 53, 127, 53, SSD1306_WHITE);
  display.setCursor(2, 55);
  if (status == "danger") {
    display.print((millis() / 500) % 2 ? F("! DANGER !") : F("          "));
  } else if (status == "warning") {
    display.print(F("* WARNING *"));
  } else {
    display.print(F("  STATUS OK"));
  }

  display.display();

  static unsigned long lastPageChange = 0;
  if (now - lastPageChange > 3000) {
    lastPageChange = now;
    displayPage = (displayPage + 1) % 3;
  }
}

void drawTiltPage() {
  display.setTextSize(2);
  display.setCursor(10, 18);
  display.print(tilt, 1);
  display.setTextSize(1);
  display.setCursor(85, 24);
  display.print(F("deg"));

  int barW = map((int)(tilt < 90.0f ? tilt : 90.0f), 0, 90, 0, 110);
  display.drawRect(10, 38, 112, 8, SSD1306_WHITE);
  display.fillRect(10, 38, barW, 8, SSD1306_WHITE);
  display.setCursor(10, 48);
  display.print(F("0"));
  display.setCursor(55, 48);
  display.print(F("45"));
  display.setCursor(105, 48);
  display.print(F("90"));
}

void drawMoisturePage() {
  display.setTextSize(2);
  display.setCursor(10, 18);
  display.print((int)moisturePct);
  display.setTextSize(1);
  display.setCursor(55, 24);
  display.print(F("%%"));

  int barW = map((int)moisturePct, 0, 100, 0, 110);
  display.drawRect(10, 38, 112, 8, SSD1306_WHITE);
  display.fillRect(10, 38, barW, 8, SSD1306_WHITE);
  display.setCursor(10, 48);
  display.print(F("Dry"));
  display.setCursor(50, 48);
  display.print(F("50%%"));
  display.setCursor(100, 48);
  display.print(F("Wet"));
}

void drawStatusPage() {
  display.setCursor(0, 15);
  display.print(F("Tilt:   "));
  display.print(tilt, 1);
  display.print(F(" deg"));
  display.setCursor(0, 28);
  display.print(F("Moist:  "));
  display.print((int)moisturePct);
  display.print(F(" %%"));
  display.setCursor(0, 41);
  display.print(F("Status: "));
  if (status == "danger") display.print(F("DANGER!"));
  else if (status == "warning") display.print(F("WARNING"));
  else display.print(F("SAFE"));
}

// ===== SEND TO SERVER =====
void sendToServer() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(3000);

  String json = "{\"device_id\":\"" + String(DEVICE_ID) + "\","
                "\"tilt\":" + String(tilt, 2) + ","
                "\"moisture\":" + String(moisturePct, 1) + ","
                "\"status\":\"" + status + "\"}";

  int code = http.POST(json);
  if (code > 0) Serial.printf("POST -> %d  T:%.1f M:%.0f [%s]\n", code, tilt, moisturePct, status.c_str());
  else Serial.printf("POST failed: %d\n", code);
  http.end();
}

// ===== SETUP =====
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Landsafe AI ===\n");

  pinMode(LED_PIN, OUTPUT);
  pinMode(MOISTURE_PIN, INPUT);
  Wire.begin(21, 22);
  Wire.setClock(400000);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed!");
    while (true);
  }
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  // Run animated intro!
  runIntro();

  if (!initMPU()) {
    Serial.println("Check MPU wiring!");
    display.clearDisplay();
    display.setCursor(10, 25);
    display.print(F("MPU ERROR!"));
    display.display();
    while (true);
  }

  connectWiFi();
  calibrateSensor();

  introDone = true;
  Serial.println("Landsafe AI ready!\n");
}

// ===== MAIN LOOP =====
void loop() {
  AccelData accel = readAccelFiltered();
  rawAx = accel.x; rawAy = accel.y; rawAz = accel.z;

  moisturePct = readMoisture();

  float dx = accel.x - refX;
  float dy = accel.y - refY;
  tilt = atan2(sqrt(dx * dx + dy * dy), abs(accel.z)) * 180.0 / PI;
  if (tilt < DEAD_ZONE) tilt = 0;

  status = "safe";
  if (tilt >= TILT_DANGER || moisturePct >= MOISTURE_DANGER) status = "danger";
  else if (tilt >= TILT_WARN || moisturePct >= MOISTURE_WARN) status = "warning";

  if (status == "danger") digitalWrite(LED_PIN, HIGH);
  else if (status == "warning") { digitalWrite(LED_PIN, HIGH); delay(100); digitalWrite(LED_PIN, LOW); delay(100); }
  else digitalWrite(LED_PIN, LOW);

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint >= 500) {
    lastPrint = millis();
    Serial.printf("Tilt: %+.1f° | Moist: %.0f%% | [%s]\n", tilt, moisturePct, status.c_str());
  }

  if (introDone) updateDisplay();

  unsigned long now = millis();
  if (now - lastSend >= 2000) {
    lastSend = now;
    sendToServer();
  }

  delay(50);
}
