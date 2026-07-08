# Gateway Service

统一审核入口，默认端口 `8040`。它不加载审核模型，只负责把文本、图片、视频请求路由到现有服务：

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
  "content_id": "content_001",
  "result": "review",
  "reason": "命中规则 ad:加微信；风险标签 ad"
}
```

需要完整调试字段时加 `?brief=false`。

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
