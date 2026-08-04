#!/usr/bin/env python3
"""
重命名 TransDecoder GFF3 文件中的基因名前缀

原始 GFF3 中基因ID可能包含 "Hg" 前缀 (homologous genes)
将其替换为 "Ug" 前缀 (unigene)

用法:
    python rename_transdecoder_gff3.py input.gff3 --output modified.gff3
"""

import argparse
import os
import sys


def rename_gff3(input_gff3: str, output_gff3: str,
                old_prefix: str = "Hg", new_prefix: str = "Ug"):
    """
    重命名 GFF3 文件中的基因/转录本前缀
    """
    modified_count = 0
    total_lines = 0

    with open(input_gff3, "r", encoding="utf-8") as fin, \
         open(output_gff3, "w", encoding="utf-8") as fout:

        for line in fin:
            total_lines += 1
            if not line.startswith("#") and line.strip():
                if old_prefix in line:
                    line = line.replace(old_prefix, new_prefix)
                    modified_count += 1
            fout.write(line)

    return total_lines, modified_count


def main():
    parser = argparse.ArgumentParser(
        description="重命名 TransDecoder GFF3 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python rename_transdecoder_gff3.py transdecoder.gff3
  python rename_transdecoder_gff3.py input.gff3 -o output.gff3
  python rename_transdecoder_gff3.py input.gff3 --old Hg --new Ug
        """
    )
    parser.add_argument("input", help="输入 GFF3 文件")
    parser.add_argument("-o", "--output", help="输出文件名")
    parser.add_argument("--old", default="Hg", help="旧前缀 (默认: Hg)")
    parser.add_argument("--new", default="Ug", help="新前缀 (默认: Ug)")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)

    if args.output:
        output = args.output
    else:
        base = os.path.splitext(args.input)[0]
        output = f"{base}_modified.gff3"

    print(f"输入文件: {args.input}")
    print(f"输出文件: {output}")
    print(f"替换: '{args.old}' → '{args.new}'")

    total, modified = rename_gff3(args.input, output, args.old, args.new)

    print(f"完成! 共 {total} 行，修改 {modified} 行")


if __name__ == "__main__":
    main()
