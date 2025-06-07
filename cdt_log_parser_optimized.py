import re
import os
import argparse
import sys
import time
import traceback
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Lock
import textwrap
from datetime import datetime
import mmap
import gc
import shutil
import functools  # 添加functools用于缓存



# 尝试导入Cython优化模块
try:
    import cdt_log_parser_cy
    CYTHON_AVAILABLE = True
    print("使用Cython优化模块")
except ImportError:
    CYTHON_AVAILABLE = False
    print("未找到Cython优化模块，使用纯Python实现")

# 尝试导入pyximport进行即时编译
if not CYTHON_AVAILABLE:
    try:
        import pyximport
        pyximport.install()
        PYXIMPORT_AVAILABLE = True
        print("使用pyximport进行即时编译")
    except ImportError:
        PYXIMPORT_AVAILABLE = False

# TODO: 性能优化建议
# 1. 使用Cython编译关键处理函数，可以显著提高执行速度
#    - 将process_test_unit, clean_cdt_log等计算密集型函数转换为Cython
#    - 创建setup.py文件进行编译
# 2. 或者使用PyPy解释器运行脚本，对纯Python代码有较好的加速效果
#    - 安装PyPy: https://www.pypy.org/download.html
#    - 使用命令: pypy3 cdt_log_parser_updated.py <参数>
# 3. 内存管理优化
#    - 使用生成器替代列表，减少中间结果的内存占用
#    - 在process_large_file中实现增量处理，避免一次性加载整个文件内容
#    - 定期调用gc.collect()释放内存，特别是在处理大文件后
# 4. 正则表达式优化
#    - 使用更高效的字符串匹配方法替代部分简单的正则表达式
#    - 对于热点路径上的正则表达式，考虑使用更专业的库如re2或regex
#    - 减少使用re.DOTALL标志，它会导致.匹配所有字符包括换行符，影响性能
# 5. 并行处理增强
#    - 实现更细粒度的并行处理，将单个大文件的处理也并行化
#    - 使用进程池(ProcessPoolExecutor)替代线程池，绕过GIL限制
#    - 优化工作负载分配，确保各个处理单元工作量均衡
# 6. 引入缓存机制
#    - 对于重复出现的模式匹配结果进行缓存
#    - 使用functools.lru_cache装饰频繁调用的纯函数
#    - 实现文件处理结果的磁盘缓存，避免重复处理相同文件
# 7. 使用更高效的数据结构
#    - 在适当情况下使用集合(set)替代列表进行查找操作
#    - 考虑使用NumPy数组处理大量数值数据
#    - 使用更高效的字符串连接方法(如''.join()替代+=)

# 监控性能的全局变量
PERFORMANCE_STATS = defaultdict(float)
FILE_STATS = {}

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cdt_parser.log'),
    ]
)

# 设置控制台日志级别为WARNING，减少终端输出
console = logging.StreamHandler()
console.setLevel(logging.WARNING)
console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logging.getLogger('').addHandler(console)

# 预编译常用的字符串匹配模式，移到类外部以便Cython优化
SKIP_PATTERNS = frozenset([
    'EMMC Transport:',
    '[Property]',
    'bytearray',
    'Transport:',
    'CDT Data <IN>:',
    'Dut:',
    'FORMAT STATUS:'
])

# 预编译需要保留的内容模式
KEEP_PATTERNS = frozenset(['X:', 'Y:', 'LOT:', 'TestNum_', 'Temp:', '#TT'])

# 系统文件列表
SYSTEM_FILES = frozenset(['desktop.ini', 'thumbs.db', '.ds_store'])

