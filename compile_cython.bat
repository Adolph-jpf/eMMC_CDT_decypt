@echo off
echo 正在编译Cython模块...

:: 检查Python是否已安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未检测到Python安装。
    echo 请安装Python 3.6或更高版本，然后再试一次。
    echo 您可以从 https://www.python.org/downloads/ 下载Python。
    pause
    exit /b 1
)

:: 检查Cython是否已安装
python -c "import Cython" >nul 2>&1
if %errorlevel% neq 0 (
    echo 未检测到Cython。正在安装...
    pip install cython
    if %errorlevel% neq 0 (
        echo 错误: Cython安装失败。
        echo 请手动运行: pip install cython
        pause
        exit /b 1
    )
)

:: 编译Cython模块
echo 正在编译Cython模块...
python setup.py build_ext --inplace
if %errorlevel% neq 0 (
    echo 错误: Cython模块编译失败。
    echo 请检查错误信息并修复问题。
    pause
    exit /b 1
) else (
    echo Cython模块编译成功！
)

echo 编译完成。现在可以使用优化版的CDT日志解析器了。
pause 