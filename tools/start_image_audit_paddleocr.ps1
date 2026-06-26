$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\image-audit"

if (-not (Test-Path $Python)) {
  throw "PaddleOCR Python environment not found: $Python"
}

$connections = Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

$env:PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT = "0"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_ETAG_TIMEOUT = "5"
$env:HF_HUB_DOWNLOAD_TIMEOUT = "30"
$env:IMAGE_AUDIT_ENABLE_OCR = "true"
$env:IMAGE_AUDIT_OCR_PROVIDER = "paddleocr"
$env:IMAGE_AUDIT_ENABLE_NSFW_MODEL = "true"
$env:IMAGE_AUDIT_NSFW_MODEL_NAME = "storage/models/falconsai-nsfw"
$env:IMAGE_AUDIT_NSFW_DEVICE = "-1"
$env:IMAGE_AUDIT_NSFW_DOWNLOAD_ON_REQUEST = "false"
$env:IMAGE_AUDIT_ENABLE_NUDENET = "true"
$env:IMAGE_AUDIT_ENABLE_VISION_SAFETY = "true"
$env:IMAGE_AUDIT_VISION_SAFETY_PROVIDER = "shieldgemma2_local"
$env:IMAGE_AUDIT_VISION_SAFETY_MODEL_NAME = "storage/models/shieldgemma-2-4b-it"
$env:IMAGE_AUDIT_VISION_SAFETY_DEVICE = "auto"
$env:IMAGE_AUDIT_VISION_SAFETY_ALLOW_CPU = "false"
$env:IMAGE_AUDIT_VISION_SAFETY_TRIGGER_MODE = "gray"
$env:IMAGE_AUDIT_VISION_SAFETY_REVIEW_ON_UNAVAILABLE = "true"

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020") `
  -WorkingDirectory $ServiceRoot `
  -WindowStyle Hidden

Write-Output "image-audit-service started at http://127.0.0.1:8020"
