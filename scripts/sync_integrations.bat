@echo off
REM 每天 20:00 由 Windows 计划任务调用一次，拉取金蝶出入库 + 钉钉审批到本地。
REM 命令内部对当天已同步做幂等判断，重复触发无害。
REM 注册示例（管理员 CMD，一行）：
REM   schtasks /create /tn "DailyReportSync" /tr "E:\DEV\dailyReport\scripts\sync_integrations.bat" /sc daily /st 20:00 /ru SYSTEM
setlocal
cd /d "%~dp0.."
python manage.py sync_kingdee >> "%~dp0..\data\sync-task.log" 2>&1
python manage.py sync_dingtalk >> "%~dp0..\data\sync-task.log" 2>&1
endlocal
