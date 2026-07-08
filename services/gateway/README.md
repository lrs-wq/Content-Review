# Gateway Service

统一审核入口，默认端口 `8040`。它不加载审核模型，只负责把文本、图片、视频请求路由到现有服务；异步审核结果也在同一端口查询：

- 文本：`text-audit-service:8010`
- 图片：`image-audit-service:8020`
- 视频：`video-audit-service:8030`

## Run

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_gateway.ps1
```

Docker Compose：

```bash
docker compose up -d gateway-service
```

## API

```http
POST /v1/moderation
```

默认返回简要结果：

```json
{
  "client_elapsed_ms": 144.5,
  "content_id": "content_001",
  "result": "review",
  "action": "review",
  "risk_level": "medium",
  "reason": "命中规则 广告引流风险:加微信；风险标签 广告引流风险"
}
```

返回规范：默认业务响应固定为 `content_id`、`result`、`action`、`risk_level`、`reason`；测试页展示时会额外补 `client_elapsed_ms`。`reason` 默认中文，原始文本证据保持原文。

需要完整调试字段时加 `?brief=false`。

`content_id` 可以不传；不传时网关会生成并返回。

异步提交：

```http
POST /v1/moderation/async
```

返回：

```json
{
  "content_id": "cr_20260708091230_ab12cd34ef",
  "status": "queued",
  "status_label": "已排队",
  "content_type": "text",
  "content_type_label": "文本",
  "result_url": "http://127.0.0.1:8040/v1/moderation/result/cr_20260708091230_ab12cd34ef"
}
```

查询：

```http
GET http://127.0.0.1:8040/v1/moderation/result/{content_id}
```

`status` 为 `completed` 时，`result` 字段就是最终审核结果。

### Text JSON

```bash
curl -X POST "http://127.0.0.1:8040/v1/moderation" \
  -H "Content-Type: application/json" \
  -d "{\"content_type\":\"text\",\"content_id\":\"text1\",\"user_id\":\"u1\",\"scene\":\"comment\",\"text\":\"这里可以加微信私聊\",\"context\":{}}"
```

### Image Upload

```bash
curl -X POST "http://127.0.0.1:8040/v1/moderation" \
  -F "content_type=image" \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "scene=post_image" \
  -F "skip_ocr=false" \
  -F "context={}" \
  -F "file=@./sample.jpg"
```

### Video Upload

```bash
curl -X POST "http://127.0.0.1:8040/v1/moderation" \
  -F "content_type=video" \
  -F "content_id=video1" \
  -F "user_id=u1" \
  -F "scene=post_video" \
  -F "skip_ocr=true" \
  -F "context={}" \
  -F "file=@./sample.mp4"
```

`content_type` 可省略：有 `text` 字段时自动识别文本；上传文件 MIME 为 `image/*` 或 `video/*` 时自动识别图片/视频。
