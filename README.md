# 社区敏感内容 AI 审核方案

本项目面向社区 UGC 内容审核，覆盖文字、图片、视频三类内容。整体设计采用“分开设计、分开运行、统一接口接入”的方式：文字、图片、视频分别作为独立审核服务部署，业务侧通过 HTTP API 调用统一网关或直接调用各服务。

## 方案结论

开源方案中不建议选择某一个“一站式审核框架”作为最终方案。更稳妥的最优组合是：

| 审核对象 | 推荐开源组件 | 作用 |
|---|---|---|
| 文字 | houbb/sensitive-word + thu-coai/roberta-base-cold | 敏感词、广告导流、联系方式、辱骂/攻击性语言初筛 |
| 图片 | PaddleOCR + Falconsai/nsfw_image_detection + NudeNet | 图片 OCR、NSFW 分类、裸露区域检测和局部打码 |
| 视频 | FFmpeg 固定抽帧 + PySceneDetect 场景补强 + 图片审核服务 + faster-whisper + 文字审核服务 | 视频抽帧、场景切换帧审核、音频转写、字幕/语音文本审核 |
| 灰区二审 | ShieldGemma 2 或 Llama Guard 4 | 高风险或不确定内容的多模态二次判断 |

核心原则：

- 文字审核不只靠敏感词，必须叠加语义模型和人工复核。
- 图片审核不只做 NSFW，必须做 OCR，否则截图、海报、表情包和二维码旁文字容易漏判。
- 视频审核不单独训练视频模型，第一版按“抽帧 + OCR + 图片审核 + 音频 ASR + 文本审核”拆解，成本和可解释性更好。
- 高风险直接拦截，中风险进入人工审核，低风险放行并保留日志。

## 分层审核架构

当前项目不应长期停留在“敏感词枚举匹配”阶段。正式方案采用分层审核：低成本规则负责快速拦截明确风险，小模型负责语义分类，上下文聚合负责补全信息，小型 agent 只处理灰区和复杂上下文，人工复核兜底，样本回流持续优化。

```text
用户提交内容
  |
  |-- 原始文本：评论 / 帖子 / 私信 / 昵称 / 简介
  |-- 图片文本：OCR 识别结果 / 二维码旁文本 / 海报和截图文字
  |-- 视频文本：标题 / 简介 / 字幕 / ASR 语音转写 / 关键帧 OCR
  |-- 业务上下文：父评论 / 帖子标题 / 最近对话 / 用户历史风险 / 场景
  |
上下文聚合 context-builder
  |
  |-- 第 1 层：规则模板，毫秒级拦明显违规
  |-- 第 2 层：小模型分类，判断辱骂、暴力、广告、诈骗等语义风险
  |-- 第 3 层：上下文聚合，原文 + 父评论 + 标题 + OCR + ASR
  |-- 第 4 层：小型 agent，只审灰区和复杂上下文
  |-- 第 5 层：人工复核，中高风险兜底
  |-- 第 6 层：样本回流，持续优化词库、规则、模型和阈值
```

各层职责：

| 层级 | 作用 | 典型耗时 | 是否全量执行 | 说明 |
|---|---|---:|---|---|
| 规则模板 | 拦截明确违规、广告导流、联系方式、暴力意图模板 | 毫秒级 | 是 | 不只枚举词，还要支持“动词 + 对象”等模板，例如暴力动词 + 人/动物/代词/名词 |
| 小模型分类 | 判断辱骂、暴力、广告、诈骗、色情交易等语义风险 | 10-200ms | 是或按场景执行 | 解决词库无法枚举的问题，但需要用真实样本调阈值 |
| 上下文聚合 | 合并原文、父评论、标题、图片 OCR、视频 ASR、用户历史风险 | 毫秒级到百毫秒级 | 是 | 输出统一审核文本包，供模型和 agent 使用 |
| 小型 agent | 处理隐晦表达、反讽、图文/多轮上下文、灰区内容 | 300ms-3s+ | 否 | 只处理灰区和复杂上下文，不建议全量同步调用 |
| 人工复核 | 处理中高风险、争议内容、申诉内容 | 分钟级 | 否 | 保证合规和误杀控制 |
| 样本回流 | 沉淀误杀、漏判、申诉、举报和人审结果 | 离线 | 是 | 用于更新词库、规则模板、模型阈值和训练样本 |

统一文本包示例：

```json
{
  "scene": "post",
  "text": "用户原文",
  "image_ocr_text": [
    "图片 OCR 文本"
  ],
  "video_transcript": "视频 ASR 转写文本或命中片段摘要",
  "context": {
    "title": "帖子标题",
    "parent_comment": "父评论",
    "recent_messages": ["最近对话"],
    "user_risk_level": "low"
  }
}
```

决策原则：

- 明确高危规则命中：直接 `block` 或高优先级人审。
- 规则命中但可能误杀：进入 `review`，结合上下文判断。
- 小模型高分且规则也命中：提高风险等级。
- 只有单个低置信信号：放行并抽检。
- agent 只在规则和小模型无法明确判断时调用。
- 人审和申诉结果必须回流，形成下一轮规则、样本和阈值更新。

