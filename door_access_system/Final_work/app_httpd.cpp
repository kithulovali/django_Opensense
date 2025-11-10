#include "esp_camera.h"
#include "esp_timer.h"
#include "img_converters.h"
#include "esp_http_server.h"
#include "esp_system.h"

#include <string>
#include <memory>

extern SemaphoreHandle_t camera_mutex;
#include <Preferences.h>
extern Preferences prefs;
#include <WString.h>
extern String g_username;
extern volatile bool g_motorBusy;

// Forward declaration of motor cycle from the .ino
extern void motorOpenCloseCycle();

// Run motor without blocking HTTP
static void motor_task(void*){
  motorOpenCloseCycle();
  vTaskDelete(NULL);
}

static esp_err_t index_handler(httpd_req_t *req) {
  static const char* html =
    "<!doctype html><html><head><meta charset='utf-8'><title>ESP32-CAM</title></head>"
    "<body><h3>ESP32-CAM</h3>"
    "<ul><li><a href='/stream'>Stream</a></li><li><a href='/jpg'>Snapshot</a></li></ul>"
    "<hr/><form action='/api/set_user' method='get'>Username: <input name='username'/>"
    "<button type='submit'>Save</button></form></body></html>";
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html, HTTPD_RESP_USE_STRLEN);
}

// Robust snapshot with small retries
static esp_err_t jpg_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;

  for (int attempt = 0; attempt < 5 && fb == NULL; attempt++) {
    if (camera_mutex) {
      if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(800))) {
        fb = esp_camera_fb_get();
        xSemaphoreGive(camera_mutex);
      }
    } else {
      fb = esp_camera_fb_get();
    }
    if (!fb) vTaskDelay(pdMS_TO_TICKS(50));
  }

  if (!fb) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, "camera busy", HTTPD_RESP_USE_STRLEN);
  }

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);

  if (camera_mutex) {
    if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(300))) { esp_camera_fb_return(fb); xSemaphoreGive(camera_mutex); }
    else { esp_camera_fb_return(fb); }
  } else { esp_camera_fb_return(fb); }
  return res;
}

static esp_err_t stream_handler(httpd_req_t *req) {
  static const char* CT = "multipart/x-mixed-replace;boundary=frame";
  static const char* B  = "\r\n--frame\r\n";
  static const char* P  = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

  httpd_resp_set_type(req, CT);

  while (true) {
    camera_fb_t * fb = NULL;

    if (camera_mutex) {
      if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(600))) {
        fb = esp_camera_fb_get();
        xSemaphoreGive(camera_mutex);
      }
    } else {
      fb = esp_camera_fb_get();
    }

    if (!fb) { vTaskDelay(pdMS_TO_TICKS(30)); continue; }

    if (httpd_resp_sendstr_chunk(req, B) != ESP_OK) {
      // client closed
      if (camera_mutex) {
        if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(300))) { esp_camera_fb_return(fb); xSemaphoreGive(camera_mutex); }
        else { esp_camera_fb_return(fb); }
      } else { esp_camera_fb_return(fb); }
      break;
    }

    char part_buf[64];
    int hlen = snprintf(part_buf, 64, P, fb->len);
    if (httpd_resp_send_chunk(req, part_buf, hlen) != ESP_OK ||
        httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len) != ESP_OK) {
      // client closed
      if (camera_mutex) {
        if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(300))) { esp_camera_fb_return(fb); xSemaphoreGive(camera_mutex); }
        else { esp_camera_fb_return(fb); }
      } else { esp_camera_fb_return(fb); }
      break;
    }

    if (camera_mutex) {
      if (xSemaphoreTake(camera_mutex, pdMS_TO_TICKS(300))) { esp_camera_fb_return(fb); xSemaphoreGive(camera_mutex); }
      else { esp_camera_fb_return(fb); }
    } else { esp_camera_fb_return(fb); }

    vTaskDelay(pdMS_TO_TICKS(10)); // small breather
  }
  return ESP_OK;
}

// /api/set_user?username=<name>
static esp_err_t set_user_handler(httpd_req_t *req) {
  size_t qs_len = httpd_req_get_url_query_len(req) + 1;
  if (qs_len <= 1) {
    httpd_resp_set_status(req, "400 Bad Request");
    return httpd_resp_send(req, "username required", HTTPD_RESP_USE_STRLEN);
  }
  std::unique_ptr<char[]> q(new char[qs_len]);
  if (httpd_req_get_url_query_str(req, q.get(), qs_len) != ESP_OK) {
    httpd_resp_set_status(req, "400 Bad Request");
    return httpd_resp_send(req, "bad query", HTTPD_RESP_USE_STRLEN);
  }
  char user[64] = {0};
  if (httpd_query_key_value(q.get(), "username", user, sizeof(user)) != ESP_OK || user[0] == 0) {
    httpd_resp_set_status(req, "400 Bad Request");
    return httpd_resp_send(req, "username required", HTTPD_RESP_USE_STRLEN);
  }
  g_username = String(user);
  prefs.putString("user", g_username);
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, "OK", HTTPD_RESP_USE_STRLEN);
}

// /api/trigger_cycle → run motor open/close sequence
static esp_err_t trigger_cycle_handler(httpd_req_t *req) {
  if (g_motorBusy) {
    httpd_resp_set_status(req, "409 Conflict");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, "BUSY", HTTPD_RESP_USE_STRLEN);
  }
  xTaskCreatePinnedToCore(motor_task, "motor", 4096, nullptr, 1, nullptr, 1);
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_send(req, "OK", HTTPD_RESP_USE_STRLEN);
}

extern "C" void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.max_uri_handlers = 10;
  config.uri_match_fn = httpd_uri_match_wildcard;

  httpd_handle_t server = NULL;
  if (httpd_start(&server, &config) == ESP_OK) {
    httpd_uri_t index_uri   = { .uri="/",                .method=HTTP_GET, .handler=index_handler,        .user_ctx=NULL };
    httpd_uri_t jpg_uri     = { .uri="/jpg",             .method=HTTP_GET, .handler=jpg_handler,          .user_ctx=NULL };
    httpd_uri_t stream_uri  = { .uri="/stream",          .method=HTTP_GET, .handler=stream_handler,       .user_ctx=NULL };
    httpd_uri_t set_user    = { .uri="/api/set_user",    .method=HTTP_GET, .handler=set_user_handler,     .user_ctx=NULL };
    httpd_uri_t trigger_uri = { .uri="/api/trigger_cycle", .method=HTTP_GET, .handler=trigger_cycle_handler, .user_ctx=NULL };

    httpd_register_uri_handler(server, &index_uri);
    httpd_register_uri_handler(server, &jpg_uri);
    httpd_register_uri_handler(server, &stream_uri);
    httpd_register_uri_handler(server, &set_user);
    httpd_register_uri_handler(server, &trigger_uri);
  }
}