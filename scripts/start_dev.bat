@echo off
cd /d "%~dp0.."
if not exist "venv\Scripts\python.exe" (
  echo [ERROR] Backend venv not found. From backend folder run:
  echo   python -m venv venv
  echo   venv\Scripts\pip install -e .
  exit /b 1
)
echo Starting backend DEV at http://127.0.0.1:8000 (GraphQL: /graphql)
venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