## 项目架构

```text
业务系统 / App / 管理后台
  |
  |-- POST /v1/moderation/text
  |-- POST /v1/moderation/image
  |-- POST /v1/moderation/video
  |
审核网关 audit-gateway（已落地；默认端口 8040，统一转发文本/图片/视频审核并查询异步结果）
  |
  |-- text-audit-service
  |     |-- 文本归一化
  |     |-- 敏感词/白名单/黑名单
  |     |-- 中文攻击性语言模型
  |
  |-- image-audit-service
  |     |-- 图片解码和基础校验
  |     |-- NSFW 分类
  |     |-- NudeNet 区域检测
  |     |-- OCR 识别图中文字
  |     |-- OCR 文本回调 text-audit-service
  |
  |-- video-audit-service
        |-- 视频元信息解析
        |-- FFmpeg 固定 1fps 抽帧
        |-- PySceneDetect 场景切换帧补强
        |-- 关键帧回调 image-audit-service
        |-- 音频提取
        |-- faster-whisper 语音转写
        |-- 转写文本回调 text-audit-service

基础设施
  |-- PostgreSQL/MySQL：审核记录、策略版本、申诉、人审结果
  |-- Redis：任务状态、限流、缓存
  |-- 对象存储：原始文件、抽帧、打码结果、证据快照
  |-- MQ：视频异步任务、人工复核队列、样本回流
```

推荐服务拆分：

| 服务 | 默认端口 | 运行方式 | 说明 |
|---|---:|---|---|
| audit-gateway | 8040 | API 网关，已落地 | 统一文本、图片、视频入口，按 `content_type` 或文件 MIME 转发到 8010/8020/8030；同端口查询异步结果 |
| text-audit-service | 8010 | 独立服务 | 可用 Java/Spring Boot 集成 houbb，也可封装为 HTTP 规则服务 |
| image-audit-service | 8020 | 独立服务 | 推荐 Python/FastAPI，便于加载 OCR 和视觉模型 |
| video-audit-service | 8030 | 独立服务 | 推荐 Python/FastAPI + 异步任务队列 |
| review-admin | 规划中 | 可选 | 人工审核、申诉、样本回流、策略配置 |

### 简要响应

文字、图片和视频审核接口默认开启简要响应，返回业务标识、审核结果、风险等级和原因：

```json
{
  "client_elapsed_ms": 144.5,
  "content_id": "content_001",
  "result": "review",
  "action": "review",
  "risk_level": "medium",
  "reason": "命中规则 暴力风险:杀人；风险标签 暴力风险"
}
```

返回约定：默认业务响应固定为 `content_id`、`result`、`action`、`risk_level`、`reason`；测试页展示时会额外补 `client_elapsed_ms`。`result/action/risk_level` 保留英文机器码，`reason` 默认返回中文，用户原文、OCR 文本、ASR 文本、命中词和证据片段保留原文。完整调试响应 `brief=false` 才返回更多模型分数和证据字段。

需要调试完整链路时传入 `brief=false`。JSON 接口可放在 query 或请求体中；multipart 上传接口使用 query，例如：

```bash
curl -X POST "http://127.0.0.1:8030/v1/moderation/video/upload?brief=false" \
  -F "content_id=video1" \
  -F "user_id=u1" \
  -F "file=@./sample.mp4"
```

## 目录结构建议

```text
Content_Review/
  README.md
  docker-compose.yml
  configs/
    policy.yaml
    thresholds.yaml
    sensitive_terms.csv
    fwwdn_terms.csv
    political_terms.csv
    allow_terms.csv
  services/
    gateway/
    text-audit/
    image-audit/
    video-audit/
    review-admin/
  shared/
    schemas/
    clients/
    policy/
  storage/
    samples/
    frames/
    reports/
  tests/
    fixtures/
    replay/
```

## 文字审核设计

文字审核服务负责评论、帖子、私信、昵称、简介、OCR 结果、视频语音转写结果。

处理流程：

```text
文本包：原始文本 + 图片 OCR 文本 + 视频 ASR 文本 + 业务上下文
  -> 文本归一化：繁简、大小写、全半角、空格、符号、emoji、拼音/谐音
  -> 上下文聚合：标题、父评论、最近对话、用户历史风险、内容场景
  -> 白名单判断
  -> 敏感词、正则和规则模板命中
  -> 小模型语义分类：辱骂、暴力、广告、诈骗、色情交易
  -> 灰区内容进入小型 agent 二审
  -> 风险融合
  -> 输出 allow / review / block
```

推荐规则：

| 风险 | 处理 |
|---|---|
| 明确违法、诈骗、色情交易、黑产导流 | 直接 block 或进入高优先级人审 |
| 辱骂、攻击性语言、争议表达 | 中高分 review，极高分 block |
| 疑似广告、联系方式变体 | 结合账号历史和频率判断 |
| 新闻、医学、法律、艺术等易误杀场景 | 白名单和上下文策略优先 |

文字接口：

```http
POST /v1/moderation/text
Content-Type: application/json
```

