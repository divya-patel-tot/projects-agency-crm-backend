# Start FastAPI backend (development)
Set-Location $PSScriptRoot\..

Write-Host "Starting backend DEV at http://127.0.0.1:8000 (GraphQL: /graphql)" -ForegroundColor Cyan
& .\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