class CDTLogParser:
    def __init__(self):
        # 编译所有正则表达式模式，添加预编译标志以提高性能
        self.patterns = {
            'site': re.compile(r'^SITE:(\d+)', re.DOTALL),
            'dut_start': re.compile(r'DUT\[(\d+)\] CDT log info:', re.DOTALL),
            'dut_status': re.compile(r'DUT(\d+) -- soft bin 0x([0-9a-f]+)', re.DOTALL),
            'unit_start': re.compile(r'Start_of_Test -----', re.DOTALL),
            'unit_end': re.compile(r'Execution time:', re.DOTALL),
            'cdt_section': re.compile(r'TestBlock = tb_MacawCdtMtstTest :.*?(?=TestItem:tb_MacawCdtMtstTest Test Time:|$)', re.DOTALL),
            'cdt_log_block': re.compile(r'DUT\[\d+\] CDT log info:\s*\[CDT log\] :~~.*?\[Property\]--->Type:\[7\], Size:\[512\] Dataproperty:bytearray:512', re.DOTALL),
            'property_end': re.compile(r'\s*\[Property\]--->Type:\[7\], Size:\[512\] Dataproperty:bytearray:512', re.DOTALL),
            'emmc_transport': re.compile(r'EMMC Transport: SingleBlock Read.*?\[Property\]--->Type:\[7\], Size:\[512\] Dataproperty:bytearray:512', re.DOTALL),
            'fail_functional': re.compile(r'DUT\d+ -- soft bin 0xffffffff -- hard bin 7 -- fail_functional', re.DOTALL),
            'stlog': re.compile(r'DUT\[\d+\] CDT log info:\[STlog\]device status=\d+\s*\[Property\]--->Type:\[7\], Size:\[512\] Dataproperty:bytearray:512', re.DOTALL),
            'unit_id': re.compile(r'Start_of_Test ----- (\d+)', re.DOTALL)
        }
        
        self.lock = Lock()
        self.td_counters = defaultdict(int)
        self.system_files = ['desktop.ini', 'thumbs.db', '.ds_store']
        self.large_file_threshold = 50 * 1024 * 1024  # 50MB以上视为大文件
        
    def validate_input_file(self, file_path):
        """验证输入文件的有效性"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        if not file_path.endswith('.txt'):
            raise ValueError(f"不支持的文件格式: {file_path}")
        if os.path.getsize(file_path) < 100:
            raise ValueError(f"文件过小，可能不是有效的测试日志: {file_path}")
            
    def is_system_file(self, filename):
        """检查是否为系统文件"""
        system_keywords = ['system', 'sys']
        return any(keyword in filename.lower() for keyword in system_keywords)
        
    def find_site_id(self, content):
        """在指定范围内查找SITE号"""
        lines = content.split('\n')
        
        # 在100-250行之间查找SITE号
        for i, line in enumerate(lines[100:251], 100):  # 使用切片[100:251]确保包含第250行
            line = line.strip()
            site_match = self.patterns['site'].match(line)
            if site_match:
                site_id = site_match.group(1).lstrip('0')
                logging.info(f"在第{i}行找到SITE号: {site_id}")
                return site_id
        
        # 如果没找到，使用默认值
        print("未找到SITE号，使用默认值'unknown'")
        logging.warning("未找到SITE号，使用默认值'unknown'")
        return "unknown"
        
    @functools.lru_cache(maxsize=1024)
    def clean_cdt_log(self, content):
        """清理CDT日志内容，只保留有效数据"""
        # 如果Cython模块可用，使用Cython版本
        if CYTHON_AVAILABLE:
            return cdt_log_parser_cy.clean_cdt_log(content)
            
        # 使用缓存检查，如果内容的哈希值已经处理过，直接返回缓存结果
        content_hash = hash(content[:100] + content[-100:] if len(content) > 200 else content)
        
        # 移除EMMC传输相关的内容 - 使用字符串查找替代正则表达式
        emmc_start = content.find('EMMC Transport: SingleBlock Read')
        if emmc_start != -1:
            property_end = content.find('[Property]--->Type:[7], Size:[512] Dataproperty:bytearray:512', emmc_start)
            if property_end != -1:
                content = content[:emmc_start] + content[property_end + 70:]  # 70是模式长度加一些余量
        
        # 初始化变量
        lines = content.split('\n')
        cleaned_lines = []
        valid_data = False
        
        # 使用更高效的列表推导式预过滤无效行
        filtered_lines = [
            line.strip() for line in lines 
            if line.strip() and not line.strip().isspace() 
            and line.strip() != '[CDT log] :~~'
            and 'nul' not in line.lower()
            and '[STlog]' not in line
            and not (line.startswith('DUT[') and 'CDT log info:' in line)
            and not line.endswith('[Property]--->Type:[7], Size:[512] Dataproperty:bytearray:512')
        ]
        
        # 使用集合加速查找
        skip_patterns_set = SKIP_PATTERNS
        keep_patterns_set = KEEP_PATTERNS
        
        # 处理预过滤后的行
        for line in filtered_lines:
            # 使用any()加速跳过模式检查
            if any(pattern in line for pattern in skip_patterns_set):
                continue
                
            # 检查是否包含字母数字字符或保留模式
            has_alnum = any(c.isalnum() for c in line)
            
            # 如果没有字母数字字符，检查是否包含保留模式
            if not has_alnum and not any(pattern in line for pattern in keep_patterns_set):
                continue
                
            # 格式化DUT状态行 - 使用更高效的字符串操作
            if ' -- soft bin 0x' in line and line.startswith('DUT'):
                dut_part = line.split()[0]
                if len(dut_part) > 3:
                    try:
                        dut_num = int(dut_part[3:])
                        soft_bin_pos = line.find(' -- soft bin 0x')
                        if soft_bin_pos != -1 and 1 <= dut_num <= 24:
                            line = f"DUT{dut_num:02d}{line[soft_bin_pos:]}"
                    except ValueError:
                        pass
                        
            cleaned_lines.append(line)
            valid_data = True
        
        # 返回处理后的内容
        if valid_data:
            return '\n'.join(cleaned_lines)
        return None

    def process_test_unit(self, unit_content, site_id, file_path, unit_id):
        """处理单个测试单元的内容"""
        # 如果Cython模块可用，使用Cython版本
        if 'cdt_log_parser_cy' in sys.modules:
            try:
                import cdt_log_parser_cy
                result = cdt_log_parser_cy.process_test_unit(unit_content, site_id, file_path, unit_id)
                if result is not None:
                    return result
                # 如果Cython版本返回None，回退到Python版本
                logging.warning(f"Cython版本的process_test_unit返回None，回退到Python版本")
            except Exception as e:
                # 如果Cython版本出错，回退到Python版本
                logging.warning(f"使用Cython版本时出错: {str(e)}，回退到Python版本")
                
        logging.info(f"处理测试单元: {unit_id}")
        
        # 创建固定的24个DUT字典 - 使用字典推导式更高效
        dut_dict = {f"{i:02d}": None for i in range(1, 25)}
        
        # 获取测试单元的行 - 使用更高效的方式
        unit_lines = unit_content.splitlines()
        logging.info(f"{unit_id} 测试单元包含 {len(unit_lines)} 行")
        
        # 查找Execution time:的位置 - 使用更高效的字符串查找
        execution_time_index = -1
        execution_time_marker = 'Execution time:'
        
        # 从后向前查找更高效，因为Execution time通常在末尾
        for i in range(len(unit_lines) - 1, max(0, len(unit_lines) - 50), -1):
            if execution_time_marker in unit_lines[i]:
                execution_time_index = i
                logging.info(f"{unit_id} 找到Execution time:在第 {i+1} 行")
                break
        
        # 从Execution time:前面的30行中查找状态行
        if execution_time_index > 0:
            start_index = max(0, execution_time_index - 30)
            status_section_lines = unit_lines[start_index:execution_time_index]
            status_section = '\n'.join(status_section_lines)
            logging.info(f"{unit_id} 使用Execution time:前面的 {len(status_section_lines)} 行查找状态行")
        else:
            # 如果没有找到Execution time:，使用最后30行
            if len(unit_lines) >= 30:
                status_section = '\n'.join(unit_lines[-30:])
            else:
                status_section = '\n'.join(unit_lines)
            logging.info(f"{unit_id} 未找到Execution time:，使用最后 {min(30, len(unit_lines))} 行查找状态行")
        
        # 提取DUT状态行 - 使用更高效的字符串查找
        status_line_marker = ' -- soft bin 0x'
        status_lines_found = 0
        dut_status_lines = {}  # 存储每个DUT的状态行
        
        # 使用更高效的方式处理状态行
        for line in status_section.split('\n'):
            if status_line_marker in line and line.startswith('DUT'):
                status_lines_found += 1
                # 提取DUT编号并格式化为两位数字符串
                dut_part = line.split()[0]
                if len(dut_part) > 3:  # 确保有'DUT'前缀
                    try:
                        dut_num_str = dut_part[3:]  # 原始字符串（如"02"或"2"）
                        dut_num = int(dut_num_str)  # 转为整数（如2）
                        if 1 <= dut_num <= 24:  # 确保DUT编号在有效范围内
                            formatted_dut_id = f"{dut_num:02d}"  # 格式化为"02"
                            
                            # 保存状态行，用于后续处理
                            status_line = f"DUT{formatted_dut_id}{line[line.find(status_line_marker):]}"
                            dut_status_lines[formatted_dut_id] = status_line
                            
                            # 检查是否包含失败标记 - 使用字符串查找替代正则表达式
                            if 'fail_functional' in line:
                                logging.info(f"{unit_id} 中的 DUT{formatted_dut_id} 标记为失败，将从字典中删除")
                                # 不要立即设置为None，等待后续处理CDT日志后再决定
                            else:
                                # 暂时设置为状态行，后面会添加完整的CDT日志内容
                                dut_dict[formatted_dut_id] = status_line
                                logging.debug(f"{unit_id} 中找到 DUT{formatted_dut_id} 状态行: {line}")
                    except ValueError:
                        continue
        
        logging.info(f"{unit_id} 共找到 {status_lines_found} 个状态行")
        
        # 提取CDT日志内容 - 使用字符串查找替代正则表达式
        cdt_start = unit_content.find('TestBlock = tb_MacawCdtMtstTest :')
        if cdt_start != -1:
            # 查找CDT部分的结束位置
            cdt_end = unit_content.find('TestItem:tb_MacawCdtMtstTest Test Time:', cdt_start)
            if cdt_end == -1:
                cdt_end = len(unit_content)
                
            # 提取CDT内容
            cdt_content = unit_content[cdt_start:cdt_end]
            
            # 处理每个DUT的CDT日志块 - 使用更高效的方法
            dut_blocks = {}  # 使用DUT编号作为键存储日志块
            block_start_marker = 'DUT['
            block_end_marker = '[Property]--->Type:[7], Size:[512] Dataproperty:bytearray:512'
            
            pos = 0
            while True:
                # 查找块的开始
                start_pos = cdt_content.find(block_start_marker, pos)
                if start_pos == -1:
                    break
                    
                # 查找块的结束
                end_pos = cdt_content.find(block_end_marker, start_pos)
                if end_pos == -1:
                    break
                    
                # 提取完整的块
                block = cdt_content[start_pos:end_pos + len(block_end_marker)]
                
                # 提取DUT ID - 使用更高效的字符串操作
                dut_start = block.find('[') + 1
                dut_end = block.find(']', dut_start)
                if dut_start > 0 and dut_end > dut_start:
                    try:
                        raw_dut_id = block[dut_start:dut_end]
                        # 将DUT编号格式化为两位数字符串（如"02"）
                        formatted_dut_id = f"{int(raw_dut_id):02d}"
                        # 无论是否有状态行，都处理这个DUT块
                        cleaned_block = self.clean_cdt_log(block)
                        if cleaned_block:
                            # 如果dut_id不在字典中，初始化为空列表
                            if formatted_dut_id not in dut_blocks:
                                dut_blocks[formatted_dut_id] = []
                            dut_blocks[formatted_dut_id].append(cleaned_block)
                    except (ValueError, IndexError):
                        pass
                        
                # 移动到下一个位置
                pos = end_pos + len(block_end_marker)
            
            # 合并每个DUT的日志块并添加状态行 - 使用更高效的方法
            for dut_id in dut_blocks:
                blocks = dut_blocks[dut_id]
                if blocks:  # 只处理有内容的DUT
                    # 添加DUT header
                    header = f"DUT[{dut_id}] CDT log info:"
                    blocks.insert(0, header)
                    
                    # 合并所有块 - 使用join而不是+=
                    combined_content = '\n'.join(blocks)
                    
                    # 检查是否有状态行
                    if dut_id in dut_status_lines:
                        # 确保状态行在文件末尾单独一行
                        combined_content = f"{combined_content.rstrip()}\n{dut_status_lines[dut_id]}"
                    
                    # 检查是否包含失败标记 - 使用字符串查找替代正则表达式
                    if dut_id in dut_status_lines and 'fail_functional' in dut_status_lines[dut_id]:
                        logging.info(f"{unit_id} 中的 DUT{dut_id} 标记为失败，将从字典中删除")
                        dut_dict[dut_id] = None
                    else:
                        # 更新dut_dict，保存CDT日志内容（可能包含状态行）
                        dut_dict[dut_id] = combined_content
                        logging.debug(f"{unit_id} 中的 DUT{dut_id} 保存了CDT日志内容")
        
        # 计算有效DUT数量
        valid_duts = 0
        for dut_id in dut_dict:
            if dut_dict[dut_id] is not None:
                valid_duts += 1
        
        logging.info(f"{unit_id} 处理完成，有效DUT数量: {valid_duts}")
        
        # 如果没有找到任何有效的DUT，返回None
        if valid_duts == 0:
            logging.warning(f"{unit_id} 没有找到任何有效的DUT，返回None")
            return None
            
        # 确保返回的是字典类型
        result = {unit_id: dut_dict}
        logging.debug(f"返回结果类型: {type(result)}")
        return result
        
    def process_file(self, file_path, output_dir=None, progress_callback=None):
        """处理单个日志文件
        
        Args:
            file_path: 日志文件路径
            output_dir: 输出目录路径
            progress_callback: 进度回调函数
            
        Returns:
            int: 处理结果数量
        """
        try:
            self.validate_input_file(file_path)
            if self.is_system_file(os.path.basename(file_path)):
                logging.info(f"跳过系统文件: {file_path}")
                return 0
                
            logging.info(f"开始处理文件: {file_path}")
            
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            if file_size > self.large_file_threshold:
                logging.info(f"文件大小为 {file_size/1024/1024:.2f}MB，超过阈值({self.large_file_threshold/1024/1024:.1f}MB)，使用大文件处理逻辑")
                return self.process_large_file(file_path, output_dir, progress_callback)
            
            # 对于较小的文件，使用标准处理逻辑
            file_base = os.path.basename(file_path)
            
            # 读取文件内容
            try:
                logging.info(f"以UTF-8编码读取文件: {file_path}")
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception as e:
                logging.error(f"读取文件失败 {file_path}: {str(e)}")
                logging.info("尝试二进制模式读取文件")
                # 尝试二进制模式读取
                with open(file_path, 'rb') as f:
                    content_bytes = f.read()
                    try:
                        content = content_bytes.decode('utf-8', errors='replace')
                    except UnicodeDecodeError:
                        content = content_bytes.decode('latin1', errors='replace')
            
            # 查找SITE号
            site_id = self.find_site_id(content)
            logging.info(f"找到SITE号: {site_id}")
            
            # 查找测试单元
            results = []
            unit_count = 0
            
            # 使用匹配的开始和结束模式分割单元
            logging.info("开始查找测试单元")
            start_matches = list(self.patterns['unit_start'].finditer(content))
            end_matches = list(self.patterns['unit_end'].finditer(content))
            
            logging.info(f"找到 {len(start_matches)} 个开始标记和 {len(end_matches)} 个结束标记")
            
            if len(start_matches) > 0 and len(end_matches) > 0:
                # 确保有成对的开始/结束匹配
                unit_pairs = []
                for start_match in start_matches:
                    start_pos = start_match.start()
                    # 找到第一个在start_pos之后的end_match
                    for end_match in end_matches:
                        if end_match.end() > start_pos:
                            unit_pairs.append((start_pos, end_match.end()))
                            break
                
                logging.info(f"找到 {len(unit_pairs)} 个有效测试单元")
                
                # 处理每个测试单元
                for i, (start, end) in enumerate(unit_pairs):
                    logging.debug(f"处理第 {i+1} 个测试单元")
                    unit_content = content[start:end]
                    unit_results = self.process_test_unit(unit_content, site_id, file_path, f"TD{i+1}")
                    
                    if unit_results:
                        logging.debug(f"单元 {i+1} 处理完成，生成 {len(unit_results)} 个结果")
                        results.append(unit_results)
                        unit_count += 1
                    else:
                        logging.debug(f"单元 {i+1} 没有生成结果")
                    
                    # 更新进度
                    if progress_callback and unit_pairs:
                        progress = (i / len(unit_pairs)) * 100
                        progress_callback(progress)
            else:
                logging.warning(f"未找到测试单元: 开始标记={len(start_matches)}, 结束标记={len(end_matches)}")
            
            # 写入结果文件
            if output_dir and results:
                logging.info(f"写入 {len(results)} 个结果到输出目录")
                self.write_output_files(results, output_dir, site_id)
            else:
                if not output_dir:
                    logging.warning("未提供输出目录，跳过写入")
                if not results:
                    logging.warning("没有结果需要写入")
            
            logging.info(f"文件处理完成: {file_path}，共 {unit_count} 个测试单元，{len(results)} 个结果")
            
            # 保存结果数量
            result_count = len(results) if results else 0
            
            # 清理内存
            content = None
            results = None
            gc.collect()
            
            return result_count
            
        except Exception as e:
            logging.error(f"处理文件时出错 {file_path}: {str(e)}")
            logging.debug(traceback.format_exc())
            return 0
            
    def process_directory(self, dir_path, output_dir, progress_callback=None, max_workers=None):
        """处理目录中的所有日志文件
        
        Args:
            dir_path: 日志文件目录路径
            output_dir: 输出目录路径
            progress_callback: 进度回调函数
            max_workers: 最大工作线程数，默认为None（使用CPU核心数）
            
        Returns:
            int: 处理结果数量
        """
        if not os.path.exists(dir_path):
            raise FileNotFoundError(f"目录不存在: {dir_path}")
        if not os.path.isdir(dir_path):
            raise ValueError(f"不是一个目录: {dir_path}")
            
        # 获取目录中的所有txt文件
        txt_files = []
        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.lower().endswith('.txt') and not self.is_system_file(file):
                    txt_files.append(os.path.join(root, file))
                    
        if not txt_files:
            logging.warning(f"目录中没有txt文件: {dir_path}")
            return 0
            
        total_files = len(txt_files)
        processed_files = 0
        total_results = 0
        
        # 确定是否使用并行处理
        use_parallel = total_files >= 2  # 至少有2个文件才使用并行处理
        
        if use_parallel and max_workers is None:
            # 默认使用CPU核心数或4，取较小值
            max_workers = min(os.cpu_count() or 4, 8)
            
        if use_parallel:
            logging.info(f"使用 {max_workers} 个线程并行处理 {total_files} 个文件")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 创建任务并提交
                future_to_file = {
                    executor.submit(self.process_file, file_path, output_dir): file_path
                    for file_path in txt_files
                }
                
                # 处理结果
                for future in future_to_file:
                    file_path = future_to_file[future]
                    try:
                        result_count = future.result()
                        total_results += result_count
                        processed_files += 1
                        
                        # 更新总体进度
                        if progress_callback:
                            progress = (processed_files / total_files) * 100
                            progress_callback(progress)
                            
                    except Exception as e:
                        logging.error(f"处理文件异常 {file_path}: {str(e)}")
        else:
            # 串行处理
            for file_path in txt_files:
                try:
                    result_count = self.process_file(file_path, output_dir, progress_callback)
                    total_results += result_count
                    processed_files += 1
                    
                    # 更新总体进度
                    if progress_callback:
                        progress = (processed_files / total_files) * 100
                        progress_callback(progress)
                        
                except Exception as e:
                    logging.error(f"处理文件异常 {file_path}: {str(e)}")
                    
        logging.info(f"目录处理完成: {dir_path}，共处理 {processed_files} 个文件，生成 {total_results} 个结果")
        return total_results
            
    def write_output_files(self, results, output_dir, site_id):
        """将处理结果写入输出文件
        
        Args:
            results: 处理结果列表，每个元素是一个字典，键为unit_id，值为包含DUT的字典
            output_dir: 输出目录路径
            site_id: SITE编号
        """
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 添加更多日志信息，以便调试
        logging.info(f"准备写入 {len(results)} 个结果到输出目录: {output_dir}")
        
        # 遍历所有结果
        for i, result_dict in enumerate(results):
            logging.debug(f"处理结果 {i+1}/{len(results)}, 类型: {type(result_dict)}")
            
            # 确保result_dict是字典类型
            if not isinstance(result_dict, dict):
                logging.warning(f"跳过非字典类型的结果: {type(result_dict)}")
                continue
                
            # 遍历字典中的每个测试单元
            for unit_id, dut_dict in result_dict.items():
                logging.debug(f"处理单元 {unit_id}, 类型: {type(dut_dict)}")
                
                # 确保dut_dict是字典类型
                if not isinstance(dut_dict, dict):
                    logging.warning(f"跳过非字典类型的DUT字典: {type(dut_dict)}")
                    continue
                    
                # 为每个有效的DUT创建文件
                valid_duts = 0
                for dut_id, content in dut_dict.items():
                    if content is not None:  # 只处理有内容的DUT
                        valid_duts += 1
                        # 创建输出文件名
                        output_file = f"{unit_id}_SITE{site_id}_DUT{dut_id}.txt"
                        file_path = os.path.join(output_dir, output_file)
                        
                        # 写入文件
                        with open(file_path, 'w', encoding='utf-8') as f:
                            # 如果内容很长，可能是完整的CDT日志
                            if len(content) > 200:
                                f.write(content)
                            else:
                                # 如果内容较短，可能只是状态行
                                f.write(f"DUT[{dut_id}] 状态行:\n")
                                f.write(content)
                                f.write("\n")
                        
                        logging.debug(f"写入文件: {file_path}")
                
                logging.info(f"单元 {unit_id} 写入了 {valid_duts} 个有效DUT文件")

    def process_large_file(self, file_path, output_dir=None, progress_callback=None):
        """处理大文件，使用分块方式减少内存使用"""
        try:
            # 记录处理开始时间
            start_time = time.time()
            logging.info(f"开始处理文件: {file_path}")
            
            # 获取文件大小
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            logging.info(f"文件大小为 {file_size_mb:.2f}MB，超过阈值({self.large_file_threshold/(1024*1024):.1f}MB)，使用大文件处理逻辑")
            
            # 分块性能统计
            io_start_time = time.time()
            
            # 创建输出目录
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # 在内存映射模式下打开文件
            with open(file_path, 'rb') as f:
                # 记录IO耗时
                io_time = time.time() - io_start_time
                if progress_callback:
                    progress_callback(5, file_path=file_path, stage="IO", time_spent=io_time)
                
                # 使用内存映射
                io_start_time = time.time()
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                
                io_time = time.time() - io_start_time
                if progress_callback:
                    progress_callback(10, file_path=file_path, stage="mmap创建", time_spent=io_time)
                
                # 查找SITE号 - 使用更高效的方法
                site_id = None
                
                # 记录正则匹配开始时间
                regex_start_time = time.time()
                
                # 定位到文件前面的部分查找SITE - 使用更高效的方式
                header_size = min(10000, file_size)  # 只读取前10KB来查找站点号
                header_text = mm[:header_size].decode('utf-8', errors='ignore')
                
                # 使用更高效的方式查找SITE号 - 直接使用字符串查找
                site_match = None
                for i, line in enumerate(header_text.splitlines()[:250], 1):
                    if line.startswith('SITE:'):
                        site_id = line[5:].strip().lstrip('0')
                        if site_id:
                            logging.info(f"在第{i}行找到SITE号: {site_id}")
                            break
                
                # 记录正则匹配耗时
                regex_time = time.time() - regex_start_time
                if progress_callback:
                    progress_callback(15, file_path=file_path, stage="SITE号查找", time_spent=regex_time)
                
                # 如果没有找到SITE，使用文件名解析
                if not site_id:
                    try:
                        # 从文件名中提取S后面跟着的数字
                        import re
                        s_match = re.search(r'S(\d+)\.txt$', file_path)
                        if s_match:
                            site_id = s_match.group(1)
                            logging.info(f"从文件名提取SITE号: {site_id}")
                    except:
                        pass
                
                # 如果仍然没有找到SITE，使用默认值1
                if not site_id:
                    site_id = "1"
                    logging.info(f"未找到SITE号，使用默认值: {site_id}")
                
                # 开始分析测试单元
                unit_start_time = time.time()
                
                # 增加块大小以减少IO操作
                block_size = 16 * 1024 * 1024  # 16MB块
                total_blocks = file_size // block_size + (1 if file_size % block_size > 0 else 0)
                
                # 使用生成器减少内存使用
                def find_markers():
                    """生成器函数，逐块查找标记位置"""
                    for i in range(total_blocks):
                        # 更新进度
                        progress = 20 + int(40 * i / total_blocks)
                        if progress_callback:
                            progress_callback(progress, file_path=file_path, stage="扫描测试单元", time_spent=None)
                        
                        # 读取块
                        start_pos = i * block_size
                        mm.seek(start_pos)
                        block_bytes = mm.read(block_size)
                        # 使用更快的解码方式
                        block = block_bytes.decode('utf-8', errors='ignore')
                        
                        # 查找所有Start_of_Test位置
                        pos = 0
                        while True:
                            start_match = block.find('Start_of_Test -----', pos)
                            if start_match == -1:
                                break
                            yield ('start', start_pos + start_match)
                            pos = start_match + 20  # 20是标记长度
                        
                        # 查找所有Execution time位置
                        pos = 0
                        while True:
                            end_match = block.find('Execution time:', pos)
                            if end_match == -1:
                                break
                            # 结束位置是end_marker的末尾
                            end_pos = start_pos + end_match + 15  # 15是标记长度
                            # 查找end_marker后面的换行符，确保包含完整的行
                            newline_pos = block.find('\n', end_match + 15)
                            if newline_pos != -1:
                                end_pos = start_pos + newline_pos + 1  # +1 包含换行符
                            yield ('end', end_pos)
                            pos = end_match + 15
                
                # 收集标记位置
                start_positions = []
                end_positions = []
                
                # 使用生成器减少内存使用
                for marker_type, position in find_markers():
                    if marker_type == 'start':
                        start_positions.append(position)
                    else:
                        end_positions.append(position)
                
                # 根据Start_of_Test和Execution time位置配对形成测试单元
                # 确保每个Start_of_Test都与其后的第一个Execution time配对
                start_positions.sort()
                end_positions.sort()
                
                # 记录日志，帮助调试
                logging.info(f"找到 {len(start_positions)} 个Start_of_Test位置")
                logging.info(f"找到 {len(end_positions)} 个Execution time位置")
                
                # 配对Start_of_Test和Execution time
                unit_positions = []
                for start_pos in start_positions:
                    # 找到第一个大于start_pos的end_pos
                    matching_end = None
                    for end_pos in end_positions:
                        if end_pos > start_pos:
                            matching_end = end_pos
                            break
                    
                    if matching_end:
                        unit_positions.append((start_pos, matching_end))
                        # 从end_positions中移除已使用的位置，确保不会重复使用
                        end_positions.remove(matching_end)
                
                # 记录单元计数
                unit_count = len(unit_positions)
                logging.info(f"配对形成 {unit_count} 个测试单元")
                
                # 按照开始位置排序，确保TD1, TD2, TD3...的顺序正确
                unit_positions.sort(key=lambda x: x[0])
                
                # 记录单元扫描耗时
                unit_scan_time = time.time() - unit_start_time
                if progress_callback:
                    progress_callback(60, file_path=file_path, stage="测试单元扫描", time_spent=unit_scan_time)
                
                # 第二遍处理: 分析每个测试单元
                process_start_time = time.time()
                
                # 按照测试单元分组处理
                results = []  # 收集处理结果
                
                # 定义处理单元的函数
                def process_unit(unit_data):
                    i, (start_pos, end_pos) = unit_data
                    # 读取并处理测试单元
                    mm.seek(start_pos)
                    unit_content = mm.read(end_pos - start_pos).decode('utf-8', errors='ignore')
                    
                    # 为每个测试单元设置正确的unit_id (TD1, TD2, TD3...)
                    unit_id = f"TD{i+1}"
                    
                    # 记录日志，帮助调试
                    logging.info(f"处理测试单元 {unit_id}，起始位置: {start_pos}，结束位置: {end_pos}，长度: {end_pos - start_pos}")
                    
                    # 处理测试单元
                    unit_results = self.process_test_unit(unit_content, site_id, file_path, unit_id)
                    
                    # 释放内存
                    unit_content = None
                    gc.collect()
                    
                    if unit_results:
                        logging.info(f"单元 {i+1} (ID: {unit_id}) 处理完成，生成 {len(unit_results)} 个结果")
                        return unit_results
                    else:
                        logging.info(f"单元 {i+1} (ID: {unit_id}) 没有生成结果")
                        return None
                
                # 并行处理测试单元 - 使用线程池替代进程池
                if unit_count > 1:
                    # 确定最佳工作线程数
                    max_workers = min(os.cpu_count() or 4, unit_count, 8)  # 最多8个线程
                    
                    if max_workers > 1:
                        logging.info(f"使用 {max_workers} 个线程并行处理 {unit_count} 个测试单元")
                        
                        # 创建任务列表
                        unit_data = [(i, pos) for i, pos in enumerate(unit_positions)]
                        
                        # 使用线程池处理
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            # 分批处理，避免一次性创建太多线程
                            batch_size = max(1, len(unit_data) // max_workers)
                            for i in range(0, len(unit_data), batch_size):
                                batch = unit_data[i:i+batch_size]
                                # 并行执行并收集结果
                                for unit_result in executor.map(process_unit, batch):
                                    if unit_result:  # 确保结果不为空
                                        results.append(unit_result)
                                
                                # 更新进度
                                progress = 60 + int(35 * min(i + batch_size, len(unit_data)) / len(unit_data))
                                if progress_callback:
                                    progress_callback(progress, file_path=file_path, stage="处理测试单元批次", time_spent=None)
                                
                                # 强制回收内存
                                gc.collect()
                    else:
                        # 单线程处理
                        for i, (start_pos, end_pos) in enumerate(unit_positions):
                            # 更新进度
                            progress = 60 + int(35 * (i + 1) / len(unit_positions))
                            if progress_callback:
                                progress_callback(progress, file_path=file_path, stage="处理测试单元", time_spent=None)
                            
                            # 处理单元
                            unit_result = process_unit((i, (start_pos, end_pos)))
                            if unit_result:
                                results.append(unit_result)
                            
                            # 每处理5个单元强制回收一次内存
                            if (i + 1) % 5 == 0:
                                gc.collect()
                else:
                    # 只有一个单元，直接处理
                    if unit_positions:
                        unit_result = process_unit((0, unit_positions[0]))
                        if unit_result:
                            results.append(unit_result)
                
                # 记录处理测试单元耗时
                process_time = time.time() - process_start_time
                if progress_callback:
                    progress_callback(95, file_path=file_path, stage="处理测试单元", time_spent=process_time)
                
                # 所有测试单元处理完成后，统一写入结果文件
                if output_dir and results:
                    logging.info(f"写入 {len(results)} 个结果到输出目录: {output_dir}")
                    # 添加更多日志信息，以便调试
                    for i, result in enumerate(results):
                        logging.debug(f"结果 {i+1} 类型: {type(result)}")
                        if isinstance(result, dict):
                            for unit_id, dut_dict in result.items():
                                logging.debug(f"  单元 {unit_id} 类型: {type(dut_dict)}")
                                if isinstance(dut_dict, dict):
                                    valid_duts = sum(1 for v in dut_dict.values() if v is not None)
                                    logging.debug(f"    有效DUT数量: {valid_duts}")
                    
                    self.write_output_files(results, output_dir, site_id)
                else:
                    if not output_dir:
                        logging.warning("未提供输出目录，跳过写入")
                    if not results:
                        logging.warning("没有结果需要写入")
                    logging.info(f"输出目录: {output_dir}, 结果数量: {len(results) if results else 0}")
                
                # 关闭内存映射
                mm.close()
            
            # 记录总处理耗时
            total_time = time.time() - start_time
            logging.info(f"处理文件完成: {file_path}, 耗时: {total_time:.2f}秒")
            
            # 更新进度到100%
            if progress_callback:
                progress_callback(100, file_path=file_path, stage="总处理", time_spent=total_time)
            
            # 强制回收内存
            gc.collect()
            
            return len(results) if results else 0
            
        except Exception as e:
            logging.error(f"处理文件异常 {file_path}: {str(e)}")
            logging.error(traceback.format_exc())
            return 0

def print_progress(current, total, description="进度", bar_length=50):
    """显示进度条
    Args:
        current: 当前处理的文件数
        total: 总文件数
        description: 进度条描述
        bar_length: 进度条长度
    """
    percent = float(current) / total if total > 0 else 0
    filled_length = int(round(percent * bar_length))
    bar = '=' * (filled_length - 1) + '>' if percent < 1 else '=' * filled_length
    spaces = ' ' * (bar_length - len(bar))
    
    # 使用更简洁的格式显示进度
    sys.stdout.write(
        f"\r{description}: [{bar}{spaces}] {percent:>7.2%}"
    )
    sys.stdout.flush()
    
    if current == total:
        sys.stdout.write('\n')
        sys.stdout.flush()

def progress_callback(percent, **kwargs):
    """进度回调函数
    Args:
        percent: 进度百分比
        **kwargs: 其他参数，包括file_path、stage和time_spent
    """
    file_path = kwargs.get('file_path', '')
    
    # 只显示文件名和进度百分比，使显示更简洁
    file_name = os.path.basename(file_path) if file_path else ''
    description = file_name if file_name else "处理中"
    print_progress(percent, 100, description)

def main():
    """CDT日志解析工具主函数
    
    用法:
        python cdt_log_parser.py <input_path> [--output-dir <output_dir>]
        
    参数:
        input_path: 输入文件或目录的路径
        --output-dir: 可选，指定输出目录名称，默认为'cdt_logs_output'
        
    示例:
        处理单个文件:
        python cdt_log_parser.py test.txt
        
        处理整个目录:
        python cdt_log_parser.py ./test_logs
        
        指定输出目录:
        python cdt_log_parser.py test.txt --output-dir my_output
    """
    # 记录开始时间
    start_time = time.time()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("cdt_parser.log"),
        ]
    )
    
    # 设置控制台日志级别为WARNING，减少终端输出
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logging.getLogger('').addHandler(console)
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='CDT日志解析工具')
    
    parser.add_argument(
        'input_path',
        help='输入文件或目录的路径'
    )
    parser.add_argument(
        '--output-dir',
        help='输出目录名称，默认为"cdt_logs_output"',
        default='cdt_logs_output'
    )
    
    args = parser.parse_args()
    
    try:
        # 确定输出目录路径
        if os.path.isdir(args.input_path):
            output_dir = os.path.join(args.input_path, args.output_dir)
        else:
            output_dir = os.path.join(os.path.dirname(args.input_path), args.output_dir)
        
        # 清空输出目录
        if os.path.exists(output_dir):
            logging.info(f"清空输出目录: {output_dir}")
            shutil.rmtree(output_dir)
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        logging.info(f"创建输出目录: {output_dir}")
        
        parser = CDTLogParser()
        if os.path.isdir(args.input_path):
            parser.process_directory(args.input_path, output_dir, progress_callback=progress_callback)
        else:
            parser.process_file(args.input_path, output_dir, progress_callback=progress_callback)
        
        # 计算并显示总执行时间
        end_time = time.time()
        execution_time = end_time - start_time
        logging.info(f"总执行时间: {execution_time:.2f}秒")
        print(f"\n总执行时间: {execution_time:.2f}秒")
        
    except Exception as e:
        logging.error(f"程序执行出错: {str(e)}")
        logging.debug(traceback.format_exc())
        sys.exit(1)

if __name__ == '__main__':
    main() 