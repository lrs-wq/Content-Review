$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\video-audit"

if (-not (Test-Path $Python)) {
  throw "Python environment not found: $Python"
}

$connections = Get-NetTCPConnection -LocalPort 8030 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

$env:PROJECT_ROOT = $ProjectRoot
$env:CONFIG_DIR = Join-Path $ProjectRoot "configs"
$env:POLICY_VERSION = "2026.06.24"
$env:IMAGE_AUDIT_URL = "http://127.0.0.1:8020/v1/moderation/image/upload"
$env:TEXT_AUDIT_URL = "http://127.0.0.1:8010/v1/moderation/text"
$env:VIDEO_AUDIT_MAX_DURATION_SECONDS = "60"
$env:VIDEO_AUDIT_FRAME_SAMPLE_FPS = "1"
$env:VIDEO_AUDIT_MAX_SAMPLED_FRAMES = "60"
$env:VIDEO_AUDIT_FRAME_SKIP_OCR = "true"
$env:VIDEO_AUDIT_STOP_ON_BLOCK = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_ENABLED = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_MAX_FRAMES = "2"
$env:VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_FIRST_FRAME = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_INCLUDE_LAST_FRAME = "false"
$env:VIDEO_AUDIT_SELECTIVE_OCR_MIN_INTERVAL_SECONDS = "2"
$env:VIDEO_AUDIT_SELECTIVE_OCR_TEXT_REGION_ENABLED = "true"
$env:VIDEO_AUDIT_SELECTIVE_OCR_RETRY_ON_QR_OR_RISK = "true"

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030") `
  -WorkingDirectory $ServiceRoot `
  -WindowStyle Hidden

Write-Output "video-audit-service started at http://127.0.0.1:8030"
