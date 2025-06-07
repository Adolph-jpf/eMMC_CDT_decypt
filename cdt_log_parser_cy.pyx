# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True
# distutils: define_macros=NPY_NO_DEPRECATED_API=NPY_1_7_API_VERSION

import re
import logging
from collections import defaultdict
import gc
from libc.string cimport strstr, strlen, memcpy, memcmp
from cpython.bytes cimport PyBytes_FromStringAndSize
from cpython.unicode cimport PyUnicode_DecodeUTF8

# 预编译常用的字符串匹配模式
SKIP_PATTERNS = [
    'EMMC Transport:',
    '[Property]',
    'bytearray',
    'Transport:',
    'CDT Data <IN>:',
    'Dut:',
    'FORMAT STATUS:'
]

# 预编译需要保留的内容模式
KEEP_PATTERNS = [
    'X:', 'Y:', 'LOT:', 'TestNum_', 'Temp:', '#TT'
]

# 正则表达式模式
cdef dict PATTERNS = {
    'fail_functional': re.compile(r'DUT\d+ -- soft bin 0xffffffff -- hard bin 7 -- fail_functional', re.DOTALL),
    'property_end': re.compile(r'\s*\[Property\]--->Type:\[7\], Size:\[512\] Dataproperty:bytearray:512', re.DOTALL),
}

# 辅助函数，检查字符串是否包含任何模式
cdef bint contains_any_pattern(str text, list patterns):
    cdef str pattern
    for pattern in patterns:
        if pattern in text:
            return True
    return False

# 辅助函数，检查字符串是否包含字母数字字符
cdef bint contains_alnum(str text):
    cdef int i
    cdef int length = len(text)
    for i in range(length):
        if text[i].isalnum():
            return True
    return False

cpdef str clean_cdt_log(str content):
    """清理CDT日志内容，只保留有效数据"""
    # 声明所有变量
    cdef int emmc_start, property_end, i
    cdef list lines, cleaned_lines, filtered_lines
    cdef bint valid_data, has_alnum
    cdef str line, pattern, dut_part
    cdef int dut_num, soft_bin_pos
    
    # 移除EMMC传输相关的内容 - 使用字符串查找替代正则表达式
    emmc_start = content.find('EMMC Transport: SingleBlock Read')
    if emmc_start != -1:
        property_end = content.find('[Property]--->Type:[7], Size:[512] Dataproperty:bytearray:512', emmc_start)
        if property_end != -1:
            content = content[:emmc_start] + content[property_end + 70:]  # 70是模式长度加一些余量
    
    # 初始化变量
    lines = content.split('\n')
    cleaned_lines = []
    filtered_lines = []
    valid_data = False
    
    # 手动过滤无效行，避免使用列表推导式
    for line in lines:
        line = line.strip()
        if not line or line.isspace():
            continue
        if line == '[CDT log] :~~':
            continue
        if 'nul' in line.lower():
            continue
        if '[STlog]' in line:
            continue
        if line.startswith('DUT[') and 'CDT log info:' in line:
            continue
        if line.endswith('[Property]--->Type:[7], Size:[512] Dataproperty:bytearray:512'):
            continue
        filtered_lines.append(line)
    
    # 处理预过滤后的行
    for line in filtered_lines:
        # 检查是否包含跳过模式
        if contains_any_pattern(line, SKIP_PATTERNS):
            continue
            
        # 检查是否包含字母数字字符
        has_alnum = contains_alnum(line)
        
        # 如果没有字母数字字符，检查是否包含保留模式
        if not has_alnum:
            if not contains_any_pattern(line, KEEP_PATTERNS):
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

# 辅助函数，创建DUT字典
cdef dict create_dut_dict():
    cdef dict result = {}
    cdef int i
    for i in range(1, 25):
        result[f"{i:02d}"] = None
    return result

cpdef dict process_test_unit(str unit_content, str site_id, str file_path, str unit_id):
    """处理单个测试单元的内容"""
    # 声明所有变量
    cdef dict dut_dict, dut_status_lines, dut_blocks, result
    cdef list unit_lines, status_section_lines, blocks
    cdef int execution_time_index, i, start_index, status_lines_found, dut_num
    cdef int cdt_start, cdt_end, pos, start_pos, end_pos, dut_start, dut_end, valid_duts
    cdef str execution_time_marker, status_section, status_line_marker
    cdef str line, dut_part, dut_num_str, formatted_dut_id, status_line
    cdef str cdt_content, block_start_marker, block_end_marker, block, raw_dut_id
    cdef str cleaned_block, dut_id, header, combined_content
    
    logging.info(f"处理测试单元: {unit_id}")
    
    # 创建固定的24个DUT字典 - 使用辅助函数
    dut_dict = create_dut_dict()
    
    # 获取测试单元的行 - 使用更高效的方式
    unit_lines = unit_content.splitlines()
    logging.info(f"{unit_id} 测试单元包含 {len(unit_lines)} 行")
    
    # 查找Execution time:的位置 - 使用更高效的字符串查找
    execution_time_index = -1
    execution_time_marker = 'Execution time:'
    
    # 从后向前查找更高效，因为Execution time通常在末尾
    for i in range(len(unit_lines) - 1, -1, -1):
        if i < len(unit_lines) - 50:
            break
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
                    cleaned_block = clean_cdt_log(block)
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