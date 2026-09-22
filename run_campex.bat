@echo off
title CAMPEX Master Controller
color 0A

echo ===================================================
echo    CAMPEX: MSRIT BESCOM Shield - Zero-Hour Launch
echo ===================================================
echo.

cd /d "%~dp0"

echo [PRE-FLIGHT] Starting Ollama Edge Server (silent)...
start /min "Ollama Server" cmd /c "ollama serve"
timeout /t 2 /nobreak >nul

echo [PRE-FLIGHT] Resolving dependencies...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
echo Dependencies verified.
echo.

echo [1/3] Launching Dashboard (UI)...
start /min "CAMPEX - [1] Dashboard" cmd /c "streamlit run app.py"
timeout /t 2 /nobreak >nul

echo [2/3] Launching Swarm Orchestrator (AI Brain)...
start /min "CAMPEX - [2] Swarm Orchestrator" cmd /c "python swarm_orchestrator.py"

echo [3/3] Launching Agent War Room (Visual TUI)...
start "CAMPEX - [3] Agent War Room" cmd /k "python agent_monitor.py"

echo.
echo ===================================================
echo  3 systems live. Only the War Room terminal is shown.
echo  Use the website to inject faults via building + / - buttons
echo  or the red INJECT APEX FAULT button.
echo ===================================================
pause
