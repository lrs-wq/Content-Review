# Image Audit Service

图片审核服务提供独立 HTTP API，用于审核头像、帖子图、评论图、截图、海报和表情包。

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8020
```

项目根目录运行 Docker Compose：

```bash
docker compose up -d image-audit-service
```

## API

JSON base64：

```bash
curl -X POST http://localhost:8020/v1/moderation/image \
  -H "Content-Type: application/json" \
  -d "{\"content_id\":\"img1\",\"user_id\":\"u1\",\"scene\":\"post_image\",\"image_base64\":\"...\"}"
```

文件上传：

```bash
curl -X POST http://localhost:8020/v1/moderation/image/upload \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "scene=post_image" \
  -F "file=@./tests/fixtures/image.jpg"
```

如果已有上游 OCR 结果，或本地暂未安装 PaddleOCR，可通过 `provided_ocr_text` 传入文本，服务会回调 `text-audit-service`：

```bash
curl -X POST http://localhost:8020/v1/moderation/image/upload \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "scene=post_image" \
  -F "provided_ocr_text=加微信免费领取" \
  -F "file=@./tests/fixtures/image.jpg"
```

## Current Pipeline

```text
图片输入
  -> 类型、大小、分辨率校验
  -> SHA256 哈希
  -> Falconsai/nsfw_image_detection：图片级 NSFW 分类
  -> NudeNet：裸露区域检测和证据框
  -> OpenCV 启发式检测：肤色大面积暴露、二维码、异常尺寸
  -> OCR：默认 PaddleOCR 可选适配器，未安装时返回 skipped
  -> OCR 文本回调 text-audit-service
  -> 风险融合，输出 allow / review / block
```

## Optional Models

当前基础版不强依赖大模型包。需要真实 OCR / 视觉模型时安装：

```bash
pip install -r requirements-model.txt
```

然后按需设置：

```bash
set IMAGE_AUDIT_ENABLE_OCR=true
set IMAGE_AUDIT_OCR_PROVIDER=paddleocr
set IMAGE_AUDIT_ENABLE_NSFW_MODEL=true
set IMAGE_AUDIT_NSFW_MODEL_NAME=storage/models/falconsai-nsfw
set IMAGE_AUDIT_NSFW_DEVICE=-1
set IMAGE_AUDIT_NSFW_DOWNLOAD_ON_REQUEST=false
set IMAGE_AUDIT_ENABLE_NUDENET=true
set IMAGE_AUDIT_ENABLE_VISION_SAFETY=true
set IMAGE_AUDIT_VISION_SAFETY_TRIGGER_MODE=gray
set IMAGE_AUDIT_VISION_SAFETY_REVIEW_ON_UNAVAILABLE=true
```

视觉层已落地四类信号：

- `scores.nsfw`：来自 `Falconsai/nsfw_image_detection`，超过阈值进入 `review` 或 `block`。
- `scores.nudity`：来自 `NudeNet`，同时在 `detections[].box` 返回裸露区域证据框。
- `scores.skin_exposure`、`scores.qr_code`、`scores.image_quality`：OpenCV/元信息启发式兜底，只作为复核信号。
- `scores.vision_safety`：可选多模态 safety 层，支持本地 ShieldGemma 2 或 Llama Guard 4/OpenAI-compatible 图文 endpoint。

模型为懒加载，服务启动时不会立刻下载。默认 `IMAGE_AUDIT_NSFW_DOWNLOAD_ON_REQUEST=false`，审核请求只加载本地模型目录，避免网络问题拖死接口。当前 Falconsai 权重目录：

```text
storage/models/falconsai-nsfw
```

如果需要重新下载或初始化，可执行预热脚本：

```powershell
D:\Anaconda3\envs\content-review-ocr\python.exe tools\prewarm_image_models.py
```

如果依赖缺失、模型未预热或模型加载失败，接口仍可返回结果，并在 `model_status.visual` 中显示错误原因。

## Multimodal Safety Layer

多模态 safety 层用于补强 Blood/Gore、Terrorism、Dangerous Content、Hate、Self-harm、Political 等 NSFW/NudeNet 难以覆盖的语义视觉风险。当前启用 `trigger_mode=gray`，只审灰区，不做全量调用。若模型暂不可用，灰区图片会以 `vision_safety_unavailable` 进入 `review`，避免继续放行。

本地 ShieldGemma 2：

```powershell
# 权重已下载到：storage/models/shieldgemma-2-4b-it
D:\Anaconda3\envs\content-review-ocr\python.exe tools\prewarm_vision_safety_model.py --provider shieldgemma2_local --model-name storage/models/shieldgemma-2-4b-it --device auto
set IMAGE_AUDIT_ENABLE_VISION_SAFETY=true
set IMAGE_AUDIT_VISION_SAFETY_PROVIDER=shieldgemma2_local
set IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME=storage/models/shieldgemma-2-4b-it
set IMAGE_AUDIT_VISION_SAFETY_DEVICE=auto
set IMAGE_AUDIT_VISION_SAFETY_ALLOW_CPU=false
set IMAGE_AUDIT_VISION_SAFETY_TRIGGER_MODE=gray
set IMAGE_AUDIT_VISION_SAFETY_REVIEW_ON_UNAVAILABLE=true
```

当前 `content-review-ocr` 环境已安装 CUDA 版 PyTorch：`torch 2.11.0+cu128`、`torchvision 0.26.0+cu128`、`torchaudio 2.11.0+cu128`，`torch.cuda.is_available()` 为 true。RTX 4060 8GB 可通过 `device=auto` 加载 ShieldGemma 2；首次灰区请求约 13 秒，加载后显存占用约 7.7GB/8GB。若 CUDA 不可用，同步接口仍会按配置拒绝 CPU 推理，灰区图片进入 `review` 并标记 `vision_safety_unavailable`。

Llama Guard 4 或远程 VLM 服务：

```powershell
set IMAGE_AUDIT_ENABLE_VISION_SAFETY=true
set IMAGE_AUDIT_VISION_SAFETY_PROVIDER=llama_guard4_openai
set IMAGE_AUDIT_VISION_SAFETY_ENDPOINT_URL=http://127.0.0.1:9000/v1/chat/completions
set IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME=meta-llama/Llama-Guard-4-12B
```

`trigger_mode=gray` 表示只审灰区；测试或离线评估时可改为 `all`。也可以在请求 `context` 里传入 `"force_vision_safety": true` 强制二审单张图片。

## Windows PaddleOCR Deployment

当前 Windows 本地已部署独立 conda 环境：

```text
D:\Anaconda3\envs\content-review-ocr
```

部署命令：

```powershell
conda create -n content-review-ocr python=3.11 -y
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install -r services\image-audit\requirements.txt
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install paddleocr
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install -r services\image-audit\requirements-model.txt
D:\Anaconda3\envs\content-review-ocr\python.exe tools\prewarm_image_models.py
```

Windows CPU 环境需要关闭 PaddleX 默认 MKLDNN/oneDNN 后端，否则 PaddlePaddle 3.3.x 在部分机器上会触发 PIR 转换错误。服务代码已默认设置：

```text
PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
```

启动已部署的 PaddleOCR 图片审核服务：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_image_audit_paddleocr.ps1
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8020/health
```

健康检查中应看到：

```json
{
  "visual_status": "heuristic:enabled,nsfw_model:configured:D:\\gogelila\\Content_Review\\storage\\models\\falconsai-nsfw:local_cache_only,nudenet:configured:nudenet",
  "ocr_status": "enabled:paddleocr"
}
```
