@echo off
echo 正在启动CDT日志解析器...

:: 设置环境变量，控制日志级别
set PYTHONIOENCODING=utf-8
set CDT_LOG_LEVEL=ERROR

:: 检查Python是否已安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未检测到Python安装。
    echo 请安装Python 3.6或更高版本，然后再试一次。
    echo 您可以从 https://www.python.org/downloads/ 下载Python。
    pause
    exit /b 1
)

:: 提示用户确认已手动安装依赖
echo 请确保您已手动安装以下依赖:
echo - Cython
echo - NumPy
echo - PyQt6
echo - setuptools
echo.
echo 如果尚未安装，请使用以下命令安装:
echo pip install cython numpy PyQt6 setuptools
echo.

:: 检查Cython模块是否已编译
if not exist cdt_log_parser_cy*.pyd (
    echo 未检测到编译后的Cython模块。
    echo 假设您已预编译Cython模块或将使用纯Python版本。
)

:: 启动应用程序
echo 正在启动图形界面...
python cdt_log_parser_ui.py

echo 应用程序已关闭。
pause 