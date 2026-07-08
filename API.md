# Content Review 简短接口文档

版本：`2026.06.24`  
更新时间：`2026-07-07`

## 1. 接入地址

| 服务 | 地址 |
|---|---|
| 统一审核入口 | `http://39.106.120.253:8040` |
| 文本审核 | `http://39.106.120.253:8010` |
| 图片审核 | `http://39.106.120.253:8020` |
| 视频审核 | `http://39.106.120.253:8030` |
| 测试页面 | `http://39.106.120.253:8050` |

本机调试可把域名/IP 换成 `127.0.0.1`。

注意：公网访问需要阿里云安全组放行 `8010`、`8020`、`8030`、`8040`、`8050`。

## 2. 简短响应模式

接口默认已经开启简短响应模式。业务调用时不要传 `brief=false`。

所有审核接口默认返回：

```json
{
  "content_id": "content_001",
  "result": "review",
  "reason": "命中规则 ad:联系方式；风险标签 ad"
}
```

如果下游接入阿里云敏感词审核，默认简短响应会把阿里云命中的风险原因整理到 `reason`：

```json
{
  "content_id": "content_001",
  "result": "block",
  "reason": "原因 疑似低俗口头语内容；命中词 八嘎(1-3)；标签 inappropriate_oral；置信度 100"
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content_id` | string | 业务内容 ID |
| `result` | string | 审核结果：`allow`、`review`、`block`，图片接口可能返回 `mask` |
| `reason` | string | 简短原因 |

结果含义：

| result | 含义 |
|---|---|
| `allow` | 放行 |
| `review` | 进入人工审核或业务复核 |
| `block` | 拦截、隐藏或禁止发布 |
| `mask` | 建议打码，仅图片接口可能返回 |

## 3. 健康检查

### 统一入口

```bash
curl http://39.106.120.253:8040/health
```

### 文本服务

```bash
curl http://39.106.120.253:8010/health
```

### 图片服务

```bash
curl http://39.106.120.253:8020/health
```

### 视频服务

```bash
curl http://39.106.120.253:8030/health
```

健康检查返回 `status: ok` 表示服务可用。

## 3.1 统一审核入口（推荐）

业务侧推荐统一调用 `8040`：

```http
POST /v1/moderation
```

### 文本 JSON

```bash
curl -X POST "http://39.106.120.253:8040/v1/moderation" \
  -H "Content-Type: application/json" \
  -d '{
    "content_type": "text",
    "content_id": "text_10001",
    "user_id": "u_123",
    "scene": "comment",
    "text": "待审核文本",
    "context": {}
  }'
```

### 图片上传

```bash
curl -X POST "http://39.106.120.253:8040/v1/moderation" \
  -F "content_type=image" \
  -F "content_id=img_10001" \
  -F "user_id=u_123" \
  -F "scene=post_image" \
  -F "skip_ocr=false" \
  -F "context={}" \
  -F "file=@./sample.jpg"
```

### 视频上传

```bash
curl -X POST "http://39.106.120.253:8040/v1/moderation" \
  -F "content_type=video" \
  -F "content_id=video_10001" \
  -F "user_id=u_123" \
  -F "scene=post_video" \
  -F "skip_ocr=true" \
  -F "context={}" \
  -F "file=@./sample.mp4"
```

`content_type` 可不传：有 `text` 字段时自动识别文本；上传文件 MIME 为 `image/*` 或 `video/*` 时自动识别图片/视频。需要完整调试字段时在 URL 加 `?brief=false`。

## 4. 文本审核

### 接口

```http
POST /v1/moderation/text
Content-Type: application/json
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `content_id` | string | 是 | 业务内容 ID |
| `user_id` | string | 是 | 用户 ID |
| `scene` | string | 否 | 场景，如 `comment`、`post`、`private_message` |
| `text` | string | 是 | 待审核文本 |
| `related_text` | string | 否 | 标题、父评论、正文等相关文本 |
| `image_ocr_text` | string[] | 否 | 图片 OCR 文本 |
| `video_transcript` | string | 否 | 视频 ASR 文本 |
| `context` | object | 否 | 业务上下文 |

### 请求示例

```bash
curl -X POST "http://39.106.120.253:8010/v1/moderation/text" \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "text_10001",
    "user_id": "u_123",
    "scene": "comment",
    "text": "这里是待审核文本",
    "related_text": "帖子标题或父评论",
    "image_ocr_text": [],
    "video_transcript": null,
    "context": {}
  }'
```

### 响应示例

```json
{
  "content_id": "text_10001",
  "result": "allow",
  "reason": "未命中风险规则，模型综合风险较低"
}
```

## 5. 图片审核

图片支持两种方式：

- `POST /v1/moderation/image/upload`：上传图片文件，推荐使用。
- `POST /v1/moderation/image`：传 Base64 或图片 URL。

限制：

| 项 | 限制 |
|---|---|
| 格式 | `JPEG`、`PNG`、`WEBP`、`BMP` |
| 最大大小 | `10MB` |
| 最大像素 | `25,000,000` |

### 5.1 图片上传接口

```http
POST /v1/moderation/image/upload
Content-Type: multipart/form-data
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `content_id` | string | 是 | 业务内容 ID |
| `user_id` | string | 是 | 用户 ID |
| `scene` | string | 否 | 场景，如 `post_image`、`avatar` |
| `file` | file | 是 | 图片文件 |
| `related_text` | string | 否 | 图片关联文本 |
| `provided_ocr_text` | string | 否 | 上游已有 OCR 文本 |
| `skip_ocr` | boolean | 否 | 是否跳过 OCR |
| `context` | JSON string | 否 | JSON 对象字符串 |

