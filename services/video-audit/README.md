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

默认返回简要结果：

```json
{
  "content_id": "video1",
  "result": "review",
  "reason": "证据 frame:violence@2.0s(0.82)；风险标签 violence"
}
```

需要完整调试字段时使用 `?brief=false`，例如查看抽帧来源、ASR、OCR、每帧审核结果。

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

URL 方式也会下载到临时文件后进入同一条 ffprobe/抽帧/ASR/文本聚合流程：

```bash
curl -X POST http://127.0.0.1:8030/v1/moderation/video \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "video_url_1",
    "user_id": "u1",
    "scene": "post_video",
    "video_url": "https://example.com/sample.mp4",
    "skip_ocr": false,
    "context": {}
  }'
```

## Pipeline

```text
视频上传
  -> 文件大小、格式、ffprobe 元信息校验
  -> 时长超过 60 秒直接拒绝
  -> ffmpeg 按 1 fps 抽帧，最多 60 帧
  -> PySceneDetect 检测场景切换帧，并替换附近固定帧补强覆盖
  -> 每帧先调用 image-audit-service，默认跳过 OCR
  -> 仅首帧/明显文字区域/二维码或风险帧在配额内开启帧 OCR
  -> faster-whisper 自动转写音频；如果 provided_asr_text 存在则优先使用外部转写
  -> 聚合选择性帧 OCR + ASR 文本
  -> 调用 text-audit-service 做上下文文本审核
  -> 融合帧风险、OCR/ASR 风险、相关文本风险
  -> 输出 allow / review / block
```

当前默认启用本地 ASR，使用 `faster-whisper` 的 `tiny` 模型、CPU `int8` 推理。服务会直接读取上传的视频文件并转写音频，随后把转写文本与帧 OCR、相关文本一起送入 `text-audit-service`。如果视频没有音轨，ASR 会返回 `skipped:no_audio_stream`，图片帧和其他文本仍会继续审核。`tiny` 用于本地联调和低延迟验证；生产环境建议在网络和算力允许时切到 `base` 或 `small`。

如果上游已经有语音转写，也可以通过 `provided_asr_text` 传入；这种情况下会优先使用上游文本，不重复跑本地 ASR。

本地启动脚本会在项目根目录存在 `apikey.txt` 且环境变量未设置时读取 HuggingFace token，只写入当前进程环境变量，不会把 token 写入仓库。脚本默认设置 `HF_ENDPOINT=https://hf-mirror.com` 以便在中国网络环境下载公开模型；如需使用官方 Hub，可在启动前自行设置 `HF_ENDPOINT` 覆盖。

PySceneDetect 默认启用，作为固定 1fps 抽帧的补强层。它最多选择 8 个场景切换帧；当固定帧已达到 `max_sampled_frames` 上限时，场景帧会替换时间上最接近的固定帧，保持下游图片审核调用数稳定。
