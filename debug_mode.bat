@echo off
echo 正在启动CDT日志解析器（调试模式）...

:: 设置环境变量，控制日志级别为DEBUG，显示所有日志信息
set PYTHONIOENCODING=utf-8
set CDT_LOG_LEVEL=DEBUG

:: 修改配置文件中的日志级别
python -c "import configparser; config = configparser.ConfigParser(); config.read('config.ini', encoding='utf-8'); config.set('Logging', 'log_level', 'DEBUG'); f = open('config.ini', 'w', encoding='utf-8'); config.write(f); f.close(); print('已将配置文件中的日志级别设置为DEBUG')"

:: 启动UI界面
python cdt_log_parser_ui.py

echo 应用程序已关闭。
pause 