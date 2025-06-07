@echo off
echo 正在安装CDT日志解析器所需的依赖项...
echo.

REM 检查Python是否已安装
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 错误: 未检测到Python。请先安装Python 3.6或更高版本。
    echo 您可以从 https://www.python.org/downloads/ 下载Python。
    pause
    exit /b 1
)

echo 检测到Python，正在安装依赖项...
echo.

REM 安装依赖项
python -m pip install --upgrade pip
echo 正在安装Cython...
python -m pip install cython
echo 正在安装NumPy...
python -m pip install numpy
echo 正在安装PyQt6...
python -m pip install PyQt6
echo 正在安装setuptools...
python -m pip install setuptools

echo.
echo 依赖项安装完成！

REM 编译Cython模块
echo.
echo 正在编译Cython模块...
python setup.py build_ext --inplace
if %ERRORLEVEL% EQU 0 (
    echo Cython模块编译成功！
) else (
    echo Cython模块编译失败，但程序仍可使用纯Python版本运行。
)

echo.
echo 安装完成！现在您可以运行 python cdt_log_parser_ui.py 启动CDT日志解析器。
echo.
pause 