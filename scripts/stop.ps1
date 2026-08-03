# Stop whatever is listening on port 8000 (backend API).
Set-Location $PSScriptRoot\..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\kill-port.ps1 -Port 8000
