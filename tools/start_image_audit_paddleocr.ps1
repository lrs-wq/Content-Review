$ErrorActionPreference = "Stop"

# Restart the local image-audit-service with OCR, Falconsai NSFW, NudeNet, and gray-zone
# ShieldGemma2 review enabled.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\image-audit"

if (-not (Test-Path $Python)) {
  throw "PaddleOCR Python environment not found: $Python"
}

# Free the fixed local development port before starting a fresh hidden uvicorn process.
$connections = Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

# PaddleOCR can be sensitive to CPU/MKLDNN defaults and model source checks in local Windows
# installs, so pin these environment values before the service imports PaddleOCR.
$env:PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT = "0"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"

# HuggingFace settings keep model loading deterministic and avoid Xet-related failures.
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_ETAG_TIMEOUT = "5"
$env:HF_HUB_DOWNLOAD_TIMEOUT = "30"

# OCR is enabled for standalone image requests. Video service can still ask image-audit-service to
# skip OCR for most frames through the request-level skip_ocr field.
$env:IMAGE_AUDIT_ENABLE_OCR = "true"
$env:IMAGE_AUDIT_OCR_PROVIDER = "paddleocr"

# Visual models are loaded from local storage so user requests do not trigger downloads.
$env:IMAGE_AUDIT_ENABLE_NSFW_MODEL = "true"
$env:IMAGE_AUDIT_NSFW_MODEL_NAME = "storage/models/falconsai-nsfw"
$env:IMAGE_AUDIT_NSFW_DEVICE = "-1"
$env:IMAGE_AUDIT_NSFW_DOWNLOAD_ON_REQUEST = "false"
$env:IMAGE_AUDIT_ENABLE_NUDENET = "true"

# Multimodal safety is only used for gray-zone images. CPU fallback is disabled because
# ShieldGemma2 is too slow for synchronous local review without a GPU.
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