```json
{
  "content_id": "post_10001",
  "user_id": "u_123",
  "scene": "comment",
  "text": "待审核文本",
  "context": {
    "post_id": "p_1",
    "reply_to": "u_456"
  }
}
```

响应：

```json
{
  "trace_id": "tr_20260624_001",
  "content_id": "post_10001",
  "risk_level": "medium",
  "action": "review",
  "labels": ["offensive"],
  "scores": {
    "rule": 0.72,
    "offensive": 0.81
  },
  "hits": [
    {
      "type": "term",
      "category": "insult",
      "term": "***"
    }
  ],
  "policy_version": "2026.06.24"
}
```

## 图片审核设计

图片审核服务负责头像、帖子图片、评论图片、表情包、截图、海报。

处理流程：

```text
原始图片
  -> 文件类型、大小、分辨率校验
  -> 图片哈希去重
  -> Falconsai/nsfw_image_detection 做 NSFW 图片分类
  -> NudeNet 做裸露区域检测，返回证据框
  -> OpenCV 启发式兜底：肤色暴露、二维码、异常尺寸
  -> OCR 识别图中文字，当前支持 PaddleOCR 可选适配器
  -> OCR 文本调用文字审核
  -> 风险融合
  -> 输出 allow / review / block / mask
```

推荐策略：

| 风险 | 处理 |
|---|---|
| 明显色情/裸露 | block，必要时生成打码版本 |
| OCR 命中高危文本 | 按文字审核结果处理 |
| 二维码、联系方式、广告水印 | review 或 block，结合业务场景 |
| 泳装、健身、医学、艺术图 | 默认 review，避免高误杀 |
| 暴力血腥、危险物品 | 第一版可进入人审，后续接 ShieldGemma 2 等模型补强 |

图片接口：

```http
POST /v1/moderation/image/upload
Content-Type: multipart/form-data
```

也支持 JSON 调用：

```http
POST /v1/moderation/image
Content-Type: application/json
```

字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `content_id` | 是 | 业务内容 ID |
| `user_id` | 是 | 用户 ID |
| `scene` | 是 | `avatar`、`post_image`、`comment_image` 等 |
| `file` | 否 | 图片文件，上传接口使用 |
| `image_base64` | 否 | base64 图片，JSON 接口使用 |
| `image_url` | 否 | 图片地址，JSON 接口使用 |
| `related_text` | 否 | 图片对应标题、帖子正文或评论 |
| `provided_ocr_text` | 否 | 已有 OCR 文本；本地未安装 OCR 或上游已做 OCR 时可直接传入 |

第一版已落地在 `services/image-audit`：

- `GET /health`：健康检查，返回视觉检测、OCR、文本审核回调状态。
- `POST /v1/moderation/image`：JSON 图片审核，支持 `image_base64` 或 `image_url`。
- `POST /v1/moderation/image/upload`：文件上传审核，支持 `provided_ocr_text`。
- 视觉层已接入 `Falconsai/nsfw_image_detection` 和 `NudeNet`；Falconsai 权重已下载到 `storage/models/falconsai-nsfw`，服务默认从本地目录加载。
- OCR 文本会回调 `text-audit-service`，默认地址为 `http://127.0.0.1:8010/v1/moderation/text`。
- 已部署 PaddleOCR 时，OCR 状态为 `enabled:paddleocr`；未安装 PaddleOCR 时，OCR 状态为 `skipped`，接口仍可运行，也可用 `provided_ocr_text` 验证图中文字审核链路。

Windows 本地 PaddleOCR 部署：

```powershell
conda create -n content-review-ocr python=3.11 -y
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install -r services\image-audit\requirements.txt
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install paddlepaddle -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install paddleocr
D:\Anaconda3\envs\content-review-ocr\python.exe -m pip install -r services\image-audit\requirements-model.txt
D:\Anaconda3\envs\content-review-ocr\python.exe tools\prewarm_image_models.py
D:\Anaconda3\envs\content-review-ocr\python.exe tools\prewarm_vision_safety_model.py --help
powershell -ExecutionPolicy Bypass -File tools\start_image_audit_paddleocr.ps1
```

当前本地模型文件：

```text
storage/models/falconsai-nsfw/config.json
storage/models/falconsai-nsfw/preprocessor_config.json
storage/models/falconsai-nsfw/model.safetensors
```

当前 Windows CPU 部署需要关闭 PaddleX 默认 MKLDNN/oneDNN 后端，项目已在 OCR 引擎中默认设置 `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0`，避免 PaddlePaddle 3.3.x 的 CPU 推理兼容问题。

视觉模型部署说明：

