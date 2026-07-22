@echo off
REM Launch ChessChamp using the project's virtual environment.
"%~dp0.venv\Scripts\python.exe" "%~dp0play.py" %*
