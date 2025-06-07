@echo off
:: 直接启动CDT日志解析器UI界面
:: 设置环境变量，控制日志级别
set PYTHONIOENCODING=utf-8
set CDT_LOG_LEVEL=ERROR

:: 启动UI界面
python cdt_log_parser_ui.py
pause 