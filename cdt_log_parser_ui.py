import sys
import os
import time
import threading
import logging
import configparser
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QPushButton, QLabel, QFileDialog, QProgressBar, QTabWidget, 
                            QTextEdit, QComboBox, QSpinBox, QCheckBox, QMessageBox, 
                            QListWidget, QListWidgetItem, QSplitter, QFrame, QToolBar, 
                            QStatusBar, QLineEdit, QGroupBox, QDialog)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QTimer, QUrl
from PyQt6.QtGui import QIcon, QFont, QColor, QPalette, QDesktopServices, QAction

# 读取配置文件
config = configparser.ConfigParser()
config_file = 'config.ini'

# 如果配置文件不存在，创建默认配置
if not os.path.exists(config_file):
    config['General'] = {
        'app_name': 'CDT日志解析器'
    }
    config['Logging'] = {
        'log_level': 'ERROR',
        'log_to_file': 'true',
        'log_file': 'cdt_parser.log'
    }
    config['Performance'] = {
        'default_workers': '0',
        'max_workers': '8'
    }
    config['UI'] = {
        'theme': 'light',
        'font_size': '10'
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        config.write(f)
else:
    config.read(config_file, encoding='utf-8')

# 从配置文件获取日志设置
log_file = config.get('Logging', 'log_file', fallback='cdt_parser.log')
log_to_file = config.getboolean('Logging', 'log_to_file', fallback=True)
log_level_str = config.get('Logging', 'log_level', fallback='ERROR')

# 配置日志
log_handlers = []
if log_to_file:
    log_handlers.append(logging.FileHandler(log_file))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)

# 优先使用环境变量中的日志级别，如果没有则使用配置文件中的设置
env_log_level = os.environ.get('CDT_LOG_LEVEL')
if env_log_level:
    log_level_str = env_log_level

log_level = getattr(logging, log_level_str, logging.ERROR)

# 设置控制台日志级别
console = logging.StreamHandler()
console.setLevel(log_level)
console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logging.getLogger('').addHandler(console)

# 记录启动信息
logging.info(f"应用程序启动，日志级别: {log_level_str}")
logging.debug(f"配置文件: {config_file}")

# 禁用第三方库的日志输出
for logger_name in ['PIL', 'matplotlib', 'urllib3', 'requests']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# 导入CDT日志解析器
try:
    from cdt_log_parser_optimized import CDTLogParser, print_progress
except ImportError:
    QMessageBox.critical(None, "导入错误", "无法导入CDT日志解析器模块。请确保cdt_log_parser_optimized.py在当前目录中。")
    sys.exit(1)

# 定义颜色主题
class Theme:
    class Light:
        PRIMARY = "#0078D7"
        SECONDARY = "#E6E6E6"
        BACKGROUND = "#F9F9F9"
        CARD_BACKGROUND = "#FFFFFF"
        TEXT = "#323130"
        BORDER = "#DDDDDD"
        SUCCESS = "#107C10"
        WARNING = "#FFB900"
        ERROR = "#D83B01"
        
    class Dark:
        PRIMARY = "#0078D7"
        SECONDARY = "#2B2B2B"
        BACKGROUND = "#1F1F1F"
        CARD_BACKGROUND = "#2D2D2D"
        TEXT = "#FFFFFF"
        BORDER = "#505050"
        SUCCESS = "#10893E"
        WARNING = "#FFB900"
        ERROR = "#F1707B"

# 当前主题
current_theme = Theme.Light

