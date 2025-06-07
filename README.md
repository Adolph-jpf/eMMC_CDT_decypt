# eMMC CDT日志解析器 (Optimized)

这是一个高性能 eMMC CDT log解析工具，专为处理大型Log文件（100MB以上）而设计；
如有问题请联系 Adolph;
## 主要特性
- 删除冗余CMD FBCC 
- Naming rule 包含TD/SITE/DUT
- 高效的文本处理算法，减少内存使用
- 使用Cython编译关键处理函数，显著提高执行速度
- 多线程并行处理，充分利用多核CPU
- 内存管理优化，适合处理超大文件
- 缓存机制，避免重复计算
- 正则表达式优化，提高匹配速度
- 支持通过配置文件自定义设置

## 配置文件

应用程序使用`config.ini`配置文件来存储设置。您可以通过以下方式修改配置：

1. 直接编辑`config.ini`文件
2. 在应用程序中点击工具栏上的"配置"按钮，打开配置编辑器







######
配置文件包含以下主要设置：

```ini
[General]
# 应用程序名称
app_name = CDT日志解析器

[Logging]
# 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
log_level = ERROR
# 是否将日志输出到文件
log_to_file = true
log_file = cdt_parser.log

[Performance]
# 默认工作线程数，0表示使用CPU核心数
default_workers = 0
# 最大工作线程数
max_workers = 8

[UI]
# 主题: light, dark
theme = light
# 字体大小
font_size = 10
```

## 打包成可执行文件

如果您希望将CDT日志解析器打包成可执行文件（EXE）分发给用户，可以使用提供的打包脚本：

### Windows系统

```bash
build_exe_windows.bat
```

打包完成后，可执行文件位于`dist`目录中，名为`CDT日志解析器.exe`。

### Linux/Mac系统

```bash
chmod +x build_exe.sh
./build_exe.sh
```

打包完成后，可执行文件位于`dist`目录中，名为`CDT日志解析器`。

## 安装依赖

如果您不使用打包好的可执行文件，而是直接运行Python脚本，则需要安装以下依赖：

### 推荐方式：手动安装依赖（更快）

#### Windows系统

```bash
pip install cython numpy PyQt6 setuptools
```

#### Linux/Mac系统

```bash
pip3 install cython numpy PyQt6 setuptools
```

### 自动安装方式（较慢）

#### Windows系统

运行提供的安装脚本：

```bash
install_dependencies.bat
```

#### Linux/Mac系统

运行提供的安装脚本：

```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

## 编译Cython模块

在首次使用前，需要编译Cython模块以获得最佳性能：

### Windows系统

可以直接运行提供的批处理文件：

```bash
compile_cython.bat
```

或者手动执行：

```bash
python setup.py build_ext --inplace
```

### Linux/Mac系统

可以使用提供的Shell脚本：

```bash
chmod +x compile_cython.sh
./compile_cython.sh
```

或者手动执行：

```bash
python setup.py build_ext --inplace
```

## 启动应用程序

### 快速启动（推荐）

#### Windows系统

双击运行`quick_start.bat`文件，直接启动UI界面。

#### Linux/Mac系统

```bash
chmod +x quick_start.sh
./quick_start.sh
```

### 标准启动（带依赖检查）

#### Windows系统

双击运行`start_app.bat`文件。

#### Linux/Mac系统

```bash
chmod +x start_app.sh
./start_app.sh
```

### 调试模式（显示详细日志）

如果您需要查看详细的日志信息，可以使用调试模式启动：

#### Windows系统

双击运行`debug_mode.bat`文件。

#### Linux/Mac系统

```bash
chmod +x debug_mode.sh
./debug_mode.sh
```

## 日志级别控制

CDT日志解析器支持通过环境变量或配置文件控制日志级别：

- `DEBUG`：显示所有日志信息，包括调试信息
- `INFO`：显示信息、警告和错误信息
- `WARNING`：显示警告和错误信息
- `ERROR`：只显示错误信息（默认）
- `CRITICAL`：只显示严重错误信息

您可以通过以下方式设置日志级别：

1. 在配置文件`config.ini`中修改`log_level`设置
2. 在应用程序中使用配置编辑器修改
3. 在命令行中设置环境变量：

```bash
# Windows
set CDT_LOG_LEVEL=INFO
python cdt_log_parser_ui.py

