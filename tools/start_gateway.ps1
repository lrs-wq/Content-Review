$ErrorActionPreference = "Stop"

# Start the unified moderation gateway on port 8040. The gateway does not run moderation models
# itself; it routes requests to text/image/video services and returns their final result.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = "D:\Anaconda3\envs\content-review-ocr\python.exe"
$ServiceRoot = Join-Path $ProjectRoot "services\gateway"

if (-not (Test-Path $Python)) {
  throw "Python environment not found: $Python"
}

# Free the fixed local development port before starting a fresh hidden uvicorn process.
$connections = Get-NetTCPConnection -LocalPort 8040 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
  Stop-Process -Id $conn.OwningProcess -Force
}

$env:GATEWAY_TEXT_AUDIT_URL = "http://127.0.0.1:8010/v1/moderation/text"
$env:GATEWAY_IMAGE_AUDIT_JSON_URL = "http://127.0.0.1:8020/v1/moderation/image"
$env:GATEWAY_IMAGE_AUDIT_UPLOAD_URL = "http://127.0.0.1:8020/v1/moderation/image/upload"
$env:GATEWAY_VIDEO_AUDIT_JSON_URL = "http://127.0.0.1:8030/v1/moderation/video"
$env:GATEWAY_VIDEO_AUDIT_UPLOAD_URL = "http://127.0.0.1:8030/v1/moderation/video/upload"
$env:GATEWAY_REQUEST_TIMEOUT_SECONDS = "300"
$env:GATEWAY_HEALTH_TIMEOUT_SECONDS = "2"
$env:GATEWAY_PORT = "8040"
$env:GATEWAY_ASYNC_JOB_DIR = Join-Path $ProjectRoot "storage\moderation-jobs"

Start-Process `
  -FilePath $Python `
  -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040") `
  -WorkingDirectory $ServiceRoot `
  -WindowStyle Hidden

Write-Output "content-review-gateway started at http://127.0.0.1:8040"
