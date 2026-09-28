@echo off
setlocal
cd /d "%~dp0"

echo.
echo ==================================================
echo   AI 图生建筑设计说明
echo ==================================================
echo.

rem ---------- 找到 Python ----------
set "PY=python"
python --version >nul 2>nul
if errorlevel 1 (
    set "PY=py"
    py --version >nul 2>nul
    if errorlevel 1 (
        echo [错误] 没有找到 Python。
        echo        请到 https://www.python.org/downloads/ 下载安装，
        echo        安装时务必勾选 "Add Python to PATH"。
        echo.
        pause
        exit /b 1
    )
)

rem ---------- 拿图片路径 ----------
set "IMG=%~1"
if "%IMG%"=="" (
    echo 小技巧：也可以直接把图片文件拖到 run.bat 图标上运行。
    echo.
    set /p "IMG=请把图片拖进这个窗口（或粘贴路径），然后按回车："
)
set "IMG=%IMG:"=%"

if not exist "%IMG%" (
    echo.
    echo [错误] 找不到这个文件：%IMG%
    echo.
    pause
    exit /b 1
)

rem ---------- 选图纸类型 ----------
echo.
echo 图纸类型：
echo    1 = 总平面图   [功能分区 / 交通组织 / 竖向设计 / 消防组织]
echo    2 = 建筑效果图 [风格意象 / 设计手法 / 材料质感]
echo    3 = 自动识别   （默认，直接回车）
echo.
set "T=3"
set /p "T=请输入 1 / 2 / 3 后回车："
set "TYPE="
if "%T%"=="1" set "TYPE=--type plan"
if "%T%"=="2" set "TYPE=--type render"

rem ---------- 跑 ----------
echo.
echo --------------------------------------------------
%PY% design_description.py "%IMG%" %TYPE%
set "RC=%ERRORLEVEL%"
echo --------------------------------------------------
echo.
if not "%RC%"=="0" (
    echo [失败] 程序没有正常结束，请把上面的提示看一遍。
    echo        最常见的两个原因：
    echo          1. .env 里没填 Key，或 Key 填错了
    echo          2. 没装依赖，执行：%PY% -m pip install requests
    echo.
) else (
    echo 说明文件已生成，在 output 文件夹里。
    echo.
)
pause
endlocal
