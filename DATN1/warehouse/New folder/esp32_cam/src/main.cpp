#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_camera.h>


#define LED_PIN 4                      // Đèn flash trên AI Thinker ESP32-CAM
#define SEND_INTERVAL_MS 2000          // Gửi ảnh mỗi 2 giây (tăng tần suất)
#define WIFI_RECONNECT_INTERVAL_MS 5000 // Kiểm tra WiFi mỗi 5 giây
#define CAMERA_REINIT_INTERVAL_MS 60000 // Kiểm tra/khởi tạo lại camera mỗi 60 giây (ít thường xuyên hơn để ổn định)
#define CAMERA_INIT_RETRIES 5          // Thử khởi tạo camera tối đa 5 lần (tăng số lần thử)
#define MIN_IMAGE_SIZE_BYTES 2000      // Kích thước ảnh tối thiểu (byte), tăng lên để loại bỏ ảnh hỏng nhỏ

const char* ssid = "03";
const char* password = "12345678";


const char* flaskServer = "http://192.168.75.106:5000/upload_image";

#define PWDN_GPIO_NUM       32
#define RESET_GPIO_NUM      -1
#define XCLK_GPIO_NUM       0
#define SIOD_GPIO_NUM       26
#define SIOC_GPIO_NUM       27
#define Y9_GPIO_NUM         35
#define Y8_GPIO_NUM         34
#define Y7_GPIO_NUM         39
#define Y6_GPIO_NUM         36
#define Y5_GPIO_NUM         21
#define Y4_GPIO_NUM         19
#define Y3_GPIO_NUM         18
#define Y2_GPIO_NUM         5
#define VSYNC_GPIO_NUM      25
#define HREF_GPIO_NUM       23
#define PCLK_GPIO_NUM       22

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
  config.xclk_freq_hz = 20000000; // Tần số xclk 20MHz
  config.pixel_format = PIXFORMAT_JPEG; // Định dạng JPEG

  bool psram = psramFound();
  Serial.printf("PSRAM found: %s\n", psram ? "Yes" : "No");

  if (psram) {
    config.frame_size = FRAMESIZE_UXGA; // Kích thước ảnh cao nhất (1600x1200)
    config.jpeg_quality = 8;            // Chất lượng JPEG (0-63), 8 là tốt và kích thước vừa phải
    config.fb_count = 2;                // 2 frame buffer để chụp ảnh mượt mà hơn
  } else {
    // Nếu không có PSRAM, dùng kích thước nhỏ hơn để tránh tràn bộ nhớ
    config.frame_size = FRAMESIZE_XGA;  // 1024x768
    config.jpeg_quality = 10;           // Chất lượng giảm nhẹ
    config.fb_count = 1;
  }

  esp_err_t err;
  for (int i = 0; i < CAMERA_INIT_RETRIES; i++) {
    err = esp_camera_init(&config);
    if (err == ESP_OK) {
      break;
    }
    Serial.printf("Camera init failed with error 0x%x, retry %d/%d\n", err, i + 1, CAMERA_INIT_RETRIES);
    delay(1000); // Tăng thời gian chờ giữa các lần thử
    esp_camera_deinit(); // Giải phóng camera trước khi thử lại
  }

  if (err != ESP_OK) {
    Serial.printf("Camera init failed after %d retries with error 0x%x\n", CAMERA_INIT_RETRIES, err);
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s == NULL) {
    Serial.println("Failed to get camera sensor object!");
    return false;
  }
  s->set_vflip(s, 1);       // Lật ảnh dọc (thường cần cho ESP32-CAM)
  s->set_hmirror(s, 1);     // Lật ảnh ngang (thường cần cho ESP32-CAM)
  s->set_brightness(s, 1);  // Độ sáng: -2 (tối nhất) đến 2 (sáng nhất), 1 là hơi sáng hơn
  s->set_contrast(s, 1);    // Độ tương phản: -2 đến 2, 1 là hơi tăng
  s->set_saturation(s, 1);  // Độ bão hòa: -2 đến 2, 1 là hơi tăng
  s->set_sharpness(s, 1);   // Độ sắc nét: -2 đến 2, 1 là hơi tăng (nếu sensor hỗ trợ)
  s->set_whitebal(s, 1);    // Bật cân bằng trắng tự động (AWB)
  s->set_awb_gain(s, 1);    // Bật điều chỉnh gain cho AWB
  s->set_aec2(s, 1);        // Bật Advanced Exposure Control (kiểm soát phơi sáng nâng cao)
  s->set_ae_level(s, 0);    // Mức độ phơi sáng tự động, 0 là trung bình
  s->set_gain_ctrl(s, 1);   // Bật điều khiển Gain tự động (AGC)
  s->set_agc_gain(s, 0);    // Mức độ gain tự động, 0 là trung bình
  s->set_exposure_ctrl(s, 1); // Bật điều khiển phơi sáng tự động (AEC)
  s->set_dcw(s, 1);         // Bật Data Compression Workflow (nếu có)
  s->set_colorbar(s, 0);    // Tắt thanh màu debug

  Serial.println("Camera initialized successfully with custom settings");
  return true;
}

void reconnectWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, reconnecting...");
    WiFi.disconnect();
    WiFi.begin(ssid, password);
    unsigned long startTime = millis();
    while (WiFi.status() != WL_CONNECTED ) {
      delay(500);
      Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nWiFi reconnected");
      Serial.println("IP address: " + WiFi.localIP().toString());
    } else {
      Serial.println("\nFailed to reconnect WiFi, retrying next cycle.");
    }
  }
}


bool sendImageToServer(camera_fb_t* fb) {

  if (!fb || fb->len < MIN_IMAGE_SIZE_BYTES) {
    Serial.printf("Invalid frame buffer or too small (%u bytes). Skipping send.\n", fb ? fb->len : 0);
    return false;
  }

  Serial.printf("Captured image size: %u bytes\n", fb->len);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected. Cannot send image.");
    return false;
  }

  HTTPClient http;
  bool success = false;

  String boundary = "----WebKitFormBoundary" + String(random(1000000, 9999999)) + String(millis());
  String contentType = "multipart/form-data; boundary=" + boundary;
  String bodyStart = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
  String bodyEnd = "\r\n--" + boundary + "--\r\n";
  size_t bodyLength = bodyStart.length() + fb->len + bodyEnd.length();
  uint8_t* buffer = (uint8_t*)malloc(bodyLength);
  if (!buffer) {
    Serial.println("Failed to allocate memory for multipart HTTP request.");
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

  Serial.println("Sending HTTP POST request...");
  int httpResponseCode = http.POST(buffer, bodyLength); 

  free(buffer); 

  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.printf("HTTP Response Code: %d, Server response: %s\n", httpResponseCode, response.c_str());
    success = (httpResponseCode == 200);
    if (success && response.indexOf("\"qr_code\":") > 0 && response.indexOf("\"qr_code\":\"null\"") == -1) {
      Serial.println("QR code detected! Turning on LED for 1 second");
      digitalWrite(LED_PIN, HIGH);
      delay(1000);
      digitalWrite(LED_PIN, LOW);
    }
  } else {
    Serial.printf("Failed to send image, HTTP error: %s\n", http.errorToString(httpResponseCode).c_str());
  }

  http.end();
  return success;
}

// --- Setup chính ---
void setup() {
  Serial.begin(115200); 
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW); 

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED ) { 
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    Serial.println("IP address: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi connection failed, please check credentials/network. Halting.");
    while (true);
  }

  if (!setupCamera()) {
    Serial.println("Camera setup failed, halting...");
    while (true); 
  }
}

void loop() {
  static unsigned long lastSendTime = 0;
  static unsigned long lastCameraCheckTime = 0;
  static unsigned long lastWiFiCheckTime = 0;

  if (millis() - lastWiFiCheckTime >= WIFI_RECONNECT_INTERVAL_MS) {
    reconnectWiFi();
    lastWiFiCheckTime = millis();
  }

  if (millis() - lastCameraCheckTime >= CAMERA_REINIT_INTERVAL_MS) {
    camera_fb_t *fb = esp_camera_fb_get(); 
    if (!fb) {
      Serial.println("Camera frame capture failed during check. Reinitializing camera...");
      esp_camera_deinit();
      if (setupCamera()) {
        Serial.println("Camera reinitialized successfully.");
      } else {
        Serial.println("Camera reinitialization failed. It might be unstable.");
      }
    } else {
      esp_camera_fb_return(fb); 
    }
    lastCameraCheckTime = millis();
  }

  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed!");
      lastSendTime = millis();
      return;
    }

    if (sendImageToServer(fb)) {
      Serial.println("Image sent successfully.");
    } else {
      Serial.println("Failed to send image.");
    }
    esp_camera_fb_return(fb);
    lastSendTime = millis(); 
  }
}