# 工作线程类，用于后台处理日志文件
class WorkerThread(QThread):
    progress_signal = pyqtSignal(int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, float)
    
    def __init__(self, input_path, output_dir, num_workers):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.num_workers = num_workers
        self.parser = CDTLogParser()
        
    def progress_callback(self, percent, **kwargs):
        file_path = kwargs.get('file_path', '')
        stage = kwargs.get('stage', '')
        # 确保percent是整数，避免类型转换警告
        percent_int = int(percent)
        self.progress_signal.emit(percent_int, f"处理文件: {os.path.basename(file_path)} - {stage} ({percent:.1f}%)")
        
    def log_callback(self, message):
        self.log_signal.emit(message)
        
    def run(self):
        try:
            start_time = time.time()
            self.log_signal.emit(f"开始处理: {self.input_path}")
            
            if os.path.isfile(self.input_path):
                # 处理单个文件
                self.log_signal.emit(f"处理文件: {self.input_path}")
                result = self.parser.process_file(self.input_path, self.output_dir, self.progress_callback)
                self.log_signal.emit(f"文件处理完成，生成 {result} 个结果")
            else:
                # 处理目录
                self.log_signal.emit(f"处理目录: {self.input_path}")
                result = self.parser.process_directory(self.input_path, self.output_dir, 
                                                     self.progress_callback, self.num_workers)
                self.log_signal.emit(f"目录处理完成，共处理 {result} 个文件")
                
            end_time = time.time()
            elapsed_time = end_time - start_time
            self.log_signal.emit(f"总处理时间: {elapsed_time:.2f}秒")
            self.finished_signal.emit(True, f"处理完成，耗时: {elapsed_time:.2f}秒", elapsed_time)
            
        except Exception as e:
            import traceback
            error_msg = f"处理过程中出错: {str(e)}\n{traceback.format_exc()}"
            self.log_signal.emit(error_msg)
            self.finished_signal.emit(False, f"处理失败: {str(e)}", 0)

# 自定义样式的按钮
class FluentButton(QPushButton):
    def __init__(self, text, parent=None, primary=False):
        super().__init__(text, parent)
        self.primary = primary
        self.setMinimumHeight(36)
        self.setFont(QFont("Segoe UI", 10))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._get_style())
        
    def _get_style(self):
        if self.primary:
            return f"""
                QPushButton {{
                    background-color: {current_theme.PRIMARY};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {current_theme.PRIMARY}DD;
                }}
                QPushButton:pressed {{
                    background-color: {current_theme.PRIMARY}AA;
                }}
                QPushButton:disabled {{
                    background-color: {current_theme.SECONDARY};
                    color: #888888;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: {current_theme.SECONDARY};
                    color: {current_theme.TEXT};
                    border: 1px solid {current_theme.BORDER};
                    border-radius: 4px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {current_theme.SECONDARY}DD;
                    border: 1px solid {current_theme.PRIMARY};
                }}
                QPushButton:pressed {{
                    background-color: {current_theme.SECONDARY}AA;
                }}
                QPushButton:disabled {{
                    background-color: {current_theme.SECONDARY};
                    color: #888888;
                    border: 1px solid {current_theme.BORDER};
                }}
            """