# Linux/Mac
export CDT_LOG_LEVEL=INFO
python3 cdt_log_parser_ui.py
```

## 使用方法

### 图形界面

图形界面提供了直观的操作方式：

1. 选择输入文件或目录
2. 选择输出目录
3. 设置工作线程数
4. 点击"开始处理"按钮
5. 查看处理进度和结果

图形界面特点：
- 现代化的Fluent Design风格
- 明暗主题切换
- 实时进度显示
- 详细的日志查看
- 处理结果预览
- 配置编辑器

### 命令行

如果您更喜欢命令行操作，也可以使用命令行接口：

```bash
python cdt_log_parser_optimized.py -i <输入文件或目录> -o <输出目录>
```

### 参数说明

- `-i, --input`: 输入文件或目录路径
- `-o, --output`: 输出目录路径
- `-w, --workers`: 并行处理的工作线程数（默认为CPU核心数）
- `-v, --verbose`: 显示详细日志信息

### 示例

处理单个文件：

```bash
python cdt_log_parser_optimized.py -i test_log.txt -o output_dir
```

处理整个目录：

```bash
python cdt_log_parser_optimized.py -i log_directory -o output_dir
```

## 性能优化选项

### 使用PyPy解释器

对于没有安装Cython的环境，可以使用PyPy解释器运行脚本，获得较好的加速效果：

```bash
pypy3 cdt_log_parser_optimized.py -i <输入文件或目录> -o <输出目录>
```

### 调整工作线程数

根据系统配置调整并行处理的工作线程数：

```bash
python cdt_log_parser_optimized.py -i <输入文件或目录> -o <输出目录> -w 8
```

## 性能测试

在测试环境中，对100MB的日志文件处理时间从原来的10秒以上优化到了3秒以下。主要优化点包括：

1. 使用Cython编译关键处理函数
2. 使用多线程并行处理，提高CPU利用率
3. 优化正则表达式，使用字符串查找替代部分正则表达式
4. 使用缓存机制，避免重复计算
5. 内存管理优化，减少内存占用

## 界面预览

CDT日志解析器提供了现代化的用户界面，包括以下主要部分：

1. **输入区域**：选择输入文件/目录和输出目录
2. **选项区域**：设置工作线程数等参数
3. **进度区域**：显示处理进度和实时日志
4. **结果区域**：显示处理结果和统计信息
5. **工具栏**：提供主题切换和帮助功能

界面采用微软Fluent Design风格，支持亮色和暗色主题，提供流畅的用户体验。

## 故障排除

### 编译错误

#### 变量声明错误

如果在编译Cython模块时遇到以下错误：

```
cdef statement not allowed here
```

这是因为在Cython中，变量声明必须在函数体的开头，不能在条件语句或循环内部。已修复此问题，请使用最新版本的代码。

#### 闭包和生成器表达式错误

如果遇到以下错误：

```
closures inside cpdef functions not yet supported
```

或

```
Compiler crash in CreateClosureClasses
```

这是因为Cython不支持在`cpdef`函数中使用Python的闭包、生成器表达式和某些列表推导式。解决方法是将这些Python特性替换为更"C风格"的代码，例如使用普通的for循环和辅助函数。

#### 类型错误

如果遇到以下错误：

```
TypeError: Expected dict, got collections.defaultdict
```

这是因为在Cython中，当函数声明返回类型为`dict`时（如`cpdef dict process_test_unit(...)`），Cython期望返回的是一个标准的Python字典，而不是`defaultdict`或其他字典子类。解决方法是在Cython代码中使用普通的`dict`替代`defaultdict`，并手动实现类似的功能。

### 多进程序列化错误

#### 嵌套函数序列化错误

如果在使用多进程时遇到以下错误：

```
AttributeError: Can't pickle local object 'CDTLogParser.process_large_file.<locals>.process_unit'
```

这是因为Python的多进程模块需要序列化（pickle）函数和数据以便在不同进程间传递，但内部定义的函数（嵌套函数）无法被序列化。

#### 线程锁序列化错误

如果在使用多进程时遇到以下错误：

```
TypeError: cannot pickle '_thread.lock' object
```

这是因为线程锁对象（如`threading.Lock`）无法被序列化，而CDTLogParser类包含了线程锁对象（`self.lock`）。

解决方案：

1. **使用多线程替代多进程**：多线程不需要序列化对象，因此可以避免这些问题。虽然多线程受到GIL的限制，但对于I/O密集型任务（如文件读写）仍然可以获得良好的性能提升。

2. **使用独立的辅助函数**：如果必须使用多进程，可以创建不依赖于类实例的独立辅助函数，并确保传递的参数不包含无法序列化的对象。

在最新版本中，我们采用了第一种方法，使用多线程替代多进程，这样可以避免序列化问题，同时保持代码的简洁性。

### 导入错误

如果遇到"ImportError: No module named cdt_log_parser_cy"错误，请确保已经正确编译Cython模块：

```bash
python setup.py build_ext --inplace
```

如果编译失败，程序会自动回退到纯Python实现，但性能会有所降低。

### UI相关问题

#### PyQt6安装问题

如果安装PyQt6时遇到问题，可以尝试安装PyQt5作为替代：

```bash
pip install PyQt5
```

然后修改`cdt_log_parser_ui.py`中的导入语句，将`PyQt6`替换为`PyQt5`。

#### 字体显示问题

如果界面字体显示不正常，可能是因为系统缺少所需的字体。可以修改`cdt_log_parser_ui.py`中的字体设置，使用系统已有的字体。

### 其他问题

如果遇到其他问题，请检查日志文件`cdt_parser.log`，其中包含详细的错误信息和处理过程。 