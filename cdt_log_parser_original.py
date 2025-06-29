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

# 监控性能的全局变量
PERFORMANCE_STATS = defaultdict(float)
FILE_STATS = {}

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cdt_parser.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

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
        
        # 预编译常用的字符串匹配模式
        self.skip_patterns = [
            'EMMC Transport:',
            '[Property]',
            'bytearray',
            'Transport:',
            'CDT Data <IN>:',
            'Dut:',
            'FORMAT STATUS:'
        ]
        
        # 预编译需要保留的内容模式
        self.keep_patterns = ['X:', 'Y:', 'LOT:', 'TestNum_', 'Temp:', '#TT']
        
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
        
    def clean_cdt_log(self, content):
        """清理CDT日志内容，只保留有效数据"""
        # 移除EMMC传输相关的内容
        content = self.patterns['emmc_transport'].sub('', content)
        
        # 初始化变量
        lines = content.split('\n')
        cleaned_lines = []
        valid_data = False
        
        # 处理每一行
        for line in lines:
            line = line.strip()
            
            # 跳过无效行
            if not line or line.isspace():
                continue
            if line == '[CDT log] :~~':
                continue
            if self.patterns['property_end'].match(line):
                continue
            # 使用更严格的nul检查
            if 'nul' in line.lower():
                continue
            if '[STlog]' in line:
                continue
            
            # 跳过所有DUT header行
            if line.startswith('DUT[') and 'CDT log info:' in line:
                continue
            
            # 处理其他行
            skip_line = False
            for pattern in self.skip_patterns:
                if pattern in line:
                    skip_line = True
                    break
                    
            if not skip_line:
                # 检查是否包含字母数字字符或保留模式
                has_alnum = False
                for c in line:
                    if c.isalnum():
                        has_alnum = True
                        break
                        
                has_keep_pattern = False
                if not has_alnum:
                    for pattern in self.keep_patterns:
                        if pattern in line:
                            has_keep_pattern = True
                            break
                            
                if has_alnum or has_keep_pattern:
                    # 格式化DUT状态行
                    if ' -- soft bin 0x' in line and line.startswith('DUT'):
                        dut_num = int(line.split()[0][3:])
                        line = f"DUT{dut_num:02d}{line[line.find(' -- '):]}"
                    cleaned_lines.append(line)
                    valid_data = True
        
        # 返回处理后的内容
        if valid_data:
            return '\n'.join(cleaned_lines)
        return None


    
    def process_dut_block(self, content, dut_id, unit_id):
        """处理单个DUT块的数据"""
        # 检查是否为失败记录
        if self.patterns['fail_functional'].search(content):
            logging.info(f"跳过失败的DUT: {dut_id}")
            return None
            
        # 提取CDT日志部分
        cdt_logs = []
        status_line = None
        
        # 首先找到状态行
        for line in content.split('\n'):
            line = line.strip()
            # 使用更宽松的模式匹配状态行
            if ' -- soft bin 0x' in line and line.startswith(f'DUT'):
                # 提取DUT编号并格式化
                dut_num = int(line.split()[0][3:])  # 去掉'DUT'前缀并转换为整数
                # 对于小于10的DUT编号，使用两位数格式
                if dut_num < 10:
                    status_line = f"DUT0{dut_num}{line[line.find(' -- '):]}"
                else:
                    status_line = line
                
        # 然后处理CDT日志
        # 首先找到CDT测试部分
        cdt_sections = self.patterns['cdt_section'].finditer(content)
        for section in cdt_sections:
            section_content = section.group(0)
            # 在CDT测试部分中查找CDT日志
            for match in self.patterns['cdt_log_block'].finditer(section_content):
                log_content = match.group(0)
                cdt_logs.append(log_content)
                #cleaned_log = self.clean_cdt_log(log_content)
                #if cleaned_log:
                #    cdt_logs.append(cleaned_log)
                
        if not cdt_logs:
            logging.debug(f"DUT {dut_id} 没有有效的CDT日志")
            return None
            
        # 合并日志内容
        combined_content = '\n'.join(filter(None, cdt_logs))  # 过滤掉None值
        if not combined_content.strip():
            logging.debug(f"DUT {dut_id} 合并后的日志为空")
            return None
            
        if status_line:
            # 确保状态行在文件末尾单独一行
            combined_content = f"{combined_content.rstrip()}\n{status_line}"
            
        return {
            'content': combined_content,
            'dut_id': dut_id,
            'unit_id': unit_id
        }
        
    def process_test_unit(self, unit_content, site_id, file_path, unit_id=None):
        """处理单个测试单元的内容
        
        Args:
            unit_content: 测试单元的内容
            site_id: SITE编号
            file_path: 日志文件路径
            unit_id: 测试单元编号，如果未提供则自动生成
            
        Returns:
            list: 包含处理结果的字典列表，每个字典包含content、dut_id和unit_id
        """
        results = []
        dut_blocks = defaultdict(list)  # 使用DUT编号作为键存储日志块
        dut_status_lines = {}  # 存储每个DUT的状态行
        
        # 如果未提供unit_id，则使用计数器生成测试单元编号
        if unit_id is None:
            with self.lock:
                unit_num = self.td_counters[file_path]
                self.td_counters[file_path] += 1
                unit_id = f"TD{unit_num + 1}"
        
        # 首先找到CDT测试部分 - 使用字符串查找代替正则表达式
        cdt_start = unit_content.find('TestBlock = tb_MacawCdtMtstTest :')
        if cdt_start == -1:
            return results
            
        # 查找CDT部分的结束位置
        cdt_end = unit_content.find('TestItem:tb_MacawCdtMtstTest Test Time:', cdt_start)
        if cdt_end == -1:
            cdt_end = len(unit_content)
            
        # 提取CDT内容
        cdt_content = unit_content[cdt_start:cdt_end]
        
        # 重要：只提取当前测试单元的状态行
        # 从测试单元的最后30行中查找状态行（状态行通常在测试单元的末尾）
        unit_lines = unit_content.splitlines()
        status_section = '\n'.join(unit_lines[-30:] if len(unit_lines) >= 30 else unit_lines)
        
        # 提取DUT状态行
        status_line_marker = ' -- soft bin 0x'
        for line in status_section.split('\n'):
            if status_line_marker in line and line.startswith('DUT'):
                # 提取DUT编号并格式化为两位数字符串
                dut_part = line.split()[0]
                if len(dut_part) > 3:  # 确保有'DUT'前缀
                    dut_num_str = dut_part[3:]  # 原始字符串（如"02"或"2"）
                    try:
                        dut_num = int(dut_num_str)  # 转为整数（如2）
                        formatted_dut_id = f"{dut_num:02d}"  # 格式化为"02"
                        status_line = f"DUT{formatted_dut_id}{line[line.find(status_line_marker):]}"
                        # 使用格式化后的DUT编号作为键
                        dut_status_lines[formatted_dut_id] = status_line
                        logging.debug(f"为 {unit_id} 找到状态行: DUT{formatted_dut_id} {status_line}")
                    except ValueError:
                        continue
        
        # 处理每个DUT的CDT日志块 - 使用字符串查找代替正则表达式
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
            
            # 提取DUT ID
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
                        dut_blocks[formatted_dut_id].append(cleaned_block)
                except (ValueError, IndexError):
                    pass
                    
            # 移动到下一个位置
            pos = end_pos + len(block_end_marker)
        
        # 合并每个DUT的日志块并添加状态行
        for dut_id, blocks in dut_blocks.items():
            if blocks:  # 只处理有内容的DUT
                # 添加DUT header
                header = f"DUT[{dut_id}] CDT log info:"
                blocks.insert(0, header)
                
                # 合并所有块
                combined_content = '\n'.join(blocks)
                
                # 添加状态行（如果有）
                if dut_id in dut_status_lines:
                    # 确保状态行在文件末尾单独一行
                    combined_content = f"{combined_content.rstrip()}\n{dut_status_lines[dut_id]}"
                    
                results.append({
                    'content': combined_content,
                    'dut_id': dut_id,
                    'unit_id': f"{unit_id}_SITE{site_id}"
                })
        
        return results
        
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
                        results.extend(unit_results)
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
            
            # 清理内存
            content = None
            results = None
            gc.collect()
            
            return len(results) if results else 0
            
        except Exception as e:
            logging.error(f"处理文件时出错 {file_path}: {str(e)}")
            logging.debug(traceback.format_exc())
            return 0
            
    def process_directory(self, dir_path, output_dir, progress_callback=None, max_workers=None):
        """处理目录中的所有日志文件
        
        Args:
            dir_path: 目录路径
            output_dir: 输出目录路径
            progress_callback: 进度回调函数
            max_workers: 最大工作线程数
            
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
            results: 处理结果列表
            output_dir: 输出目录路径
            site_id: SITE编号
        """
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # 按DUT ID分组结果
        dut_groups = defaultdict(list)
        for result in results:
            if not result:
                continue
                
            dut_id = result.get('dut_id')
            if not dut_id:
                continue
                
            unit_id = result.get('unit_id', 'TD1')
            content = result.get('content', '')
            
            if content:
                dut_groups[(unit_id, dut_id)].append(content)
                
        # 写入输出文件
        for (unit_id, dut_id), contents in dut_groups.items():
            # 格式化文件名，确保DUT ID是两位数
            try:
                dut_num = int(dut_id)
                formatted_dut_id = f"{dut_num:02d}"
            except ValueError:
                formatted_dut_id = dut_id  # 如果无法转换为数字，保持原样
                
            # 检查unit_id是否已经包含SITE信息，避免重复
            if "_SITE" in unit_id:
                # 已包含SITE信息，直接使用
                output_file = f"{unit_id}_DUT{formatted_dut_id}.txt"
            else:
                # 不包含SITE信息，添加
                output_file = f"{unit_id}_SITE{site_id}_DUT{formatted_dut_id}.txt"
                
            file_path = os.path.join(output_dir, output_file)
            
            # 检查是否需要追加内容
            mode = 'a' if os.path.exists(file_path) else 'w'
            
            with open(file_path, mode, encoding='utf-8') as f:
                for content in contents:
                    f.write(content)
                    # 确保每个内容块之间有换行符
                    if not content.endswith('\n'):
                        f.write('\n')
                    
            logging.debug(f"写入文件: {file_path}")

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
            
            # 使用mmap减少内存使用
            logging.info(f"使用优化方法处理大文件: {file_path}")
            
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
                
                # 查找SITE号
                site_id = None
                
                # 记录正则匹配开始时间
                regex_start_time = time.time()
                
                # 定位到文件前面的部分查找SITE
                header_size = min(10000, file_size)  # 只读取前10KB来查找站点号
                header_text = mm[:header_size].decode('utf-8', errors='ignore')
                
                # 使用更高效的方式查找SITE号
                site_match = None
                for i, line in enumerate(header_text.splitlines()[:250], 1):
                    if line.startswith('SITE:'):
                        site_match = self.patterns['site'].match(line)
                        if site_match:
                            site_id = site_match.group(1)
                            logging.info(f"在第{i}行找到SITE号: {site_id}")
                            break
                
                # 记录正则匹配耗时
                regex_time = time.time() - regex_start_time
                if progress_callback:
                    progress_callback(15, file_path=file_path, stage="正则匹配", time_spent=regex_time)
                
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
                
                # 查找测试单元
                # 测试单元计数器
                unit_count = 0
                
                # 开始分析测试单元
                unit_start_time = time.time()
                
                # 增加块大小以减少IO操作
                block_size = 16 * 1024 * 1024  # 16MB块
                total_blocks = file_size // block_size + (1 if file_size % block_size > 0 else 0)
                
                # 记录测试单元的起始结束位置
                unit_positions = []
                
                # 第一遍扫描: 识别所有测试单元的位置
                current_unit_start = None
                last_pos = 0
                
                # 使用更高效的字符串搜索而不是正则表达式
                start_marker = 'Start_of_Test -----'
                end_marker = 'Execution time:'
                
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
                    
                    # 查找所有测试单元的开始位置
                    pos = 0
                    while True:
                        start_match = block.find(start_marker, pos)
                        if start_match == -1:
                            break
                        
                        # 如果前一个单元还在进行中，结束它
                        if current_unit_start is not None:
                            unit_positions.append((current_unit_start, start_pos + start_match))
                            current_unit_start = None
                        
                        # 记录新单元的开始位置
                        current_unit_start = start_pos + start_match
                        pos = start_match + len(start_marker)
                    
                    # 查找所有测试单元的结束位置
                    pos = 0
                    while True:
                        end_match = block.find(end_marker, pos)
                        if end_match == -1:
                            break
                        
                        # 如果有一个单元在进行中，结束它
                        if current_unit_start is not None:
                            unit_positions.append((current_unit_start, start_pos + end_match + len(end_marker)))
                            current_unit_start = None
                        
                        pos = end_match + len(end_marker)
                    
                    last_pos = start_pos + len(block)
                
                # 如果最后一个单元没有结束，使用文件末尾作为结束
                if current_unit_start is not None:
                    unit_positions.append((current_unit_start, file_size))
                
                # 记录单元计数
                unit_count = len(unit_positions)
                logging.info(f"找到 {unit_count} 个测试单元")
                
                # 记录单元扫描耗时
                unit_scan_time = time.time() - unit_start_time
                if progress_callback:
                    progress_callback(60, file_path=file_path, stage="测试单元扫描", time_spent=unit_scan_time)
                
                # 第二遍处理: 分析每个测试单元
                process_start_time = time.time()
                
                # 按照测试单元分组处理
                results = []  # 收集处理结果
                
                # 并行处理测试单元
                from concurrent.futures import ThreadPoolExecutor
                max_workers = min(os.cpu_count() or 4, unit_count, 8)  # 最多8个线程
                
                if unit_count > 1 and max_workers > 1:
                    logging.info(f"使用 {max_workers} 个线程并行处理 {unit_count} 个测试单元")
                    
                    def process_unit(unit_data):
                        i, (start_pos, end_pos) = unit_data
                        # 读取并处理测试单元
                        mm.seek(start_pos)
                        unit_content = mm.read(end_pos - start_pos).decode('utf-8', errors='ignore')
                        # 为每个测试单元设置正确的unit_id (TD1, TD2, TD3...)
                        unit_id = f"TD{i+1}"
                        unit_results = self.process_test_unit(unit_content, site_id, file_path, unit_id)
                        if unit_results:
                            logging.info(f"单元 {i+1} (ID: {unit_id}) 处理完成，生成 {len(unit_results)} 个结果")
                            return unit_results
                        else:
                            logging.info(f"单元 {i+1} (ID: {unit_id}) 没有生成结果")
                            return []
                    
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        # 创建任务列表
                        unit_data = [(i, pos) for i, pos in enumerate(unit_positions)]
                        # 并行执行并收集结果
                        for unit_results in executor.map(process_unit, unit_data):
                            results.extend(unit_results)
                else:
                    # 串行处理
                    for i, (start_pos, end_pos) in enumerate(unit_positions):
                        # 更新进度
                        progress = 60 + int(35 * (i + 1) / len(unit_positions))
                        if progress_callback:
                            progress_callback(progress, file_path=file_path, stage="处理测试单元", time_spent=None)
                        
                        # 读取并处理测试单元
                        mm.seek(start_pos)
                        unit_content = mm.read(end_pos - start_pos).decode('utf-8', errors='ignore')
                        # 为每个测试单元设置正确的unit_id (TD1, TD2, TD3...)
                        unit_id = f"TD{i+1}"
                        unit_results = self.process_test_unit(unit_content, site_id, file_path, unit_id)
                        if unit_results:
                            logging.info(f"单元 {i+1} (ID: {unit_id}) 处理完成，生成 {len(unit_results)} 个结果")
                            results.extend(unit_results)
                        else:
                            logging.info(f"单元 {i+1} (ID: {unit_id}) 没有生成结果")
                
                # 记录处理测试单元耗时
                process_time = time.time() - process_start_time
                if progress_callback:
                    progress_callback(95, file_path=file_path, stage="处理测试单元", time_spent=process_time)
                
                # 所有测试单元处理完成后，统一写入结果文件
                if output_dir and results:
                    logging.info(f"写入 {len(results)} 个结果到输出目录: {output_dir}")
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
    
    # 使用更清晰的格式显示进度
    sys.stdout.write(
        f"\r{description}: [{bar}{spaces}] {percent:>7.2%} ({current}/{total}) "
    )
    sys.stdout.flush()
    
    if current == total:
        sys.stdout.write('\n')
        sys.stdout.flush()

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
    parser = argparse.ArgumentParser(
        description='CDT日志解析工具 - 用于解析和提取CDT测试日志中的有效数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''
            示例:
              处理单个文件:
              %(prog)s test.txt
              
              处理整个目录:
              %(prog)s ./test_logs
              
              指定输出目录:
              %(prog)s test.txt --output-dir my_output
        ''')
    )
    
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
        parser = CDTLogParser()
        if os.path.isdir(args.input_path):
            parser.process_directory(args.input_path, args.output_dir)
        else:
            output_dir = os.path.join(os.path.dirname(args.input_path), args.output_dir)
            parser.process_file(args.input_path, output_dir)
        
    except Exception as e:
        logging.error(f"程序执行出错: {str(e)}")
        logging.debug(traceback.format_exc())
        sys.exit(1)

if __name__ == '__main__':
    main() 