- `Falconsai/nsfw_image_detection`：图片级 NSFW/SFW 分类，输出 `scores.nsfw`，超过 `nsfw_review_score` 进入复核，超过 `nsfw_block_score` 拦截。
- `NudeNet`：裸露区域检测，输出 `scores.nudity` 和 `detections[].box`，超过 `nudity_review_score` 进入复核，超过 `nudity_block_score` 拦截。
- `OpenCV` 启发式：只作为兜底 review 信号，结果写入 `skin_exposure`、`qr_code`、`image_quality`，不再把肤色启发式直接当成 NSFW 结论。
- `vision_safety` 多模态层：已接入 `shieldgemma2_local` 和 OpenAI-compatible 图文接口，可用于 ShieldGemma 2 或 Llama Guard 4 二审；当前启用灰区二审，不做全量调用。
- 默认不在审核请求里下载 HuggingFace 模型，避免网络问题拖死接口；本地权重目录存在时会直接离线加载。

多模态 safety 层启用方式：

```powershell
# 本地 ShieldGemma 2，权重已下载到 storage/models/shieldgemma-2-4b-it
$env:IMAGE_AUDIT_ENABLE_VISION_SAFETY="true"
$env:IMAGE_AUDIT_VISION_SAFETY_PROVIDER="shieldgemma2_local"
$env:IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME="storage/models/shieldgemma-2-4b-it"
$env:IMAGE_AUDIT_VISION_SAFETY_DEVICE="auto"
$env:IMAGE_AUDIT_VISION_SAFETY_ALLOW_CPU="false"

# Llama Guard 4 或其它 VLM 服务，要求服务兼容 /v1/chat/completions 图文接口
$env:IMAGE_AUDIT_ENABLE_VISION_SAFETY="true"
$env:IMAGE_AUDIT_VISION_SAFETY_PROVIDER="llama_guard4_openai"
$env:IMAGE_AUDIT_VISION_SAFETY_ENDPOINT_URL="http://127.0.0.1:9000/v1/chat/completions"
$env:IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME="meta-llama/Llama-Guard-4-12B"
```

ShieldGemma 2 本地权重已下载完成，约 8.05GiB。当前 `content-review-ocr` 环境已安装 CUDA 版 PyTorch：`torch 2.11.0+cu128`、`torchvision 0.26.0+cu128`、`torchaudio 2.11.0+cu128`，`torch.cuda.is_available()` 为 true。本机 RTX 4060 8GB 可通过 `device=auto` 加载 ShieldGemma2，实测首次灰区请求约 13 秒，加载后显存占用约 7.7GB/8GB，余量很小。Llama Guard 4 权重约 24GB，生产建议作为独立 GPU 服务部署，再通过 endpoint 接入图片审核服务。

响应：

```json
{
  "trace_id": "img_tr_20260625_002",
  "content_id": "img_10001",
  "risk_level": "high",
  "action": "block",
  "labels": ["nsfw", "ocr_sensitive"],
  "scores": {
    "nsfw": 0.94,
    "nudity": 0.88,
    "ocr_text": 0.76
  },
  "image": {
    "width": 1080,
    "height": 720,
    "format": "JPEG",
    "sha256": "..."
  },
  "ocr": {
    "status": "ok",
    "text": "图片中识别出的文字",
    "provider": "paddleocr"
  },
  "text_review": {
    "used": true,
    "action": "review",
    "labels": ["ad"]
  },
  "detections": [
    {
      "label": "nudity",
      "score": 0.91,
      "source": "nudenet",
      "box": [120, 80, 240, 260],
      "evidence": "FEMALE_BREAST_EXPOSED"
    }
  ],
  "policy_version": "2026.06.24"
}
```

## 视频审核设计

视频审核建议采用异步任务。视频文件通常较大，且需要抽帧、OCR、音频转写和多次模型调用，同步接口容易超时。

处理流程：

```text
原始视频
  -> 元信息解析：时长、分辨率、码率、音轨
  -> 抽帧：固定间隔抽帧 + 场景切换关键帧
  -> 每帧调用 image-audit-service
  -> 提取音频
  -> faster-whisper 语音转文字
  -> 转写文本调用 text-audit-service
  -> 聚合帧风险、OCR 风险、语音文本风险
  -> 输出 allow / review / block
```

抽帧建议：

| 视频长度 | 抽帧策略 |
|---|---|
| 小于 30 秒 | 每 1 秒 1 帧 + 场景切换帧 |
| 30 秒到 5 分钟 | 每 2-3 秒 1 帧 + 场景切换帧 |
| 大于 5 分钟 | 每 5 秒 1 帧 + 场景切换帧 + 首尾关键帧 |
| 直播/长视频 | 按时间窗口切片，边抽帧边审核 |

视频提交接口：

```http
POST /v1/moderation/video
Content-Type: application/json
```

```json
{
  "content_id": "video_10001",
  "user_id": "u_123",
  "scene": "post_video",
  "video_url": "https://example.com/video.mp4",
  "related_text": "视频标题或帖子正文",
  "callback_url": "https://biz.example.com/moderation/callback"
}
```

提交响应：

```json
{
  "trace_id": "tr_20260624_003",
  "task_id": "task_video_10001",
  "status": "queued"
}
```

查询接口：

```http
GET /v1/moderation/tasks/{task_id}
```

结果响应：

