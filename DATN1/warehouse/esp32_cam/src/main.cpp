#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_camera.h>

#define LED_PIN 4 // Đèn flash trên AI Thinker ESP32-CAM
#define SEND_INTERVAL 5000 // Gửi ảnh mỗi 5 giây
#define WIFI_RECONNECT_INTERVAL 5000 // Kiểm tra WiFi mỗi 5 giây
#define CAMERA_REINIT_INTERVAL 10000 // Kiểm tra camera mỗi 10 giây
#define CAMERA_INIT_RETRIES 3 // Thử khởi tạo camera tối đa 3 lần
#define MIN_IMAGE_SIZE 1000 // Kích thước ảnh tối thiểu (byte)

const char* ssid = "03";
const char* password = "12345678";

IPAddress local_IP(192, 168, 252, 100);
IPAddress gateway(192, 168, 252, 1);
IPAddress subnet(255, 255, 255, 0);

const char* flaskServer = "http://192.168.252.106:5000/upload_image";

// Cấu hình chân cho AI Thinker ESP32-CAM
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

bool setupCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000; // Tăng lên 20MHz để cải thiện tốc độ
  config.pixel_format = PIXFORMAT_JPEG;
  

  bool psram = psramFound();
  Serial.printf("PSRAM found: %s\n", psram ? "Yes" : "No");
  if (psram) {
    config.frame_size = FRAMESIZE_XGA; // 1024x768
    config.jpeg_quality = 8; // Chất lượng cao hơn
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_SVGA; // 800x600
    config.jpeg_quality = 10;
    config.fb_count = 1;
  }

  esp_err_t err;
  for (int i = 0; i < CAMERA_INIT_RETRIES; i++) {
    err = esp_camera_init(&config);
    if (err == ESP_OK) {
      break;
    }
    Serial.printf("Camera init failed with error 0x%x, retry %d/%d\n", err, i + 1, CAMERA_INIT_RETRIES);
    delay(500);
    esp_camera_deinit();
  }

  if (err != ESP_OK) {
    Serial.printf("Camera init failed after %d retries with error 0x%x\n", CAMERA_INIT_RETRIES, err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
s->set_brightness(s, 2);     // độ sáng: -2 to 2
s->set_contrast(s, 2);       // độ tương phản: -2 to 2
s->set_saturation(s, 2);     // độ bão hòa: -2 to 2
s->set_sharpness(s, 2);      // độ sắc nét (nếu sensor hỗ trợ)
s->set_whitebal(s, 1);       // bật cân bằng trắng
s->set_gain_ctrl(s, 1);      // bật điều chỉnh gain
s->set_exposure_ctrl(s, 1);  // bật điều chỉnh phơi sáng
s->set_awb_gain(s, 1);       // auto white balance gain
s->set_aec2(s, 1);           // advanced exposure control


  Serial.println("Camera initialized successfully");
  return true;
}

void reconnectWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, reconnecting...");
    WiFi.disconnect();
    WiFi.begin(ssid, password);
    unsigned long startTime = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startTime < WIFI_RECONNECT_INTERVAL) {
      delay(500);
      Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWiFi reconnected");
      Serial.println("IP address: " + WiFi.localIP().toString());
    } else {
      Serial.println("\nFailed to reconnect WiFi");
    }
  }
}

bool sendImageToServer(camera_fb_t* fb) {
  if (!fb || fb->len < MIN_IMAGE_SIZE) {
    Serial.printf("Invalid frame buffer or too small (%u bytes)\n", fb ? fb->len : 0);
    return false;
  }

  Serial.printf("Captured image size: %u bytes\n", fb->len);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected");
    return false;
  }

  HTTPClient http;
  bool success = false;

  String boundary = "----WebKitFormBoundary" + String(random(1000000, 9999999));
  String contentType = "multipart/form-data; boundary=" + boundary;
  String bodyStart = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
  String bodyEnd = "\r\n--" + boundary + "--\r\n";

  size_t bodyLength = bodyStart.length() + fb->len + bodyEnd.length();
  uint8_t* buffer = (uint8_t*)malloc(bodyLength);
  if (!buffer) {
    Serial.println("Failed to allocate memory for multipart");
    return false;
  }

  size_t pos = 0;
  memcpy(buffer + pos, bodyStart.c_str(), bodyStart.length());
  pos += bodyStart.length();
  memcpy(buffer + pos, fb->buf, fb->len);
  pos += fb->len;
  memcpy(buffer + pos, bodyEnd.c_str(), bodyEnd.length());

  http.begin(flaskServer);
  http.addHeader("Content-Type", contentType);
  http.addHeader("Content-Length", String(bodyLength));

  int httpResponseCode = http.POST(buffer, bodyLength);

  digitalWrite(LED_PIN, LOW); // Tắt đèn flash sau khi gửi

  free(buffer);

  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.println("HTTP Response: " + String(httpResponseCode) + ", Server response: " + response);
    success = (httpResponseCode == 200);
  } else {
    Serial.printf("Failed to send image, HTTP error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  return success;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  if (!WiFi.config(local_IP, gateway, subnet)) {
    Serial.println("Failed to configure IP");
  }

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startTime < WIFI_RECONNECT_INTERVAL) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.println("IP address: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi connection failed");
    while (true);
  }

  if (!setupCamera()) {
    Serial.println("Camera setup failed, stopping...");
    while (true);
  }
}

void loop() {
  static unsigned long lastSendTime = 0;
  static unsigned long lastCameraCheckTime = 0;
  static unsigned long lastWiFiCheckTime = 0;

  if (millis() - lastWiFiCheckTime > WIFI_RECONNECT_INTERVAL) {
    reconnectWiFi();
    lastWiFiCheckTime = millis();
  }

  if (millis() - lastCameraCheckTime > CAMERA_REINIT_INTERVAL) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera check failed, reinitializing...");
      esp_camera_deinit();
      if (setupCamera()) {
        Serial.println("Camera reinitialized successfully");
      } else {
        Serial.println("Camera reinitialization failed");
      }
    } else {
      esp_camera_fb_return(fb);
    }
    lastCameraCheckTime = millis();
  }

  if (millis() - lastSendTime >= SEND_INTERVAL) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      lastSendTime = millis(); // Đặt lại thời gian để thử lại
      return;
    }

    if (sendImageToServer(fb)) {
      Serial.println("Image sent successfully");
    } else {
      Serial.println("Failed to send image");
    }
    esp_camera_fb_return(fb);
    lastSendTime = millis();
  }
}