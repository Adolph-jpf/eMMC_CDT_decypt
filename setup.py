from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy

# 定义要编译的Cython模块
extensions = [
    Extension(
        "cdt_log_parser_cy",  # 输出模块名
        ["cdt_log_parser_cy.pyx"],  # 源文件
        include_dirs=[numpy.get_include()],  # 如果使用numpy，需要包含头文件
        extra_compile_args=["-O3", "-march=native", "-ffast-math"],  # 优化编译选项
    )
]

setup(
    name="CDTLogParser",
    version="1.0",
    description="CDT Log Parser with Cython optimization",
    author="Your Name",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": 3,
            "boundscheck": False,
            "wraparound": False,
            "initializedcheck": False,
            "cdivision": True,
        },
    ),
    zip_safe=False,
) 