$ErrorActionPreference = "Stop"

# This script restarts the local video-audit-service with the same defaults used by the manual
# test page. It is intentionally Windows/PowerShell specific for the current workstation setup.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\video-audit"

if (-not (Test-Path $Python)) {
  throw "Python environment not found: $Python"
}

# Free the fixed local development port before starting a fresh hidden uvicorn process.
$connections = Get-NetTCPConnection -LocalPort 8030 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

# Make repo/config paths explicit so the service behaves the same regardless of the current shell
# directory used to run this script.
$env:PROJECT_ROOT = $ProjectRoot
$env:CONFIG_DIR = Join-Path $ProjectRoot "configs"
$env:POLICY_VERSION = "2026.06.24"

# HuggingFace download settings for faster-whisper. The mirror endpoint is useful in China; users
# can override HF_ENDPOINT before running the script if they prefer the official Hub.
$env:HF_HUB_DISABLE_XET = "1"
$env:HF_HUB_ETAG_TIMEOUT = "5"
$env:HF_HUB_DOWNLOAD_TIMEOUT = "60"
if (-not $env:HF_ENDPOINT) {
  $env:HF_ENDPOINT = "https://hf-mirror.com"
}

# Read a local token only into this process environment. apikey.txt is ignored by git and is never
# written to logs or committed configuration.
$TokenPath = Join-Path $ProjectRoot "apikey.txt"
if (-not $env:HF_TOKEN -and (Test-Path $TokenPath)) {
  $Token = (Get-Content -Raw -Path $TokenPath).Trim()
  if ($Token) {
    $env:HF_TOKEN = $Token
    $env:HUGGING_FACE_HUB_TOKEN = $Token
  }
}

# Reuse the already running text/image services over local HTTP. Video moderation stays a thin
# orchestrator over ffprobe/ffmpeg, image-audit-service, ASR, and text-audit-service.
$env:IMAGE_AUDIT_URL = "http://127.0.0.1:8020/v1/moderation/image/upload"
$env:TEXT_AUDIT_URL = "http://127.0.0.1:8010/v1/moderation/text"
# The first OCR frame can be slow after a cold image-audit start because PaddleOCR and multimodal
# safety weights may still be warming up. A longer downstream timeout prevents false
# frame_audit_error reviews during local testing.
$env:VIDEO_AUDIT_IMAGE_AUDIT_TIMEOUT_SECONDS = "240"

# The synchronous upload API is intentionally capped at 60 seconds and 60 sampled frames.
$env:VIDEO_AUDIT_MAX_DURATION_SECONDS = "60"
$env:VIDEO_AUDIT_FRAME_SAMPLE_FPS = "1"
$env:VIDEO_AUDIT_MAX_SAMPLED_FRAMES = "60"

# Scene detection uses PySceneDetect to replace nearby fixed frames with scene-cut frames, keeping
# the total frame budget stable while improving coverage around shot changes.
$env:VIDEO_AUDIT_SCENE_DETECT_ENABLED = "true"
$env:VIDEO_AUDIT_SCENE_DETECT_THRESHOLD = "27"
$env:VIDEO_AUDIT_SCENE_DETECT_MIN_SCENE_LEN = "15"
$env:VIDEO_AUDIT_SCENE_DETECT_MAX_FRAMES = "8"
$env:VIDEO_AUDIT_SCENE_DETECT_DEDUPE_SECONDS = "0.35"

# OCR is selective by default: audit every frame visually, but only OCR likely text/QR/risk frames.
$env:VIDEO_AUDIT_FRAME_SKIP_OCR = "true"
$env:VIDEO_AUDIT_STOP_ON_BLOCK = "false"
$env:VIDEO_AUDIT_SELECTIVE_OCR_ENABLED = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_MAX_FRAMES = "2"
$env:VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_FIRST_FRAME = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_LAST_FRAME = "false"
$env:VIDEO_AUDIT_SELECTIVE_OCR_MIN_INTERVAL_SECONDS = "2"
$env:VIDEO_AUDIT_SELECTIVE_OCR_TEXT_REGION_ENABLED = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_RETRY_ON_QR_OR_RISK = "true"

# tiny/cpu/int8 keeps local ASR usable on this workstation. Switch to base/small when model quality
# matters more than latency and weights are predownloaded.
$env:VIDEO_AUDIT_ENABLE_ASR = "true"
$env:VIDEO_AUDIT_ASR_PROVIDER = "faster_whisper"
$env:VIDEO_AUDIT_ASR_MODEL_NAME = "tiny"
$env:VIDEO_AUDIT_ASR_DEVICE = "cpu"
$env:VIDEO_AUDIT_ASR_COMPUTE_TYPE = "int8"

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030") `
  -WorkingDirectory $ServiceRoot `
  -WindowStyle Hidden

Write-Output "video-audit-service started at http://127.0.0.1:8030"
