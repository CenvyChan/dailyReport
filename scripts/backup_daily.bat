@echo off
REM 每天备份一次数据库，保留最近 30 份。备份目录取 .env 里的 BACKUP_DIRECTORY。
REM 注册示例（管理员 CMD，一行）：
REM   schtasks /create /tn "DailyReportBackup" /tr "E:\DEV\dailyReport\scripts\backup_daily.bat" /sc daily /st 23:30 /ru SYSTEM
setlocal
cd /d "%~dp0.."
python scripts\backup_sqlite.py --keep 30 >> "%~dp0..\logs\backup.log" 2>&1
endlocal
