@echo off
echo.
echo ========================================
echo   SignalBot - Daily Push to GitHub
echo ========================================
echo.
cd /d D:\AutoTrade\optfiles\pwa
python market_bot_v8_small.py
git add signals.json capital_log.txt my_capital.txt run_and_push.bat
git commit -m "Signal %date%"
git push origin main
echo.
echo Done! Open phone app and tap Refresh
echo ========================================
pause
