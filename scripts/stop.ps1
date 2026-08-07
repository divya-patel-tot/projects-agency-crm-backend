# Stop whatever is listening on the backend API port (default 8000).
Set-Location $PSScriptRoot\..

$Port = 8000
if ($env:BACKEND_PORT) {
    $Port = [int]$env:BACKEND_PORT
}
elseif (Test-Path ".dev-port") {
    $fromFile = (Get-Content ".dev-port" -Raw).Trim()
    if ($fromFile -match '^\d+$') {
        $Port = [int]$fromFile
    }
}

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\kill-port.ps1 -Port $Port
Remove-Item ".dev-port" -ErrorAction SilentlyContinue