```json
{
  "task_id": "task_video_10001",
  "content_id": "video_10001",
  "status": "finished",
  "risk_level": "medium",
  "action": "review",
  "labels": ["frame_nsfw", "speech_sensitive"],
  "evidence": {
    "frames": [
      {
        "timestamp": 12.4,
        "risk_level": "high",
        "labels": ["nsfw"],
        "snapshot_url": "oss://review-evidence/video_10001/0012.jpg"
      }
    ],
    "transcript": "音频转写文本片段",
    "ocr_text": "关键帧 OCR 文本"
  },
  "policy_version": "2026.06.24"
}
```

当前已落地第一版同步上传服务，目录为 `services/video-audit`，默认端口 `8030`。该版本用于本地联调和小文件审核，强制限制视频时长不超过 60 秒：

```text
POST /v1/moderation/video/upload
Content-Type: multipart/form-data
```

字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `content_id` | 是 | 业务内容 ID |
| `user_id` | 是 | 用户 ID |
| `scene` | 否 | 默认 `general`，如 `post_video` |
| `file` | 是 | 视频文件，默认支持 mp4/mov/webm/mkv/avi |
| `related_text` | 否 | 视频标题、正文、评论上下文 |
| `provided_asr_text` | 否 | 上游已有 ASR 转写文本；存在时优先使用，不重复跑本地 ASR；未提供且视频有音轨时会自动用 faster-whisper 转写 |
| `skip_ocr` | 否 | 是否让帧图片审核跳过 OCR |
| `context` | 否 | JSON 对象字符串 |

执行逻辑：

```text
上传视频
  -> ffprobe 校验格式、时长、分辨率、编码
  -> duration > 60s 直接返回 video_too_long
  -> ffmpeg 按 1 fps 抽帧，最多 60 帧
  -> PySceneDetect 检测场景切换帧，并替换附近固定帧补强覆盖
  -> 每帧先调用 image-audit-service，默认跳过 OCR
  -> 仅首帧/明显文字区域/二维码或风险帧在配额内开启 OCR
  -> faster-whisper 自动转写音频，若 provided_asr_text 存在则优先使用外部转写，无音轨则跳过 ASR
  -> 聚合帧 OCR 文本 + ASR 文本
  -> 调用 text-audit-service
  -> 融合帧风险和文本风险，输出 allow / review / block
```

启动：

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_video_audit.ps1
```

ASR 默认配置：

- 本地开发默认启用 `faster-whisper`，模型为 `tiny`、`cpu`、`int8`，用于先保证同步接口可运行和低延迟验证。
- 如果视频没有音轨，返回 `asr.status=skipped:no_audio_stream`，不会加载 ASR 模型。
- 如果请求传入 `provided_asr_text`，优先使用外部转写文本，不重复跑本地 ASR。
- `tools\start_video_audit.ps1` 会在存在 `apikey.txt` 且环境变量未设置时读取 HuggingFace token 到当前进程环境；该文件已被 `.gitignore` 排除。
- 中国网络环境下脚本默认设置 `HF_ENDPOINT=https://hf-mirror.com` 下载公开 faster-whisper 权重；需要官方 Hub 时可提前设置 `HF_ENDPOINT` 覆盖。

抽帧默认配置：

- 固定抽帧：`frame_sample_fps=1`，`max_sampled_frames=60`。
- 场景补强：默认启用 PySceneDetect，`threshold=27`，最多选 `8` 个场景切换帧。
- 合并策略：场景切换帧优先；当固定帧已经达到 60 帧上限时，场景帧会替换时间上最接近的固定帧，避免下游图片审核调用数突然增大。

测试：

```powershell
D:\Anaconda3\envs\content-review-ocr\python.exe tests\replay\video_audit_smoke.py
```

调用示例：

```bash
curl -X POST http://127.0.0.1:8030/v1/moderation/video/upload \
  -F "content_id=v1" \
  -F "user_id=u1" \
  -F "scene=post_video" \
  -F "related_text=视频标题或正文" \
  -F "provided_asr_text=" \
  -F "skip_ocr=true" \
  -F "context={}" \
  -F "file=@sample.mp4"
```

## 风险决策模型

所有服务统一输出三类动作：

| 动作 | 说明 |
|---|---|
| `allow` | 放行，保留日志并可抽检 |
| `review` | 进入人工审核队列 |
| `block` | 拦截、隐藏或禁止发布 |

推荐阈值从保守值开始，后续通过样本回放调整：

```yaml
text:
  block_score: 0.92
  review_score: 0.65
image:
  nsfw_block_score: 0.90
  nsfw_review_score: 0.60
  skin_review_score: 0.70
  qr_review_score: 0.65
  ocr_review_score: 0.65
  vision_safety:
    enabled: true
    provider: "shieldgemma2_local"
    trigger_mode: "gray"
    review_on_unavailable: true
  text_audit_url: "http://127.0.0.1:8010/v1/moderation/text"
video:
  frame_block_ratio: 0.05
  frame_review_ratio: 0.02
  speech_review_score: 0.65
```

融合规则示例：

```text
任一高危规则命中 -> block
NSFW 分数 >= block_score -> block
OCR 文本或语音文本高危 -> block
多个中风险信号同时出现 -> review
只有单个低置信信号 -> allow + 抽检
```