# 自定义卡片容器
class CardWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            CardWidget {{
                background-color: {current_theme.CARD_BACKGROUND};
                border-radius: 8px;
                border: 1px solid {current_theme.BORDER};
            }}
        """)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 16, 16, 16)
        self.layout.setSpacing(12)

# 主窗口类
class CDTLogParserUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 从配置文件获取应用程序名称
        app_name = config.get('General', 'app_name', fallback='CDT日志解析器')
        self.setWindowTitle(app_name)
        self.setMinimumSize(900, 700)
        
        # 设置应用图标
        # 获取应用程序路径，确保在编译后也能找到图标
        if getattr(sys, 'frozen', False):
            # 如果是打包后的应用程序
            application_path = os.path.dirname(sys.executable)
        else:
            # 如果是开发环境
            application_path = os.path.dirname(os.path.abspath(__file__))
        
        icon_path = os.path.join(application_path, 'icon.jpg')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            # 记录日志
            logging.info(f"已加载应用图标: {icon_path}")
        else:
            logging.warning(f"找不到图标文件: {icon_path}")
        
        # 从配置文件获取UI主题设置
        theme_name = config.get('UI', 'theme', fallback='light')
        global current_theme
        if theme_name.lower() == 'dark':
            current_theme = Theme.Dark
        else:
            current_theme = Theme.Light
            
        # 从配置文件获取字体大小
        font_size = config.getint('UI', 'font_size', fallback=10)
        
        # 设置应用程序样式
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {current_theme.BACKGROUND};
                color: {current_theme.TEXT};
                font-family: 'Segoe UI', 'Microsoft YaHei UI';
                font-size: {font_size}pt;
            }}
            QTabWidget::pane {{
                border: 1px solid {current_theme.BORDER};
                border-radius: 4px;
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {current_theme.SECONDARY};
                color: {current_theme.TEXT};
                border: 1px solid {current_theme.BORDER};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 16px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {current_theme.CARD_BACKGROUND};
                border-bottom: none;
            }}
            QTabBar::tab:hover {{
                background-color: {current_theme.CARD_BACKGROUND}AA;
            }}
            QProgressBar {{
                border: 1px solid {current_theme.BORDER};
                border-radius: 4px;
                text-align: center;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {current_theme.PRIMARY};
                border-radius: 3px;
            }}
            QLineEdit, QComboBox, QSpinBox {{
                border: 1px solid {current_theme.BORDER};
                border-radius: 4px;
                padding: 6px;
                background-color: {current_theme.CARD_BACKGROUND};
                color: {current_theme.TEXT};
                selection-background-color: {current_theme.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QTextEdit {{
                border: 1px solid {current_theme.BORDER};
                border-radius: 4px;
                padding: 6px;
                background-color: {current_theme.CARD_BACKGROUND};
                color: {current_theme.TEXT};
                selection-background-color: {current_theme.PRIMARY};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 1px solid {current_theme.BORDER};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        # 创建工具栏
        self.create_toolbar()
        
        # 创建标题
        title_label = QLabel("CDT日志解析器")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 创建输入部分
        input_card = CardWidget()
        main_layout.addWidget(input_card)
        
        # 输入文件/目录选择
        input_layout = QHBoxLayout()
        input_card.layout.addLayout(input_layout)
        
        input_label = QLabel("输入文件/目录:")
        input_layout.addWidget(input_label)
        
        self.input_path_edit = QLineEdit()
        self.input_path_edit.setPlaceholderText("选择CDT日志文件或包含日志文件的目录")
        self.input_path_edit.setReadOnly(True)
        input_layout.addWidget(self.input_path_edit, 1)
        
        browse_button = FluentButton("浏览...")
        browse_button.clicked.connect(self.browse_input)
        input_layout.addWidget(browse_button)
        
        # 输出目录选择
        output_layout = QHBoxLayout()
        input_card.layout.addLayout(output_layout)
        
        output_label = QLabel("输出目录:")
        output_layout.addWidget(output_label)
        
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("选择输出目录")
        self.output_dir_edit.setReadOnly(True)
        output_layout.addWidget(self.output_dir_edit, 1)
        
        output_button = FluentButton("浏览...")
        output_button.clicked.connect(self.browse_output)
        output_layout.addWidget(output_button)
        
        # 处理选项
        options_layout = QHBoxLayout()
        input_card.layout.addLayout(options_layout)
        
        workers_label = QLabel("工作线程数:")
        options_layout.addWidget(workers_label)
        
        self.workers_spin = QSpinBox()
        self.workers_spin.setMinimum(1)
        
        # 从配置文件获取最大工作线程数
        max_workers = config.getint('Performance', 'max_workers', fallback=8)
        self.workers_spin.setMaximum(max_workers)
        
        # 从配置文件获取默认工作线程数
        default_workers = config.getint('Performance', 'default_workers', fallback=0)
        if default_workers <= 0:
            # 如果设置为0或负数，则使用CPU核心数
            default_workers = min(os.cpu_count() or 4, max_workers)
        else:
            # 确保不超过最大值
            default_workers = min(default_workers, max_workers)
            
        self.workers_spin.setValue(default_workers)
        self.workers_spin.setToolTip("设置并行处理的工作线程数")
        options_layout.addWidget(self.workers_spin)
        
        options_layout.addStretch()
        
        # 处理按钮
        buttons_layout = QHBoxLayout()
        input_card.layout.addLayout(buttons_layout)
        
        buttons_layout.addStretch()
        
        self.process_button = FluentButton("开始处理", primary=True)
        self.process_button.clicked.connect(self.start_processing)
        buttons_layout.addWidget(self.process_button)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget, 1)
        
        # 进度标签页
        progress_tab = QWidget()
        progress_layout = QVBoxLayout(progress_tab)
        progress_layout.setContentsMargins(16, 16, 16, 16)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("就绪")
        progress_layout.addWidget(self.status_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        progress_layout.addWidget(self.log_text, 1)
        
        self.tab_widget.addTab(progress_tab, "处理进度")
        
        # 结果标签页
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(16, 16, 16, 16)
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        results_layout.addWidget(self.results_text, 1)
        
        results_buttons_layout = QHBoxLayout()
        results_layout.addLayout(results_buttons_layout)
        
        results_buttons_layout.addStretch()
        
        open_output_button = FluentButton("打开输出目录")
        open_output_button.clicked.connect(self.open_output_directory)
        results_buttons_layout.addWidget(open_output_button)
        
        self.tab_widget.addTab(results_tab, "处理结果")
        
        # 关于标签页
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setContentsMargins(16, 16, 16, 16)
        
        about_card = CardWidget()
        about_layout.addWidget(about_card)
        
        about_title = QLabel("CDT日志解析器 (优化版)")
        about_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        about_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_card.layout.addWidget(about_title)
        
        # 从README.md文件中读取about信息，只读取前25行
        about_content = self.read_about_from_readme()
        
        # 创建about文本和刷新按钮的布局
        about_content_layout = QVBoxLayout()
        
        # 添加about文本 - 使用QTextEdit替代QLabel以支持滚动
        self.about_text = QTextEdit()
        self.about_text.setReadOnly(True)  # 设置为只读模式
        self.about_text.setHtml(about_content)  # 使用HTML格式支持更好的排版
        self.about_text.setMinimumHeight(300)  # 设置最小高度
        
        # 确保滚动条可见并可用
        self.about_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.about_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # 设置样式表，使其看起来更像标签而非编辑框，但保留滚动条功能
        self.about_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Theme.Light.CARD_BACKGROUND if current_theme == Theme.Light else Theme.Dark.CARD_BACKGROUND};
                border: 1px solid {Theme.Light.BORDER if current_theme == Theme.Light else Theme.Dark.BORDER};
                border-radius: 4px;
                color: {Theme.Light.TEXT if current_theme == Theme.Light else Theme.Dark.TEXT};
                padding: 8px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {Theme.Light.SECONDARY if current_theme == Theme.Light else Theme.Dark.SECONDARY};
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {Theme.Light.PRIMARY if current_theme == Theme.Light else Theme.Dark.PRIMARY};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        about_content_layout.addWidget(self.about_text)
        
        # 添加刷新按钮
        refresh_button = QPushButton("刷新配置")
        refresh_button.clicked.connect(self.refresh_config)
        about_content_layout.addWidget(refresh_button)
        
        about_card.layout.addLayout(about_content_layout)
        
        self.tab_widget.addTab(about_tab, "关于")
        
        # 创建状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")
        
        # 初始化工作线程
        self.worker_thread = None
        
    def create_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 主题切换动作
        self.theme_action = QAction("切换到暗色主题", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(self.theme_action)
        
        # 配置编辑器动作
        config_action = QAction("配置", self)
        config_action.triggered.connect(self.show_config_editor)
        toolbar.addAction(config_action)
        
        toolbar.addSeparator()
        
        # 帮助动作
        help_action = QAction("帮助", self)
        help_action.triggered.connect(self.show_help)
        toolbar.addAction(help_action)
        
    def toggle_theme(self):
        """切换明暗主题"""
        global current_theme
        if current_theme == Theme.Light:
            current_theme = Theme.Dark
            self.theme_action.setText("切换到亮色主题")
            # 更新配置文件
            config.set('UI', 'theme', 'dark')
        else:
            current_theme = Theme.Light
            self.theme_action.setText("切换到暗色主题")
            # 更新配置文件
            config.set('UI', 'theme', 'light')
            
            # 保存配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                config.write(f)
            
            # 重新应用样式
            # 注意：在实际应用中，这种方式可能不够完善，可能需要重新创建所有UI元素
            # 或使用QSS属性选择器和动态属性来实现更好的主题切换
            QMessageBox.information(self, "主题切换", "主题切换需要重启应用程序才能完全生效。")
        
    def show_config_editor(self):
        """显示配置编辑器对话框"""
        dialog = ConfigEditorDialog(self)
        if dialog.exec():
            # 如果用户点击了保存按钮，提示重启应用程序
            QMessageBox.information(self, "配置已更改", "配置已更改，部分设置需要重启应用程序才能生效。")
        
    def show_help(self):
        help_text = (
            "CDT日志解析器使用说明：\n\n"
            "1. 点击\"浏览...\"按钮选择输入文件或目录\n"
            "2. 点击\"浏览...\"按钮选择输出目录\n"
            "3. 调整工作线程数（默认为CPU核心数，最多8个）\n"
            "4. 点击\"开始处理\"按钮开始处理\n"
            "5. 在\"处理进度\"标签页查看处理进度和日志\n"
            "6. 处理完成后，在\"处理结果\"标签页查看结果\n"
            "7. 点击\"打开输出目录\"按钮查看输出文件\n\n"
            "如需更多帮助，请参阅README.md文件。"
        )
        QMessageBox.information(self, "帮助", help_text)
        
    def browse_input(self):
        options = QFileDialog.Option.ReadOnly
        file_filter = "文本文件 (*.txt);;所有文件 (*)"
        
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, False)
        dialog.setWindowTitle("选择输入文件或目录")
        dialog.setNameFilter(file_filter)
        
        # 添加选择目录的按钮
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        for btn in dialog.findChildren(QPushButton):
            if btn.text() == "Open":
                btn.setText("打开")
            elif btn.text() == "Cancel":
                btn.setText("取消")
        
        layout = dialog.layout()
        if layout is not None:
            dir_button = QPushButton("选择目录", dialog)
            dir_button.clicked.connect(lambda: self.select_directory(dialog))
            layout.addWidget(dir_button)
        
        if dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_files = dialog.selectedFiles()
            if selected_files:
                self.input_path_edit.setText(selected_files[0])
                
                # 如果是目录，自动设置输出目录为输入目录下的output子目录
                if os.path.isdir(selected_files[0]):
                    default_output = os.path.join(selected_files[0], "output")
                else:
                    # 如果是文件，自动设置输出目录为文件所在目录下的output子目录
                    default_output = os.path.join(os.path.dirname(selected_files[0]), "output")
                    
                if not self.output_dir_edit.text():
                    self.output_dir_edit.setText(default_output)
    
    def select_directory(self, dialog):
        directory = QFileDialog.getExistingDirectory(dialog, "选择目录")
        if directory:
            dialog.close()
            self.input_path_edit.setText(directory)
            
            # 自动设置输出目录为输入目录下的output子目录
            default_output = os.path.join(directory, "output")
            if not self.output_dir_edit.text():
                self.output_dir_edit.setText(default_output)
    
    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if directory:
            self.output_dir_edit.setText(directory)
    
    def start_processing(self):
        input_path = self.input_path_edit.text()
        output_dir = self.output_dir_edit.text()
        
        if not input_path:
            QMessageBox.warning(self, "警告", "请选择输入文件或目录")
            return
            
        if not output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return
            
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 禁用处理按钮
        self.process_button.setEnabled(False)
        
        # 清空日志和结果
        self.log_text.clear()
        self.results_text.clear()
        
        # 重置进度条
        self.progress_bar.setValue(0)
        self.status_label.setText("正在处理...")
        
        # 切换到进度标签页
        self.tab_widget.setCurrentIndex(0)
        
        # 创建并启动工作线程
        self.worker_thread = WorkerThread(input_path, output_dir, self.workers_spin.value())
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.log_signal.connect(self.update_log)
        self.worker_thread.finished_signal.connect(self.processing_finished)
        self.worker_thread.start()
    
    def update_progress(self, percent, status):
        # 确保percent是整数
        self.progress_bar.setValue(percent)
        self.status_label.setText(status)
        self.statusBar.showMessage(status)
    
    def update_log(self, message):
        self.log_text.append(message)
        # 滚动到底部
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def processing_finished(self, success, message, elapsed_time):
        # 启用处理按钮
        self.process_button.setEnabled(True)
        
        # 更新状态
        self.status_label.setText(message)
        self.statusBar.showMessage(message)
        
        # 更新结果
        if success:
            self.results_text.append(f"处理完成！\n")
            self.results_text.append(f"输入: {self.input_path_edit.text()}")
            self.results_text.append(f"输出: {self.output_dir_edit.text()}")
            self.results_text.append(f"处理时间: {elapsed_time:.2f}秒")
            
            # 如果处理时间小于3秒，显示祝贺信息
            if elapsed_time < 3.0:
                self.results_text.append("\n🎉 恭喜！处理时间已经达到目标（小于3秒）！")
            
            # 切换到结果标签页
            self.tab_widget.setCurrentIndex(1)
            
            # 显示成功消息
            QMessageBox.information(self, "处理完成", f"处理完成，耗时: {elapsed_time:.2f}秒")
        else:
            self.results_text.append(f"处理失败！\n")
            self.results_text.append(f"错误信息: {message}")
            
            # 显示错误消息
            QMessageBox.critical(self, "处理失败", message)
    
    def open_output_directory(self):
        output_dir = self.output_dir_edit.text()
        if output_dir and os.path.exists(output_dir):
            # 使用系统默认文件管理器打开目录
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_dir))
        else:
            QMessageBox.warning(self, "警告", "输出目录不存在")

    def save_config(self):
        """保存当前配置到配置文件"""
        # 更新配置
        config.set('Performance', 'default_workers', str(self.workers_spin.value()))
        
        # 保存配置文件
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
            
        logging.debug("配置已保存")
        
    def closeEvent(self, event):
        """窗口关闭时保存配置"""
        self.save_config()
        event.accept()

    def read_about_from_readme(self):
        """从README.md文件中读取about信息，只读取前25行"""
        # 默认内容
        about_content = "这是一个高性能的eMMC CDT log解析工具，专为处理大型Log文件（100MB以上）而设计;<br>"
        about_content += "如有问题请联系 Adolph<br><br><b>主要特性：</b><br>"
        default_features = [
            "• Naming rule 包含TD/SITE/DUT",
            "• 高效的文本处理算法，减少内存使用",
            "• 使用Cython编译关键处理函数，显著提高执行速度",
            "• 多线程并行处理，充分利用多核CPU",
            "• 内存管理优化，适合处理超大文件",
            "• 缓存机制，避免重复计算",
            "• 正则表达式优化，提高匹配速度"
        ]
        
        # 尝试读取README.md文件的前25行
        try:
            with open('README.md', 'r', encoding='utf-8') as f:
                # 只读取前25行
                readme_lines = []
                for i, line in enumerate(f):
                    if i >= 25:  # 只读取前25行
                        break
                    readme_lines.append(line)
                
                readme_content = ''.join(readme_lines)
                
                # 如果成功读取到内容，则使用README.md的内容
                if readme_content.strip():
                    # 将Markdown格式转换为简单的HTML格式
                    # 处理标题
                    readme_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', readme_content, flags=re.MULTILINE)
                    readme_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', readme_content, flags=re.MULTILINE)
                    readme_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', readme_content, flags=re.MULTILINE)
                    
                    # 处理列表项
                    readme_content = re.sub(r'^- (.+)$', r'• \1', readme_content, flags=re.MULTILINE)
                    
                    # 处理粗体
                    readme_content = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', readme_content)
                    
                    # 处理换行 - 将所有换行符替换为HTML的<br>标签
                    readme_content = readme_content.replace('\n', '<br>')
                    
                    return readme_content
        except Exception as e:
            logging.warning(f"无法读取README.md文件: {e}")
        
        # 如果无法读取README.md或内容为空，则使用默认内容
        for feature in default_features:
            about_content += f"{feature}<br>"
            
        return about_content

    def refresh_config(self):
        """刷新配置和UI"""
        # 重新读取配置文件
        global config
        config.read(config_file, encoding='utf-8')
        
        # 更新about信息
        about_content = self.read_about_from_readme()
        self.about_text.setHtml(about_content)  # 使用setHtml而不是setText
        
        # 更新样式表以匹配当前主题
        self.about_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Theme.Light.CARD_BACKGROUND if current_theme == Theme.Light else Theme.Dark.CARD_BACKGROUND};
                border: 1px solid {Theme.Light.BORDER if current_theme == Theme.Light else Theme.Dark.BORDER};
                border-radius: 4px;
                color: {Theme.Light.TEXT if current_theme == Theme.Light else Theme.Dark.TEXT};
                padding: 8px;
            }}
            QScrollBar:vertical {{
                border: none;
                background: {Theme.Light.SECONDARY if current_theme == Theme.Light else Theme.Dark.SECONDARY};
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {Theme.Light.PRIMARY if current_theme == Theme.Light else Theme.Dark.PRIMARY};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        
        # 更新UI设置
        # 从配置文件获取字体大小
        font_size = config.getint('UI', 'font_size', fallback=10)
        
        # 更新工作线程数设置
        max_workers = config.getint('Performance', 'max_workers', fallback=8)
        self.workers_spin.setMaximum(max_workers)
        
        default_workers = config.getint('Performance', 'default_workers', fallback=0)
        if default_workers <= 0:
            default_workers = min(os.cpu_count() or 4, max_workers)
        else:
            default_workers = min(default_workers, max_workers)
        
        # 只有当当前值与配置不同时才更新，避免用户设置被覆盖
        if self.workers_spin.value() != default_workers and self.workers_spin.value() == 0:
            self.workers_spin.setValue(default_workers)
        
        QMessageBox.information(self, "刷新成功", "已重新加载配置信息。")

# 配置编辑器对话框
class ConfigEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("配置编辑器")
        self.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # 创建选项卡
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # 日志选项卡
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        
        # 日志级别
        log_level_group = QGroupBox("日志级别")
        log_level_layout = QVBoxLayout(log_level_group)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        current_level = config.get('Logging', 'log_level', fallback='ERROR')
        self.log_level_combo.setCurrentText(current_level)
        log_level_layout.addWidget(self.log_level_combo)
        
        log_layout.addWidget(log_level_group)
        
        # 日志文件
        log_file_group = QGroupBox("日志文件")
        log_file_layout = QVBoxLayout(log_file_group)
        
        self.log_to_file_check = QCheckBox("将日志输出到文件")
        self.log_to_file_check.setChecked(config.getboolean('Logging', 'log_to_file', fallback=True))
        log_file_layout.addWidget(self.log_to_file_check)
        
        log_file_layout.addWidget(QLabel("日志文件名:"))
        self.log_file_edit = QLineEdit(config.get('Logging', 'log_file', fallback='cdt_parser.log'))
        log_file_layout.addWidget(self.log_file_edit)
        
        log_layout.addWidget(log_file_group)
        
        # 性能选项卡
        perf_tab = QWidget()
        perf_layout = QVBoxLayout(perf_tab)
        
        # 工作线程
        workers_group = QGroupBox("工作线程")
        workers_layout = QVBoxLayout(workers_group)
        
        workers_layout.addWidget(QLabel("默认工作线程数 (0表示使用CPU核心数):"))
        self.default_workers_spin = QSpinBox()
        self.default_workers_spin.setMinimum(0)
        self.default_workers_spin.setMaximum(32)
        self.default_workers_spin.setValue(config.getint('Performance', 'default_workers', fallback=0))
        workers_layout.addWidget(self.default_workers_spin)
        
        workers_layout.addWidget(QLabel("最大工作线程数:"))
        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setMinimum(1)
        self.max_workers_spin.setMaximum(32)
        self.max_workers_spin.setValue(config.getint('Performance', 'max_workers', fallback=8))
        workers_layout.addWidget(self.max_workers_spin)
        
        perf_layout.addWidget(workers_group)
        
        # UI选项卡
        ui_tab = QWidget()
        ui_layout = QVBoxLayout(ui_tab)
        
        # 主题
        theme_group = QGroupBox("主题")
        theme_layout = QVBoxLayout(theme_group)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        current_theme_name = config.get('UI', 'theme', fallback='light')
        self.theme_combo.setCurrentText(current_theme_name)
        theme_layout.addWidget(self.theme_combo)
        
        ui_layout.addWidget(theme_group)
        
        # 字体大小
        font_group = QGroupBox("字体")
        font_layout = QVBoxLayout(font_group)
        
        font_layout.addWidget(QLabel("字体大小:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setMinimum(8)
        self.font_size_spin.setMaximum(16)
        self.font_size_spin.setValue(config.getint('UI', 'font_size', fallback=10))
        font_layout.addWidget(self.font_size_spin)
        
        ui_layout.addWidget(font_group)
        
        # 添加选项卡
        tab_widget.addTab(log_tab, "日志")
        tab_widget.addTab(perf_tab, "性能")
        tab_widget.addTab(ui_tab, "界面")
        
        # 按钮
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_config)
        button_layout.addWidget(save_button)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
    
    def save_config(self):
        # 保存日志设置
        config.set('Logging', 'log_level', self.log_level_combo.currentText())
        config.set('Logging', 'log_to_file', str(self.log_to_file_check.isChecked()))
        config.set('Logging', 'log_file', self.log_file_edit.text())
        
        # 保存性能设置
        config.set('Performance', 'default_workers', str(self.default_workers_spin.value()))
        config.set('Performance', 'max_workers', str(self.max_workers_spin.value()))
        
        # 保存UI设置
        config.set('UI', 'theme', self.theme_combo.currentText())
        config.set('UI', 'font_size', str(self.font_size_spin.value()))
        
        # 写入配置文件
        with open(config_file, 'w', encoding='utf-8') as f:
            config.write(f)
        
        # 提示用户重启应用程序
        QMessageBox.information(self, "配置已保存", "配置已保存，部分设置需要重启应用程序才能生效。")
        
        self.accept()

# 应用程序入口
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 使用Fusion风格，它在所有平台上都有一致的外观
    
    # 设置应用程序图标
    # 获取应用程序路径，确保在编译后也能找到图标
    if getattr(sys, 'frozen', False):
        # 如果是打包后的应用程序
        application_path = os.path.dirname(sys.executable)
    else:
        # 如果是开发环境
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    icon_path = os.path.join(application_path, 'icon.jpg')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        logging.info(f"已设置应用程序图标: {icon_path}")
    else:
        logging.warning(f"找不到图标文件: {icon_path}")
    
    # 从配置文件获取字体大小
    font_size = config.getint('UI', 'font_size', fallback=10)
    
    # 设置应用程序字体
    font = app.font()
    font.setPointSize(font_size)
    app.setFont(font)
    
    # 创建并显示主窗口
    window = CDTLogParserUI()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 