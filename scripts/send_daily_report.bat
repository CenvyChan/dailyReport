@echo off
REM 由 Windows 计划任务每 10 分钟调用一次；命令内部判断收件组是否到点、当天是否已发过。
REM 注册示例（管理员 CMD，一行）：
REM   schtasks /create /tn "DailyReportMail" /tr "E:\DEV\dailyReport\scripts\send_daily_report.bat" /sc minute /mo 10 /ru SYSTEM
setlocal
cd /d "%~dp0.."
python manage.py send_daily_report >> "%~dp0..\data\mail-task.log" 2>&1
endlocal
