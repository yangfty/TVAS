#!/usr/bin/env python3
"""
重命名 Trinity 序列

将 Trinity.fasta 中的序列名转换为规范格式。
Trinity 默认命名: >TRINITY_DN12345_c0_g1_i1 len=xxx path=[...]
转换后: >Hvi_Ug000001

用法:
    python rename_trinity_seq.py input.fasta --prefix Hvi_Ug --output renamed.fasta
"""

import argparse
import os
import sys


def rename_trinity_sequences(input_fasta: str, output_fasta: str, prefix: str = "Gene"):
    """
    重命名 FASTA 中的 Trinity 序列

    保留序列ID中的TRINITY编号信息，统一格式为:
        >{prefix}{number:06d}

    同时保留原始序列ID作为注释:
        >{prefix}000001 original: TRINITY_DN12345_c0_g1_i1
    """
    count = 0

    os.makedirs(os.path.dirname(output_fasta) or ".", exist_ok=True)

    with open(input_fasta, "r", encoding="utf-8") as fin, \
         open(output_fasta, "w", encoding="utf-8") as fout:

        for line in fin:
            if line.startswith(">"):
                count += 1
                original_id = line[1:].strip().split()[0]  # 取第一段
                # 如果原始ID中有Hg，替换为Ug（保持兼容）
                new_id = f"{prefix}{count:06d}"
                fout.write(f">{new_id} original: {original_id}\n")
            else:
                fout.write(line)

    return count


def main():
    parser = argparse.ArgumentParser(
        description="重命名 Trinity 组装的序列",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python rename_trinity_seq.py Trinity.fasta
  python rename_trinity_seq.py Trinity.fasta --prefix Hvi_Uni
  python rename_trinity_seq.py input.fasta -o output.fasta --prefix Hvi_Ug
        """
    )
    parser.add_argument("input", help="输入 FASTA 文件")
    parser.add_argument("-o", "--output", help="输出文件名（默认: 输入文件_rename.fasta）")
    parser.add_argument("--prefix", default="Gene", help="序列名前缀 (默认: Gene)")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)

    if args.output:
        output = args.output
    else:
        base = os.path.splitext(args.input)[0]
        output = f"{base}_rename.fasta"

    print(f"输入文件: {args.input}")
    print(f"输出文件: {output}")
    print(f"序列前缀: {args.prefix}")

    count = rename_trinity_sequences(args.input, output, args.prefix)

    print(f"完成! 共重命名 {count} 条序列")


if __name__ == "__main__":
    main()
