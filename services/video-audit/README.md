# Video Audit Service

视频审核服务提供独立 HTTP API，负责 60 秒以内视频的校验、抽帧、图片审核调用、OCR/ASR 文本聚合和总风险决策。

## Run

```powershell
powershell -ExecutionPolicy Bypass -File tools/start_video_audit.ps1
```

依赖：

- `text-audit-service`：默认 `http://127.0.0.1:8010`
- `image-audit-service`：默认 `http://127.0.0.1:8020`
- `ffmpeg` / `ffprobe`

## API

```bash
curl -X POST http://127.0.0.1:8030/v1/moderation/video/upload \
  -F "content_id=video1" \
  -F "user_id=u1" \
  -F "scene=post_video" \
  -F "related_text=视频标题或正文" \
  -F "provided_asr_text=已有语音转写，可选" \
  -F "context={}" \
  -F "file=@./sample.mp4"
```

## Pipeline

```text
视频上传
  -> 文件大小、格式、ffprobe 元信息校验
  -> 时长超过 60 秒直接拒绝
  -> ffmpeg 按 1 fps 抽帧，最多 60 帧
  -> 每帧先调用 image-audit-service，默认跳过 OCR
  -> 仅首帧/明显文字区域/二维码或风险帧在配额内开启帧 OCR
  -> 聚合选择性帧 OCR + provided_asr_text
  -> 调用 text-audit-service 做上下文文本审核
  -> 融合帧风险、OCR/ASR 风险、相关文本风险
  -> 输出 allow / review / block
```

当前默认不强制本地 ASR；如果上游已经有语音转写，可以通过 `provided_asr_text` 传入。后续可开启 `faster-whisper` 作为本地 ASR provider。