## 数据库设计

最少需要以下表：

| 表 | 说明 |
|---|---|
| `review_cases` | 每次审核请求、结果、动作、证据索引 |
| `review_events` | 模型分数、规则命中、OCR 结果、抽帧结果 |
| `sensitive_terms` | 敏感词、类别、等级、状态 |
| `allow_terms` | 白名单词、适用场景、原因 |
| `policy_versions` | 策略版本、阈值、词库版本、上线时间 |
| `manual_reviews` | 人审任务、审核员、结论、原因 |
| `appeals` | 用户申诉、复核结果、误杀原因 |
| `model_samples` | 可用于评估/训练的样本索引和标签 |

## 中国场景政治敏感配置

如果业务运行在中国语境下，需要把涉政、公共事务、领导人姓名、别名、谐音、机构名、重大事件和监管要求作为独立高风险类目处理。不要把这类内容混在普通辱骂或广告词库里，否则会难以审计、难以灰度、也难以回滚。

项目已内置独立政治敏感词库：

```text
configs/political_terms.csv
```

建议维护方式：

- 领导人姓名、别名、谐音、简称、拼音缩写单独维护。
- 机构名、职务名、重大公共事件、监管阶段性要求单独维护。
- 领导人姓名、别名、简称和常见称谓默认使用 `political / high / block`，直接拦截。
- 机构名、职务名、重大事件、地区公共议题默认仍使用 `review`，进入人工复核。
- 新闻、历史、政策解读、法律讨论、官方公告等内容应通过白名单和上下文策略降低误杀。
- 每次词库更新必须记录版本、来源、变更人和回滚点。

词库格式：

```csv
term,category,risk_level,match_type,action,enabled,notes
领导人姓名占位,political,high,compact,block,true,replace with maintained leader names and aliases
```

服务启动时会同时加载：

```text
configs/sensitive_terms.csv
configs/political_terms.csv
configs/fwwdn_terms.csv
configs/dirty_cnwords_curse_terms.csv
configs/oral_vulgar_terms.csv
```

如需加载更多垂直词库，可设置环境变量：

```bash
EXTRA_TERMS_PATHS="D:\path\terms_a.csv;D:\path\terms_b.csv"
```

政治词库变更后可运行回归测试：

```bash
python tools/run_political_terms_report.py
```

报告输出：

```text
storage/reports/political_terms_report_latest.md
storage/reports/political_terms_report_latest.json
```

## 公开词库导入

