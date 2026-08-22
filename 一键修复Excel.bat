@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "BASE_DIR=%~dp0"
set "PROCESSOR=%BASE_DIR%xls_postprocessor.py"

if not exist "%PROCESSOR%" (
    echo [错误] 未找到：%PROCESSOR%
    echo 请将本脚本与 xls_postprocessor.py 放在 Excel 文件所在目录。
    pause
    exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 goto use_py

where python >nul 2>nul
if not errorlevel 1 goto use_python

echo [错误] 未找到 Python。
echo 请先安装 Python，并确保已加入 PATH。
pause
exit /b 1

:use_py
set "PYTHON=py -3"
goto run

:use_python
set "PYTHON=python"

:run
echo 正在处理目录：%BASE_DIR%
echo.
%PYTHON% "%PROCESSOR%" "%BASE_DIR%"
set "RESULT=%errorlevel%"

echo.
if "%RESULT%"=="0" (
    echo [完成] 当前目录下的 xls 文件已处理。
) else (
    echo [失败] 处理过程中出现错误，错误代码：%RESULT%
    echo 请查看上方的详细信息。
)
pause
exit /b %RESULT%
