# 内容审核测试台

本页面用于手动测试 `text-audit-service` 与 `image-audit-service`。

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

- 文本审核：原文、相关文本、图片 OCR 文本、视频 ASR 文本、上下文 JSON。
- 图片审核：本地图片上传、相关文本、已知 OCR 文本、是否跳过 OCR、上下文 JSON。
- 视频审核：本地视频上传、相关文本、已有 ASR 文本、是否强制跳过帧 OCR、上下文 JSON；不填写已有 ASR 时，视频服务会对有音轨的视频自动转写。
- 返回展示：`action`、`risk_level`、耗时、命中标签、OCR 行、模型状态与完整 JSON。
