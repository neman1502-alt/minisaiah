@echo off
chcp 65001 > nul
echo ===========================================================================
echo 🌟 [성경분석] 올인원 마스터 공유 허브 & 실시간 AI 분석 플랫폼 실행 중...
echo ===========================================================================
echo.

cd /d "%~dp0"
"C:\Users\office05\AppData\Local\Python\bin\python.exe" launch_share_service.py

pause
