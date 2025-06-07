#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
创建应用程序图标
此脚本将提供的图片转换为应用程序图标格式
"""

import os
import sys
from PIL import Image

def create_icon_from_image(input_image_path, output_icon_path='icon.jpg'):
    """
    将输入图片转换为应用程序图标
    
    参数:
        input_image_path: 输入图片路径
        output_icon_path: 输出图标路径，默认为icon.jpg
    """
    try:
        # 打开原始图片
        img = Image.open(input_image_path)
        
        # 调整大小为标准图标尺寸 (256x256)
        img = img.resize((256, 256), Image.LANCZOS)
        
        # 保存为JPG格式
        img.save(output_icon_path, "JPEG", quality=95)
        
        print(f"图标已成功创建: {output_icon_path}")
        return True
    except Exception as e:
        print(f"创建图标时出错: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("用法: python create_icon.py <图片路径>")
        return
    
    input_image_path = sys.argv[1]
    if not os.path.exists(input_image_path):
        print(f"错误: 找不到图片文件 '{input_image_path}'")
        return
    
    create_icon_from_image(input_image_path)

if __name__ == "__main__":
    main() 