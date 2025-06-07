#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
构建CDT日志解析器应用程序
此脚本用于打包应用程序并包含所有必要的资源文件
"""

import os
import sys
import shutil
import subprocess

def build_app():
    """构建应用程序"""
    print("开始构建CDT日志解析器应用程序...")
    
    # 检查是否安装了PyInstaller
    try:
        import PyInstaller
        print(f"已检测到PyInstaller版本: {PyInstaller.__version__}")
    except ImportError:
        print("未检测到PyInstaller，正在安装...")
        subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # 确保icon.jpg存在
    if not os.path.exists("icon.jpg"):
        print("警告: 未找到icon.jpg文件，将使用默认图标")
    
    # 创建spec文件内容
    spec_content = """# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['cdt_log_parser_ui.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.jpg', '.'), ('README.md', '.'), ('config.ini', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CDT日志解析器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.jpg',
)
"""
    
    # 写入spec文件
    with open("cdt_log_parser.spec", "w", encoding="utf-8") as f:
        f.write(spec_content)
    
    print("已创建PyInstaller规范文件")
    
    # 运行PyInstaller
    print("正在运行PyInstaller...")
    result = subprocess.call(["pyinstaller", "cdt_log_parser.spec", "--clean"])
    
    if result == 0:
        print("应用程序构建成功!")
        print("可执行文件位于: dist/CDT日志解析器.exe")
    else:
        print("构建失败，请检查错误信息")

if __name__ == "__main__":
    build_app() 