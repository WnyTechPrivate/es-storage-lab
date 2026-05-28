# Windows: open 2 PowerShell windows — backend (8766) + frontend dev (5173)
# Usage:  .\scripts\dev-up.ps1

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")

# Backend
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\webapp\backend'; " +
    ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload --reload-dir app --log-level info"
)

# Frontend (PATH 에 Node 강제 주입)
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "`$env:Path += ';C:\Program Files\nodejs'; " +
    "cd '$root\webapp\frontend'; " +
    "npm run dev"
)

Write-Host ""
Write-Host "Started:"
Write-Host "  backend  http://127.0.0.1:8766"
Write-Host "  frontend http://localhost:5173"
