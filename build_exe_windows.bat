@echo off
chcp 65001
echo 正在打包CDT日志解析器为可执行文件...

:: 检查是否已安装PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller未安装，正在安装...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo 安装PyInstaller失败，请手动安装：pip install pyinstaller
        pause
        exit /b 1
    )
)

:: 使用PyInstaller打包
echo 正在使用PyInstaller打包...
pyinstaller --onefile --windowed --icon=icon.ico --name="CDT日志解析器" cdt_log_parser_ui.py

if %errorlevel% neq 0 (
    echo 打包失败，请检查错误信息。
    pause
    exit /b 1
)

echo 打包完成！可执行文件位于dist目录中。
echo 您可以将dist目录中的"CDT日志解析器.exe"分发给用户。

pause 