项目支持把 [fwwdn/sensitive-stop-words](https://github.com/fwwdn/sensitive-stop-words) 导入为运行时规则词库。导入脚本会下载广告、色情类、涉枪涉爆违法信息关键词、网址、政治类 5 个文件，生成独立词库：

```text
configs/fwwdn_terms.csv
```

执行导入：

```bash
python tools/import_fwwdn_terms.py --refresh
```

默认映射策略：

| 来源 | category | risk_level | action |
|---|---|---|---|
| 广告.txt | ad | medium | review |
| 色情类.txt | adult | high | block |
| 涉枪涉爆违法信息关键词.txt | weapon | high | block |
| 网址.txt | url | medium | review |
| 政治类.txt | political | high | review |

导入脚本会跳过 `configs/sensitive_terms.csv` 和 `configs/political_terms.csv` 已有词，避免同一词在核心业务词库和外部公开词库里重复命中。导入报告输出：

```text
storage/reports/fwwdn_terms_import_latest.json
```

辱骂/低俗口头语可从 [dablelv/dirty-cnwords](https://github.com/dablelv/dirty-cnwords) 的 `curse/all.txt` 导入。该仓库未在抓取时发现明确 LICENSE 文件，上线或对外分发前需要再确认授权；本项目把导入内容单独放在独立 CSV，方便替换、禁用或回滚：

```bash
python tools/import_dirty_cnwords_curse_terms.py --refresh
```

生成的词库默认会随服务启动加载：

```text
configs/dirty_cnwords_curse_terms.csv
```

项目还维护了一份自有低俗口头语变体词库，用于覆盖 `小八嘎`、`baka`、`ばか` 等前后缀、假名和罗马音变体：

```text
configs/oral_vulgar_terms.csv
```

低俗口头语和导入的辱骂词默认使用 `high/review`，表示高风险但先进入复核，不直接拦截。

审核日志必须记录：

- 请求 ID、内容 ID、用户 ID、场景。
- 命中的规则、词库版本、模型版本、模型分数。
- 最终动作、决策原因、策略版本。
- 人审结果、申诉结果、样本回流状态。

## 执行方式

当前 README 定义目标架构。实际落地时建议使用 Docker Compose 分别启动服务。

### 1. 准备模型和配置

```bash
mkdir -p models configs storage/samples storage/frames storage/reports
```

需要准备：

- `configs/sensitive_terms.csv`：敏感词、广告词、黑产词、导流词。
- `configs/fwwdn_terms.csv`：从 fwwdn/sensitive-stop-words 导入的公开词库。
- `configs/political_terms.csv`：中国场景政治敏感词库。
- `configs/dirty_cnwords_curse_terms.csv`：从 dablelv/dirty-cnwords 导入的辱骂低俗词库。
- `configs/oral_vulgar_terms.csv`：本项目维护的低俗口头语和变体词库。
- `configs/allow_terms.csv`：白名单词。
- `configs/policy.yaml`：风险标签和处置策略。
- `configs/thresholds.yaml`：各模型阈值。
- `models/`：文本模型、图片模型、OCR 模型、ASR 模型缓存目录。

### 2. 分别启动服务

```bash
docker compose up -d text-audit-service
docker compose up -d image-audit-service
docker compose up -d video-audit-service
docker compose up -d gateway-service
```

如果本地开发，不通过 Docker，也建议固定端口运行。文本服务可直接启动：

```bash
cd services/text-audit
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

图片和视频服务建议使用项目脚本启动，脚本会设置 OCR、视觉模型、ASR、HuggingFace 镜像和端口重启逻辑：

```bash
powershell -ExecutionPolicy Bypass -File tools\start_image_audit_paddleocr.ps1
```

```bash
powershell -ExecutionPolicy Bypass -File tools\start_video_audit.ps1
```

```bash
powershell -ExecutionPolicy Bypass -File tools\start_gateway.ps1
```

### 3. 接口调用示例

统一审核入口（推荐业务侧调用，默认端口 `8040`）：

```bash
curl -X POST http://localhost:8040/v1/moderation \
  -H "Content-Type: application/json" \
  -d '{"content_type":"text","content_id":"c1","user_id":"u1","scene":"comment","text":"待审核文本","context":{}}'
```

`content_id` 可以不传；不传时 8040 会自动生成并在响应中返回。

异步提交接口会立即返回 `content_id`，客户端继续在 8040 同端口轮询：

```bash
curl -X POST http://localhost:8040/v1/moderation/async \
  -H "Content-Type: application/json" \
  -d '{"content_type":"text","user_id":"u1","scene":"comment","text":"待审核文本","context":{}}'
```

```bash
curl http://localhost:8040/v1/moderation/result/{content_id}
```

轮询返回 `queued`、`processing`、`completed`、`failed` 或 `not_found`；`completed` 时 `result` 字段就是最终审核结果。

图片和视频也走同一个路径，通过 `content_type` 或上传文件 MIME 自动识别：

```bash
curl -X POST http://localhost:8040/v1/moderation \
  -F "content_type=image" \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "skip_ocr=false" \
  -F "context={}" \
  -F "file=@./sample.jpg"
```

文字审核：

```bash
curl -X POST http://localhost:8010/v1/moderation/text \
  -H "Content-Type: application/json" \
  -d '{"content_id":"c1","user_id":"u1","scene":"comment","text":"待审核文本"}'
```

图片审核：

```bash
curl -X POST http://localhost:8020/v1/moderation/image/upload \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "scene=post_image" \
  -F "file=@./tests/fixtures/image.jpg"
```

如果本地暂未安装 PaddleOCR，可先传入已有 OCR 文本验证链路：

```bash
curl -X POST http://localhost:8020/v1/moderation/image/upload \
  -F "content_id=img1" \
  -F "user_id=u1" \
  -F "scene=post_image" \
  -F "provided_ocr_text=加微信免费领取，日赚500不是梦" \
  -F "file=@./tests/fixtures/image.jpg"
```

视频审核：

```bash
curl -X POST http://localhost:8030/v1/moderation/video/upload \
  -F "content_id=v1" \
  -F "user_id=u1" \
  -F "scene=post_video" \
  -F "related_text=视频标题或正文" \
  -F "provided_asr_text=" \
  -F "skip_ocr=true" \
  -F "context={}" \
  -F "file=@./sample.mp4"
```

### 4. 可视化内容审核测试台

项目内置一个轻量测试页，可以测试文本、图片、视频三类接口：文本支持图片 OCR/视频 ASR 上下文，图片支持文件上传和已有 OCR 文本，视频支持文件上传、已有 ASR 文本和强制跳过帧 OCR。测试页默认使用 `8040` 异步提交和同端口轮询查询，会分别展示立即返回和最终轮询返回；取消异步模式后可直连 `8010/8020/8030` 做单服务调试。

```bash
python tools/text-audit-ui/serve.py --host 0.0.0.0 --port 8050
```

浏览器访问：

```text
http://127.0.0.1:8050/
http://192.168.1.200:8050/
```

### 5. 公开词库抽样测试

项目提供词库测试脚本，会下载公开词库/语料，抽样调用 `text-audit-service`，生成覆盖率、误放/误审和耗时报告。

先训练小模型分类层：

```bash
python tools/train_text_classifier.py
```

训练产物：

```text
storage/models/text-classifier/text_classifier.joblib
storage/reports/text_classifier_train_report_latest.json
```

再运行词库测试：

```bash
python tools/run_lexicon_report.py
```

报告输出：

```text
storage/reports/text_audit_lexicon_report_latest.md
storage/reports/text_audit_lexicon_report_latest.json
```

### 6. 图片综合安全测试

项目提供 C4Censor / UnsafeBench 评测脚本。C4Censor 会自动从 Figshare 下载 `Dataset.tar` 并按子类抽样或全量调用 `image-audit-service`；UnsafeBench 是 HuggingFace gated dataset，需要先在页面接受 DUA 并提供授权 token，否则脚本会记录为跳过。

运行 C4Censor 完整 600 张测试，跳过 OCR、只测视觉层：

```bash
D:\Anaconda3\envs\content-review-ocr\python.exe tools/run_image_safety_report.py --limit-per-subclass 50 --skip-ocr
```

快速抽样：

```bash
D:\Anaconda3\envs\content-review-ocr\python.exe tools/run_image_safety_report.py --limit-per-subclass 10 --skip-ocr
```

如果要同时尝试 UnsafeBench，需要先在 HuggingFace 数据集页面接受 DUA，并提供有权限的 token：

```bash
D:\Anaconda3\envs\content-review-ocr\python.exe tools/run_image_safety_report.py --include-unsafebench --hf-token-file apikey.txt --skip-ocr
```

如果 token 未授权，脚本会跳过 UnsafeBench，并在报告中记录 `skipped:download_or_read_failed`，不会打印或写入 token。

报告输出：

```text
storage/reports/image_safety_report_latest.md
storage/reports/image_safety_report_latest.json
```

注意：C4Censor 和 UnsafeBench 包含成人、暴力、恐怖主义等显式图片，报告只保留 hash、标签、动作和耗时，不展示原图。

## 部署建议

| 阶段 | 建议 |
|---|---|
| MVP | 单机部署，文字和图片服务优先上线，视频异步处理 |
| 小规模生产 | 网关 + 独立服务 + Redis/MQ + 数据库，图片/OCR 服务可使用 GPU |
| 中大型社区 | 服务水平扩容，视频任务独立队列，人审后台和样本回流必须上线 |
| 高合规业务 | 开源方案只做辅助，涉政、暴恐、未成年人、诈骗黑产建议接入商业厂商或专业人审兜底 |

资源建议：

| 服务 | CPU | GPU | 说明 |
|---|---:|---:|---|
| text-audit-service | 2-4 核 | 可选 | 敏感词 CPU 足够，文本模型可用小 GPU 加速 |
| image-audit-service | 4-8 核 | 推荐 | NSFW、NudeNet、OCR 对 GPU 更友好 |
| video-audit-service | 4-8 核 | 推荐 | 抽帧 CPU 可跑，批量帧审核和 ASR 建议 GPU |
| audit-gateway | 2 核 | 不需要 | 已落地 8040 统一入口，转发到 text/image/video 审核服务并查询异步结果 |

## 样本回流和持续优化

上线后必须建立闭环：

```text
线上审核
  -> 人工复核 / 用户举报 / 用户申诉 / 抽检
  -> 标注误杀、漏判、正确命中
  -> 更新敏感词、白名单、阈值
  -> 离线回放历史样本
  -> 灰度发布新策略
  -> 全量上线并保留可回滚版本
```

建议评估指标：

| 指标 | 作用 |
|---|---|
| Precision | 命中内容中真实违规的比例，影响误杀 |
| Recall | 真实违规内容被抓到的比例，影响漏判 |
| FPR | 正常内容被误伤比例 |
| FNR | 违规内容被放过比例 |
| 人审命中率 | review 队列中真实违规比例 |
| 申诉成功率 | 策略是否过严 |
| 类目覆盖率 | 各风险类型分别统计，不能只看总准确率 |

## 开源组件来源

- houbb/sensitive-word：https://github.com/houbb/sensitive-word
- houbb/sensitive-word-data：https://github.com/houbb/sensitive-word-data
- thu-coai/roberta-base-cold：https://huggingface.co/thu-coai/roberta-base-cold
- thu-coai/COLDataset：https://github.com/thu-coai/COLDataset
- PaddleOCR：https://github.com/PaddlePaddle/PaddleOCR
- RapidOCR：https://github.com/RapidAI/RapidOCR
- Falconsai/nsfw_image_detection：https://huggingface.co/Falconsai/nsfw_image_detection
- NudeNet：https://github.com/vladmandic/nudenet
- ShieldGemma 2：https://huggingface.co/google/shieldgemma-2-4b-it
- Llama Guard 4：https://huggingface.co/meta-llama/Llama-Guard-4-12B
- FFmpeg：https://ffmpeg.org/
- PySceneDetect：https://github.com/Breakthrough/PySceneDetect
- faster-whisper：https://github.com/SYSTRAN/faster-whisper
- Whisper：https://github.com/openai/whisper

## 注意事项

- 开源模型不能承诺覆盖所有涉政、暴恐、未成年人、诈骗黑产风险。
- 所有模型商用前必须检查 License 和模型使用条款。
- 不建议长期保存高敏原图，证据存储应做权限隔离、脱敏和过期清理。
- 审核策略必须版本化，否则线上误杀无法快速回滚。
- 人审结果不要直接无校验地进入训练集，需要仲裁和质检，避免数据污染。