请求示例：

```bash
curl -X POST "http://39.106.120.253:8020/v1/moderation/image/upload" \
  -F "content_id=img_10001" \
  -F "user_id=u_123" \
  -F "scene=post_image" \
  -F "related_text=图片相关正文" \
  -F "provided_ocr_text=" \
  -F "skip_ocr=false" \
  -F "context={}" \
  -F "file=@./sample.jpg"
```

响应示例：

```json
{
  "content_id": "img_10001",
  "result": "review",
  "reason": "视觉命中 image_too_small(0.45)/metadata；风险标签 image_too_small"
}
```

### 5.2 图片 JSON 接口

```http
POST /v1/moderation/image
Content-Type: application/json
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `content_id` | string | 是 | 业务内容 ID |
| `user_id` | string | 是 | 用户 ID |
| `scene` | string | 否 | 场景 |
| `image_base64` | string | 条件必填 | Base64 图片 |
| `image_url` | string | 条件必填 | 图片 URL |
| `related_text` | string | 否 | 图片关联文本 |
| `provided_ocr_text` | string | 否 | 上游已有 OCR 文本 |
| `skip_ocr` | boolean | 否 | 是否跳过 OCR |
| `context` | object | 否 | 业务上下文 |

`image_base64` 和 `image_url` 二选一。

请求示例：

```bash
curl -X POST "http://39.106.120.253:8020/v1/moderation/image" \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "img_10002",
    "user_id": "u_123",
    "scene": "post_image",
    "image_url": "https://example.com/image.jpg",
    "related_text": "",
    "skip_ocr": false,
    "context": {}
  }'
```

## 6. 视频审核

### 接口

```http
POST /v1/moderation/video/upload
Content-Type: multipart/form-data
```

限制：

| 项 | 限制 |
|---|---|
| 最大大小 | `100MB` |
| 最大时长 | `60` 秒 |
| 格式 | `mp4`、`mov`、`webm`、`mkv`、`avi` |

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `content_id` | string | 是 | 业务内容 ID |
| `user_id` | string | 是 | 用户 ID |
| `scene` | string | 否 | 场景，如 `post_video` |
| `file` | file | 是 | 视频文件 |
| `related_text` | string | 否 | 视频标题、正文、评论等 |
| `provided_asr_text` | string | 否 | 上游已有 ASR 文本 |
| `skip_ocr` | boolean | 否 | 是否跳过帧 OCR |
| `context` | JSON string | 否 | JSON 对象字符串 |

### 请求示例

```bash
curl -X POST "http://39.106.120.253:8030/v1/moderation/video/upload" \
  -F "content_id=video_10001" \
  -F "user_id=u_123" \
  -F "scene=post_video" \
  -F "related_text=视频标题或正文" \
  -F "provided_asr_text=" \
  -F "skip_ocr=true" \
  -F "context={}" \
  -F "file=@./sample.mp4"
```

### 响应示例

```json
{
  "content_id": "video_10001",
  "result": "review",
  "reason": "证据 text:ad(0.75)；聚合文本审核 ad；风险标签 video_text_sensitive,ad"
}
```

## 7. 错误响应

### 参数错误

缺少必填字段或字段类型错误时，通常返回 `422`。

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "content_id"],
      "msg": "Field required"
    }
  ]
}
```

### 图片错误

```json
{
  "detail": "unsupported_image_format:GIF",
  "error": "invalid_image"
}
```

常见原因：

| detail | 说明 |
|---|---|
| `missing_image_source` | 未提供图片 |
| `invalid_image_base64` | Base64 不合法 |
| `image_decode_failed` | 图片无法解码 |
| `unsupported_image_format:*` | 图片格式不支持 |
| `image_too_large:*` | 图片过大 |
| `image_pixels_too_large:*` | 图片像素过大 |

### 视频错误

```json
{
  "detail": "video duration 75.000s exceeds 60.000s",
  "error": "video_too_long"
}
```

常见原因：

| error | 说明 |
|---|---|
| `unsupported_video_type` | 视频格式不支持 |
| `empty_video` | 视频为空 |
| `video_file_too_large` | 视频超过 100MB |
| `missing_video_stream` | 未找到视频流 |
| `invalid_video_duration` | 视频时长无效 |
| `video_too_long` | 视频超过 60 秒 |
| `ffprobe_failed` | 视频解析失败 |
| `frame_sampling_failed` | 抽帧失败 |

## 8. 服务运维命令

查看状态：

```bash
systemctl status content-review-text
systemctl status content-review-image
systemctl status content-review-video
systemctl status content-review-ui
```

重启服务：

```bash
systemctl restart content-review-text content-review-image content-review-video content-review-ui
```

查看日志：

```bash
journalctl -u content-review-text -f
journalctl -u content-review-image -f
journalctl -u content-review-video -f
journalctl -u content-review-ui -f
```

## 9. 调试完整响应

业务接入不要使用完整响应。

只有排查问题时才临时追加：

```text
?brief=false
```

例如：

```bash
curl -X POST "http://39.106.120.253:8010/v1/moderation/text?brief=false" ...
```

完整响应包含 `trace_id`、`labels`、`scores`、命中证据、OCR/ASR/抽帧详情等字段，适合后端排障，不适合直接给业务前端使用。
