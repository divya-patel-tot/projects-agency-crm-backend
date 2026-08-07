# Start FastAPI backend (development)
Set-Location $PSScriptRoot\..

. "$PSScriptRoot\dev-health.ps1"

$PreferredPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8000 }

if (Test-AgencyCrmHealth -Port $PreferredPort) {
    Write-Host "Agency CRM already running at http://127.0.0.1:$PreferredPort" -ForegroundColor Green
    Set-Content -Path ".dev-port" -Value $PreferredPort -NoNewline
    exit 0
}

$Port = & "$PSScriptRoot\resolve-port.ps1" -PreferredPort $PreferredPort
if ($Port -ne $PreferredPort) {
    Write-Host "Port $PreferredPort is busy — starting backend on $Port" -ForegroundColor Yellow
}

Set-Content -Path ".dev-port" -Value $Port -NoNewline
Write-Host "Starting backend DEV at http://127.0.0.1:$Port (GraphQL: /graphql)" -ForegroundColor Cyan
& .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
