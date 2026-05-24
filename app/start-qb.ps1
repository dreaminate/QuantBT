$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $backendPython)) {
  $backendPython = "python"
}

# 后端：无独立窗口，后台运行（仍监听 127.0.0.1:8000）
$backendArgs = @(
  "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"
)
Start-Process -FilePath $backendPython -ArgumentList $backendArgs -WorkingDirectory $backendDir -WindowStyle Hidden | Out-Null

Write-Host "qb backend (后台，无窗口): http://127.0.0.1:8000"
Write-Host "qb frontend (当前窗口):     http://127.0.0.1:5173"
Write-Host ""

# 前端：在当前终端前台运行（不另开 PowerShell 窗口）；Ctrl+C 仅结束 Vite，后端仍在后台）
Push-Location $frontendDir
try {
  npm run dev -- --host 127.0.0.1 --port 5173
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "qb backend (后台): http://127.0.0.1:8000"
Write-Host "说明: 前端已退出。若需停止后端，请在任务管理器中结束对应 python/uvicorn 进程。"
