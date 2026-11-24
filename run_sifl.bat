@echo off
cd /d "%~dp0"
python sifl_app.py
if errorlevel 1 pause
