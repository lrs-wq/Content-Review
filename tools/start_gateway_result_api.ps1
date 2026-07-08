$ErrorActionPreference = "Stop"

# Start a second gateway instance on port 8041 for async moderation result polling. It uses the
# same app and the same file-backed job store as the 8040 submit gateway, but clients should call
# only the /v1/moderation/result endpoints on this port.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\gateway"

if (-not (Test-Path $Python)) {
  throw "Python environment not found: $Python"
}

# Free the fixed local polling port before starting a fresh hidden uvicorn process.
$connections = Get-NetTCPConnection -LocalPort 8041 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

$env:GATEWAY_TEXT_AUDIT_URL = "http://127.0.0.1:8010/v1/moderation/text"
$env:GATEWAY_IMAGE_AUDIT_JSON_URL = "http://127.0.0.1:8020/v1/moderation/image"
$env:GATEWAY_IMAGE_AUDIT_UPLOAD_URL = "http://127.0.0.1:8020/v1/moderation/image/upload"
$env:GATEWAY_VIDEO_AUDIT_UPLOAD_URL = "http://127.0.0.1:8030/v1/moderation/video/upload"
$env:GATEWAY_REQUEST_TIMEOUT_SECONDS = "300"
$env:GATEWAY_HEALTH_TIMEOUT_SECONDS = "2"
$env:GATEWAY_PORT = "8041"
$env:GATEWAY_RESULT_PORT = "8041"
$env:GATEWAY_ASYNC_JOB_DIR = Join-Path $ProjectRoot "storage\moderation-jobs"

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8041") `
  -WorkingDirectory $ServiceRoot `
  -WindowStyle Hidden

Write-Output "content-review-result-api started at http://127.0.0.1:8041"
