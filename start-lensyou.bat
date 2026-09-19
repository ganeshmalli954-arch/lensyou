@echo off
title LensYou - AI Video Analyzer
color 0b
echo ============================================================
echo   🎬 LensYou - Personal AI Video Intelligence Platform
echo   Opening in your browser...
echo ============================================================
cd /d "C:\Users\HP\.gemini\antigravity\scratch\yt-analyzer"
timeout /t 2 /nobreak >nul
start "" http://localhost:5000
python app.py
pause
