#include <WiFi.h>
#include <WebServer.h>
#include <DHTesp.h>
#include <HX711.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>

float temperature = 0.0, humidity = 0.0, weight = 0.0;

const char* ssid = "03";      
const char* password = "12345678"; 


const char* flaskServer = "http://192.168.75.106:5000";

WebServer server(80);

#define DHT_PIN 13
#define DT 4
#define SCK 5
HX711 scale;
DHTesp dht;

void sendSensorData() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, cannot send sensor data.");
    return;
  }

  if (isnan(temperature) || isnan(humidity)|| isnan(weight)) {
    Serial.println("Invalid sensor data (NaN), skipping send.");
    return;
  }

  HTTPClient http;
  String url = String(flaskServer) + "/api/sensor";
  Serial.print("Sending sensor data to: ");
  Serial.println(url);

  if (!http.begin(url)) {
    Serial.println("Failed to initialize HTTP connection for sensor data.");
    http.end();
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.setTimeout(2000);

  DynamicJsonDocument doc(300);
  doc["temperature"] = temperature;
  doc["humidity"] = humidity;
  doc["weight"] = weight;
  String payload;
  serializeJson(doc, payload);
  Serial.print("Sensor payload: ");
  Serial.println(payload);

  int httpCode = http.POST(payload);
  if (httpCode > 0) {
    if (httpCode == HTTP_CODE_OK) {
      Serial.println("Sensor data sent successfully.");
      String response = http.getString();
      Serial.print("Response: ");
      Serial.println(response);
    } else {
      Serial.print("HTTP request failed with code: ");
      Serial.println(httpCode);
      String response = http.getString();
      Serial.print("Response: ");
      Serial.println(response);
    }
  } else {
    Serial.print("HTTP request failed with error code: ");
    Serial.println(httpCode);
    Serial.println("Possible causes: Server unreachable, timeout, or network issue.");
  }
  http.end();
}

void handleData() {
  String json = "{";
  json += "\"temperature\":" + String(temperature, 1) + ",";
  json += "\"humidity\":" + String(humidity, 0) + ",";
  json += "\"weight\":" + String(weight / 1000, 2);
  json += "}";
  Serial.println("Sending debug data to client.");
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);
  delay(100);
  dht.setup(DHT_PIN, DHTesp::DHT11);
  Serial.println("DHT11 sensor initialized.");

  scale.begin(DT, SCK);
  scale.set_scale(); 
  scale.tare();      
  Serial.println("HX711 initialized.");


  WiFi.mode(WIFI_STA);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }

  Serial.println("\nWiFi connected.");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
 
  server.on("/data", handleData);

  server.begin();
  Serial.println("Web server started.");
}

void loop() {
  weight = scale.get_units(10);
  temperature = dht.getTemperature();
  humidity = dht.getHumidity();
  if (dht.getStatusString() != "OK") {
    Serial.print("DHT Error: ");
    Serial.println(dht.getStatusString());
  }

  sendSensorData();
  server.handleClient();

  delay(1000);
}