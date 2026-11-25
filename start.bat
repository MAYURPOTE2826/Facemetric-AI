@echo off
start "Facemetric-AI API" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
start "Facemetric-AI Web" cmd /k "cd /d %~dp0frontend && npm run dev"
