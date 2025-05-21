#include <WiFi.h>
#include <WebServer.h>
#include <DHTesp.h>

// Khai báo đối tượng DHT
DHTesp dht;

// Biến lưu trữ nhiệt độ và độ ẩm
float temperature, humidity;

// Chân kết nối cảm biến DHT11
#define DHT_PIN 13

// Thông tin WiFi
const char* ssid = "03";       // Thay bằng tên WiFi của bạn
const char* password = "12345678"; // Thay bằng mật khẩu WiFi của bạn

// Khởi tạo web server trên cổng 80
WebServer server(80);

void handleRoot() {
  // Tạo nội dung HTML với JavaScript để tự động cập nhật dữ liệu
  String html = "<!DOCTYPE html><html><head><title>ESP32 Web Server</title>";
  html += "<meta charset=\"UTF-8\">"; // Thêm mã hóa UTF-8
  html += "<style>body { font-family: Arial; text-align: center; margin-top: 50px; }";
  html += "h1 { color: #333; } p { font-size: 1.2em; }</style></head><body>";
  html += "<h1>ESP32 DHT11 Web Server</h1>";
  html += "<p>Temperature: <span id='temp'>--</span> °C</p>";
  html += "<p>Humidity: <span id='hum'>--</span> %</p>";
  html += "<script>";
  html += "setInterval(() => { fetch('/data').then(res => res.json()).then(data => {";
  html += "document.getElementById('temp').innerText = data.temperature;";
  html += "document.getElementById('hum').innerText = data.humidity;";
  html += "}); }, 2000);"; // Cập nhật mỗi 2 giây
  html += "</script></body></html>";

  // Gửi nội dung HTML về trình duyệt
  server.send(200, "text/html", html);
}

void handleData() {
  // Trả về dữ liệu nhiệt độ và độ ẩm dưới dạng JSON
  String json = "{";
  json += "\"temperature\":" + String(temperature, 1) + ",";
  json += "\"humidity\":" + String(humidity, 0);
  json += "}";
  server.send(200, "application/json", json);
}

void setup() {
  // Khởi tạo Serial để debug
  Serial.begin(115200);
  delay(100);

  // Khởi tạo cảm biến DHT11
  dht.setup(DHT_PIN, DHTesp::DHT11);
  Serial.println("DHT11 sensor initialized.");

  // Kết nối WiFi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected.");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // Cấu hình route cho web server
  server.on("/", handleRoot);
  server.on("/data", handleData); // Route để trả về dữ liệu JSON

  // Bắt đầu web server
  server.begin();
  Serial.println("Web server started.");
}

void loop() {
  // Đọc dữ liệu từ cảm biến
  if (millis() - dht.getMinimumSamplingPeriod() >= 0) {
    temperature = dht.getTemperature();
    humidity = dht.getHumidity();

    // Kiểm tra trạng thái của cảm biến
    if (dht.getStatusString() != "OK") {
      Serial.print("DHT Error: ");
      Serial.println(dht.getStatusString());
    }
  }

  // Xử lý các yêu cầu từ client
  server.handleClient();
}