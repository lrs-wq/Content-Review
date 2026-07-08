# 内容审核测试台

本页面用于手动测试内容审核接口。默认模式会提交到 `gateway-service:8040`，
再按返回的 `content_id` 轮询 `gateway-result-service:8041`；也可以取消异步模式，
直连 `text-audit-service`、`image-audit-service`、`video-audit-service` 做单服务调试。

## 启动服务

先启动文本审核服务：

```bash
cd services/text-audit
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

再启动图片审核服务：

```bash
powershell -ExecutionPolicy Bypass -File tools/start_image_audit_paddleocr.ps1
```

再启动视频审核服务：

```bash
powershell -ExecutionPolicy Bypass -File tools/start_video_audit.ps1
```

启动聚合网关和结果查询服务：

```bash
powershell -ExecutionPolicy Bypass -File tools/start_gateway.ps1
powershell -ExecutionPolicy Bypass -File tools/start_gateway_result_api.ps1
```

启动测试台：

```bash
python tools/text-audit-ui/serve.py --host 0.0.0.0 --port 8050
```

浏览器访问：

```text
http://127.0.0.1:8050/
http://192.168.1.200:8050/
```

## 页面能力

- 默认异步：请求先到 `POST /v1/moderation/async`，页面展示 8040 的立即返回，
  再轮询 `GET /v1/moderation/result/{content_id}` 并展示最终审核结果。
- 文本审核：原文、相关文本、图片 OCR 文本、视频 ASR 文本、上下文 JSON。
- 图片审核：本地图片上传、相关文本、已知 OCR 文本、是否跳过 OCR、上下文 JSON。
- 视频审核：本地视频上传、相关文本、已有 ASR 文本、是否强制跳过帧 OCR、上下文 JSON；不填写已有 ASR 时，视频服务会对有音轨的视频自动转写。
- 返回展示：`action`、`risk_level`、耗时、命中标签、OCR 行、模型状态、8040 直接返回、8041 轮询返回与最终 JSON。
