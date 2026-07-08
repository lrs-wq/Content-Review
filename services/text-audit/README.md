# Text Audit Service

文字审核服务提供独立 HTTP API，用于审核评论、帖子、私信、昵称、简介、图片 OCR 文本和视频语音转写文本。

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

项目根目录运行 Docker Compose：

```bash
docker compose up -d text-audit-service
```

## API

默认返回简要结果：

```json
{
  "content_id": "c1",
  "result": "review",
  "action": "review",
  "risk_level": "medium",
  "reason": "命中规则 ad:加微信；风险标签 广告引流风险"
}
```

需要完整调试字段时使用 `?brief=false`，也可以在 JSON 请求体中传入 `"brief": false`。

```bash
curl -X POST http://localhost:8010/v1/moderation/text \
  -H "Content-Type: application/json" \
  -d "{\"content_id\":\"c1\",\"user_id\":\"u1\",\"scene\":\"comment\",\"text\":\"待审核文本\"}"
```

请求支持把复杂上下文一起送入审核：

```json
{
  "content_id": "c1",
  "user_id": "u1",
  "scene": "comment",
  "text": "用户原文",
  "related_text": "帖子标题或正文",
  "image_ocr_text": ["图片 OCR 文本"],
  "video_transcript": "视频 ASR 转写文本",
  "context": {
    "parent_comment": "父评论",
    "recent_messages": ["最近对话"]
  }
}
```

服务内置小型 agent 二审层。它不会全量替代规则，只在以下情况触发：

- 初步分数处于灰区。
- 请求包含父评论、标题、图片 OCR、视频 ASR 等复杂上下文。
- 文本里出现暴力、广告、诈骗等可疑语义线索。

服务还支持轻量小模型分类层。训练命令：

```bash
python ../../tools/train_text_classifier.py
```

模型产物默认加载：

```text
../../storage/models/text-classifier/text_classifier.joblib
```

中国场景的政治敏感词、领导人姓名、别名、谐音、机构名和重大事件建议维护在：

```text
../../configs/political_terms.csv
```

领导人姓名、别名和常见称谓默认动作是 `political/high/block`，直接拦截。机构名、职务名、重大事件、地区公共议题等仍建议使用 `review`，由人工复核兜底，避免新闻、历史和政策讨论被直接误封。

公开词库可以从 `fwwdn/sensitive-stop-words` 导入：

```bash
python ../../tools/import_fwwdn_terms.py --refresh
```

生成的词库默认会随服务启动加载：

```text
../../configs/fwwdn_terms.csv
```

辱骂/低俗口头语可从 `dablelv/dirty-cnwords` 的 `curse/all.txt` 导入：

```bash
python ../../tools/import_dirty_cnwords_curse_terms.py --refresh
```

生成的词库默认会随服务启动加载：

```text
../../configs/dirty_cnwords_curse_terms.csv
```

本项目还维护了一份自有低俗口头语变体词库，用于覆盖 `小八嘎`、`baka`、`ばか` 等前后缀、假名和罗马音变体：

```text
../../configs/oral_vulgar_terms.csv
```

低俗口头语和导入的辱骂词默认使用 `high/review`，表示高风险但先进入复核，不直接拦截。

注意：`dirty-cnwords` 抓取时未发现明确 LICENSE 文件，上线或对外分发前需要确认授权；导入内容已独立成 CSV，便于替换、禁用或回滚。

默认只启用规则和启发式语义判断。需要加载 `thu-coai/roberta-base-cold` 时，安装 `requirements-model.txt` 并设置：

```bash
set TEXT_AUDIT_ENABLE_MODEL=true
```
