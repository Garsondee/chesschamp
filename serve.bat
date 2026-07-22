@echo off
REM Launch the ChessChamp web app, then open http://127.0.0.1:8000
"%~dp0.venv\Scripts\python.exe" -m uvicorn web.app:app --host 127.0.0.1 --port 8000
