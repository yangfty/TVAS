#!/usr/bin/env python3
"""
判断文件类型并将 DOS 格式转换为 Unix 格式

检测文件是否包含 DOS 换行符 (\\r\\n)，如果是则转换为 Unix 格式 (\\n)

用法:
    python ifdos2unix.py file.txt
    python ifdos2unix.py file.txt -o converted.txt
"""

import argparse
import os
import sys


def detect_line_ending(filepath: str) -> str:
    """检测文件的主要换行符类型"""
    with open(filepath, "rb") as f:
        # 读取前 64KB 做检测
        chunk = f.read(65536)

    crlf_count = chunk.count(b"\r\n")
    cr_only = chunk.count(b"\r") - crlf_count  # 减去 \r\n 中的 \r
    lf_count = chunk.count(b"\n") - crlf_count  # 减去 \r\n 中的 \n

    if crlf_count > max(cr_only, lf_count):
        return "dos"
    elif cr_only > max(crlf_count, lf_count):
        return "mac"
    else:
        return "unix"


def dos2unix(input_path: str, output_path: str) -> int:
    """将 DOS 格式转换为 Unix 格式"""
    with open(input_path, "rb") as f:
        content = f.read()

    # 先转换 \r\n → \n (DOS → Unix)
    converted = content.replace(b"\r\n", b"\n")
    # 再转换残留的 \r → \n (Mac → Unix)
    converted = converted.replace(b"\r", b"\n")

    with open(output_path, "wb") as f:
        f.write(converted)

    return len(content) - len(converted)  # 移除的字节数


def main():
    parser = argparse.ArgumentParser(
        description="检测文件格式并转换为 Unix 换行符",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python ifdos2unix.py file.txt                # 检测格式
  python ifdos2unix.py file.txt -o unix.txt    # 转换
        """
    )
    parser.add_argument("input", help="输入文件")
    parser.add_argument("-o", "--output", help="输出文件（不指定则只检测不转换）")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"错误: 文件不存在: {args.input}")
        sys.exit(1)

    # 检测格式
    ending_type = detect_line_ending(args.input)
    type_names = {"dos": "DOS/Windows (\\r\\n)", "mac": "Mac (\\r)", "unix": "Unix (\\n)"}

    print(f"文件: {args.input}")
    print(f"格式: {type_names.get(ending_type, ending_type)}")

    if ending_type == "unix":
        print("文件已经是 Unix 格式，无需转换。")
        if not args.output:
            return

    # 转换
    if args.output:
        removed_bytes = dos2unix(args.input, args.output)
        print(f"转换完成 → {args.output}")
        print(f"移除了 {removed_bytes} 个多余的 '\\r' 字节")
    else:
        if ending_type != "unix":
            print(f"提示: 使用 -o 参数指定输出文件以进行转换")


if __name__ == "__main__":
    main()
