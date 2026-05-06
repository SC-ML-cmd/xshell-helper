@echo off
echo Xshell + Bridge v5 launcher

taskkill /f /im XshellCore.exe >nul 2>&1
taskkill /f /im Xshell.exe >nul 2>&1
timeout /t 2 /nobreak >nul

start "" "D:\software\xshell8\Xshell.exe" "C:\Users\Administrator\Documents\NetSarang Computer\8\Xshell\Sessions\ali_ecs_0103.xsh" -script "D:\dev\workspace\AI\xshell-helper\xshell-mcp\bridge\xshell_bridge_v5.py"

timeout /t 10 /nobreak >nul

echo Done. Check bridge status.
