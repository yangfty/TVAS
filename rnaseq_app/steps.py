"""
转录组de novo组装软件 - 分析步骤定义模块

将原始SLURM脚本中的命令转换为独立的Python步骤函数。
每个步骤接收 env_manager + 参数，返回 (成功/失败, 输出信息)。
"""

import os
import sys
import glob
from typing import Tuple, List, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from .env_manager import CondaEnvManager


# ============================================================
# 资源路径工具 (兼容 PyInstaller 打包)
# ============================================================

def _resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径"""
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, relative_path)


# ============================================================
# 步骤状态与数据结构
# ============================================================

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """单步骤执行结果"""
    step_id: str
    name: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    duration_sec: float = 0.0
    output_files: List[str] = field(default_factory=list)


@dataclass
class SampleInfo:
    """单个样本信息"""
    group: str          # 条件/分组 (如 "P", "TX-CK")
    replicate: str      # 重复名 (如 "P_rep1")
    r1_path: str        # R1 FASTQ 文件路径
    r2_path: str        # R2 FASTQ 文件路径


# ============================================================
# 分析上下文（保存各步骤间的共享状态）
# ============================================================

@dataclass
class AnalysisContext:
    """分析上下文 - 保存各步骤的输入输出路径等共享信息"""
    work_dir: str = ""                  # 工作目录
    species_prefix: str = "Hvi"         # 物种前缀
    gene_prefix: str = "Uni"            # 基因前缀 (Ug)
    threads: int = 4                    # 默认线程数
    samples: List[SampleInfo] = field(default_factory=list)

    # 各步骤的输出文件/目录（在运行过程中填充）
    fastqc_dir: str = ""
    fastp_dir: str = ""
    rcorrector_dir: str = ""
    trinity_dir: str = ""
    trinity_fasta: str = ""                # Trinity.fasta
    longest_isoform_fasta: str = ""        # *_longest.fasta
    cd_hit_dir: str = ""
    cd_hit_output: str = ""                # *_longest_rd80.fasta
    renamed_fasta: str = ""                # *_reprn.fasta / *_repug.fasta
    transdecoder_orf_dir: str = ""
    transdecoder_predict_dir: str = ""
    transdecoder_pep: str = ""             # *.transdecoder.pep
    transdecoder_cds: str = ""             # *.transdecoder.cds
    transdecoder_gff3: str = ""            # *.transdecoder.gff3
    renamed_gff3: str = ""                 # *_repug_td.gff3
    gffread_dir: str = ""
    final_cds: str = ""
    final_pep: str = ""


# ============================================================
# 步骤函数
# ============================================================

# 每个步骤函数签名: (env: CondaEnvManager, ctx: AnalysisContext,
#                     log: Callable, set_progress: Callable) -> StepResult

def step_fastqc(env: CondaEnvManager, ctx: AnalysisContext,
                log: Callable, progress: Callable) -> StepResult:
    """步骤1: FastQC 质量评估"""
    result = StepResult("fastqc", "FastQC 质量评估")

    if not ctx.samples:
        result.status = StepStatus.SKIPPED
        result.message = "没有配置样本"
        return result

    out_dir = os.path.join(ctx.work_dir, "01_fastqc_out")
    os.makedirs(out_dir, exist_ok=True)
    ctx.fastqc_dir = out_dir

    result.status = StepStatus.RUNNING
    log("▶ FastQC 质量评估开始...")

    total = len(ctx.samples)
    for i, sample in enumerate(ctx.samples):
        progress(int((i / total) * 100))
        log(f"  [{i+1}/{total}] {sample.replicate} ...")

        # 检查文件是否存在
        if not os.path.exists(sample.r1_path):
            log(f"    ⚠ R1文件不存在: {sample.r1_path}")
            continue
        if not os.path.exists(sample.r2_path):
            log(f"    ⚠ R2文件不存在: {sample.r2_path}")
            continue

        cmd = f"fastqc {sample.r1_path} {sample.r2_path} -o {out_dir} -t {ctx.threads}"
        ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=600)
        if ok:
            log(f"    ✓ {sample.replicate} 完成")
        else:
            log(f"    ✗ {sample.replicate} 失败: {output[-200:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"FastQC 完成，输出目录: {out_dir}"
    return result


def step_fastp(env: CondaEnvManager, ctx: AnalysisContext,
               log: Callable, progress: Callable,
               quality_threshold: int = 20,
               min_length: int = 50) -> StepResult:
    """步骤2: Fastp 过滤"""
    result = StepResult("fastp", "Fastp 数据过滤")

    if not ctx.samples:
        result.status = StepStatus.SKIPPED
        result.message = "没有配置样本"
        return result

    out_dir = os.path.join(ctx.work_dir, "02_fastp_clean")
    os.makedirs(out_dir, exist_ok=True)
    ctx.fastp_dir = out_dir

    result.status = StepStatus.RUNNING
    log("▶ Fastp 数据过滤开始...")
    log(f"  参数: -q {quality_threshold} -l {min_length} --detect_adapter_for_pe")

    total = len(ctx.samples)
    for i, sample in enumerate(ctx.samples):
        progress(int((i / total) * 100))
        log(f"  [{i+1}/{total}] {sample.replicate} ...")

        out_r1 = os.path.join(out_dir, f"{sample.replicate}_R1_clean.fq.gz")
        out_r2 = os.path.join(out_dir, f"{sample.replicate}_R2_clean.fq.gz")
        html = os.path.join(out_dir, f"{sample.replicate}_fastp.html")
        json_rpt = os.path.join(out_dir, f"{sample.replicate}_fastp.json")

        cmd = (
            f"fastp -i {sample.r1_path} -I {sample.r2_path} "
            f"-o {out_r1} -O {out_r2} "
            f"--detect_adapter_for_pe "
            f"-q {quality_threshold} -l {min_length} "
            f"-w {ctx.threads} "
            f"--html {html} --json {json_rpt}"
        )
        ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=1200)
        if ok:
            log(f"    ✓ {sample.replicate} 过滤完成")
        else:
            log(f"    ✗ {sample.replicate} 失败: {output[-200:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"Fastp 过滤完成，输出目录: {out_dir}"
    return result


def step_rcorrector(env: CondaEnvManager, ctx: AnalysisContext,
                    log: Callable, progress: Callable) -> StepResult:
    """步骤3: Rcorrector 纠错"""
    result = StepResult("rcorrector", "Rcorrector 纠错")

    fastp_dir = ctx.fastp_dir or os.path.join(ctx.work_dir, "02_fastp_clean")
    if not os.path.isdir(fastp_dir):
        result.status = StepStatus.SKIPPED
        result.message = f"Fastp 输出目录不存在: {fastp_dir}，请先运行 Fastp"
        return result

    out_dir = os.path.join(ctx.work_dir, "03_rcorrector")
    os.makedirs(out_dir, exist_ok=True)
    ctx.rcorrector_dir = out_dir

    result.status = StepStatus.RUNNING
    log("▶ Rcorrector 纠错开始...")

    # 获取 rcorrector 的 perl 脚本路径
    env_path = env.get_env_path()
    rcorrector_pl = ""
    if env_path:
        candidates = [
            os.path.join(env_path, "bin", "run_rcorrector.pl"),
            os.path.join(env_path, "share", "rcorrector", "run_rcorrector.pl"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                rcorrector_pl = c
                break

    if not rcorrector_pl:
        # 尝试通过 which 查找
        ok, which_out = env.run_in_env("which run_rcorrector.pl")
        if ok:
            rcorrector_pl = which_out.strip()
        else:
            # fallback: 直接在 conda env 的 bin 目录
            rcorrector_pl = "$CONDA_PREFIX/bin/run_rcorrector.pl"

    total = len(ctx.samples)
    for i, sample in enumerate(ctx.samples):
        progress(int((i / total) * 100))
        log(f"  [{i+1}/{total}] {sample.replicate} ...")

        r1_clean = os.path.join(fastp_dir, f"{sample.replicate}_R1_clean.fq.gz")
        r2_clean = os.path.join(fastp_dir, f"{sample.replicate}_R2_clean.fq.gz")

        if not os.path.exists(r1_clean) or not os.path.exists(r2_clean):
            log(f"    ⚠ 找不到过滤后的文件: {r1_clean}")
            continue

        cmd = (
            f"perl {rcorrector_pl} "
            f"-1 {r1_clean} -2 {r2_clean} "
            f"-t {ctx.threads} "
            f"-od {out_dir}"
        )
        ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=1800)
        if ok:
            log(f"    ✓ {sample.replicate} 纠错完成")
        else:
            log(f"    ✗ {sample.replicate} 失败: {output[-200:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"Rcorrector 纠错完成，输出目录: {out_dir}"
    return result


def step_trinity_assemble(env: CondaEnvManager, ctx: AnalysisContext,
                          log: Callable, progress: Callable,
                          max_memory: str = "50G") -> StepResult:
    """步骤4: Trinity 组装"""
    result = StepResult("trinity", "Trinity 组装")

    rcorrector_dir = ctx.rcorrector_dir or os.path.join(ctx.work_dir, "03_rcorrector")
    out_dir = os.path.join(ctx.work_dir, "04_trinity_out")
    os.makedirs(out_dir, exist_ok=True)
    ctx.trinity_dir = out_dir

    # 生成 samples_file (Trinity 要求的格式)
    samples_file = os.path.join(ctx.work_dir, "trinity_samples.txt")
    with open(samples_file, "w", encoding="utf-8") as f:
        for s in ctx.samples:
            r1_cor = os.path.join(rcorrector_dir, f"{s.replicate}_R1_clean.cor.fq.gz")
            r2_cor = os.path.join(rcorrector_dir, f"{s.replicate}_R2_clean.cor.fq.gz")
            f.write(f"{s.group}\t{s.replicate}\t{r1_cor}\t{r2_cor}\n")

    result.status = StepStatus.RUNNING
    log(f"▶ Trinity 组装开始 (max_memory={max_memory}, CPU={ctx.threads})...")
    log(f"  样本文件: {samples_file}")
    log("  ⚠ Trinity 组装可能需要数小时甚至数天，请耐心等待...")

    cmd = (
        f"Trinity --seqType fq --samples_file {samples_file} "
        f"--max_memory {max_memory} --CPU {ctx.threads} "
        f"--output {out_dir}"
    )
    ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=86400 * 3)  # 最多3天

    if ok:
        # 查找 Trinity.fasta
        trinity_fa = os.path.join(out_dir, "Trinity.fasta")
        if not os.path.isfile(trinity_fa):
            trinity_fa = os.path.join(out_dir, "Trinity.fasta.gz")

        if os.path.isfile(trinity_fa):
            ctx.trinity_fasta = trinity_fa
            log("✓ Trinity 组装完成")
        else:
            log("⚠ Trinity 似乎完成但未找到 Trinity.fasta，请检查输出目录")
    else:
        log(f"✗ Trinity 组装失败:\n{output[-500:]}")
        result.status = StepStatus.FAILED
        result.message = "Trinity 组装失败"
        return result

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"Trinity 组装完成，输出: {ctx.trinity_fasta}"
    result.output_files = [ctx.trinity_fasta]
    return result


def step_longest_isoform(env: CondaEnvManager, ctx: AnalysisContext,
                         log: Callable, progress: Callable) -> StepResult:
    """步骤5: 获取每个Trinity基因的最长isoform"""
    result = StepResult("longest_isoform", "提取最长Isoform")

    trinity_fa = ctx.trinity_fasta
    if not trinity_fa or not os.path.isfile(trinity_fa):
        result.status = StepStatus.SKIPPED
        result.message = "Trinity.fasta 不存在，请先运行 Trinity 组装"
        return result

    out_dir = os.path.join(ctx.work_dir, "05_longest_isoform")
    os.makedirs(out_dir, exist_ok=True)

    output_fa = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_longest.fasta")
    ctx.longest_isoform_fasta = output_fa

    # 查找 get_longest_isoform_seq_per_trinity_gene.pl
    env_path = env.get_env_path()
    script_path = ""
    if env_path:
        script_path = os.path.join(
            env_path, "opt", "trinity-2.8.5", "util", "misc",
            "get_longest_isoform_seq_per_trinity_gene.pl"
        )
        if not os.path.isfile(script_path):
            # 尝试搜索
            import glob as g
            candidates = g.glob(
                os.path.join(env_path, "opt", "trinity-*", "util", "misc",
                             "get_longest_isoform_seq_per_trinity_gene.pl")
            )
            script_path = candidates[0] if candidates else ""

    if not script_path or not os.path.isfile(script_path):
        result.status = StepStatus.FAILED
        result.message = "找不到 get_longest_isoform_seq_per_trinity_gene.pl"
        return result

    result.status = StepStatus.RUNNING
    log("▶ 提取最长 isoform...")

    cmd = f"perl {script_path} {trinity_fa} > {output_fa}"
    ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=7200)

    if ok and os.path.isfile(output_fa):
        # 统计序列数
        count_ok, count_out = env.run_in_env(
            f"grep -c '>' {output_fa}", timeout=30
        )
        seq_count = count_out.strip() if count_ok else "?"
        log(f"✓ 提取完成，共 {seq_count} 条序列")
    else:
        log(f"✗ 提取失败: {output[-300:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"提取最长isoform完成: {output_fa}"
    result.output_files = [output_fa]
    return result


def step_cd_hit(env: CondaEnvManager, ctx: AnalysisContext,
                log: Callable, progress: Callable,
                identity: float = 0.80) -> StepResult:
    """步骤6: CD-HIT 去冗余"""
    result = StepResult("cd_hit", "CD-HIT 去冗余")

    input_fa = ctx.longest_isoform_fasta
    if not input_fa or not os.path.isfile(input_fa):
        result.status = StepStatus.SKIPPED
        result.message = "最长isoform文件不存在，请先运行提取最长isoform步骤"
        return result

    out_dir = os.path.join(ctx.work_dir, "06_cd_hit_out")
    os.makedirs(out_dir, exist_ok=True)
    ctx.cd_hit_dir = out_dir

    # 根据 identity 确定 word_size
    if identity >= 0.95:
        word_size = 10
    elif identity >= 0.90:
        word_size = 8
    elif identity >= 0.88:
        word_size = 7
    elif identity >= 0.85:
        word_size = 6
    elif identity >= 0.80:
        word_size = 5
    elif identity >= 0.75:
        word_size = 4
    else:
        word_size = 5

    id_str = str(int(identity * 100))
    output_fa = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_longest_rd{id_str}.fasta")
    ctx.cd_hit_output = output_fa

    result.status = StepStatus.RUNNING
    log(f"▶ CD-HIT 去冗余 (identity={identity:.0%}, word_size={word_size})...")

    cmd = (
        f"cd-hit-est -i {input_fa} -o {output_fa} "
        f"-c {identity} -n {word_size} -G 1 -g 1 "
        f"-T {ctx.threads} -M 100000"
    )
    ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=86400)

    if ok and os.path.isfile(output_fa):
        count_ok, count_out = env.run_in_env(f"grep -c '>' {output_fa}", timeout=30)
        seq_count = count_out.strip() if count_ok else "?"
        log(f"✓ CD-HIT 完成，共 {seq_count} 条序列 (去冗余后)")
    else:
        log(f"✗ CD-HIT 失败: {output[-300:]}")
        result.status = StepStatus.FAILED
        result.message = "CD-HIT 去冗余失败"
        return result

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"CD-HIT 完成: {output_fa}"
    result.output_files = [output_fa]
    return result


def step_rename_sequences(env: CondaEnvManager, ctx: AnalysisContext,
                          log: Callable, progress: Callable) -> StepResult:
    """步骤7: 重命名序列 + DOS转Unix"""
    result = StepResult("rename", "重命名序列")

    input_fa = ctx.cd_hit_output
    if not input_fa or not os.path.isfile(input_fa):
        result.status = StepStatus.SKIPPED
        result.message = "CD-HIT 输出文件不存在，请先运行 CD-HIT"
        return result

    out_dir = os.path.join(ctx.work_dir, "07_renamed")
    os.makedirs(out_dir, exist_ok=True)

    # 重命名后的文件
    renamed_fa = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_reprn.fasta")
    final_fa = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_repug.fasta")
    ctx.renamed_fasta = final_fa

    result.status = StepStatus.RUNNING
    log("▶ 重命名序列...")

    # 获取脚本路径
    rename_script = _resource_path("scripts/rename_trinity_seq.py")

    if not os.path.isfile(rename_script):
        log("⚠ 未找到 rename_trinity_seq.py，使用内联重命名...")
        # 内联实现：读取fasta，重命名序列，写出
        seq_count = 0
        with open(input_fa, "r") as fin, open(renamed_fa, "w") as fout:
            for line in fin:
                if line.startswith(">"):
                    seq_count += 1
                    fout.write(f">{ctx.species_prefix}_{ctx.gene_prefix}{seq_count:06d}\n")
                else:
                    fout.write(line)
        log(f"✓ 重命名完成，共 {seq_count} 条序列")
    else:
        cmd = f"python {rename_script} {input_fa} --prefix {ctx.species_prefix}_{ctx.gene_prefix}"
        ok, output = env.run_in_env(cmd, cwd=out_dir, timeout=600)
        log(output)

    # DOS → Unix 转换
    log("  转换文件格式 (DOS → Unix)...")
    try:
        with open(renamed_fa, "rb") as f:
            content = f.read()
        unix_content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        with open(final_fa, "wb") as f:
            f.write(unix_content)
        log(f"✓ 格式转换完成 → {final_fa}")
    except Exception as e:
        log(f"  ⚠ 格式转换失败: {e}")
        # 直接复制
        import shutil
        shutil.copy(renamed_fa, final_fa)

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"序列重命名完成: {final_fa}"
    result.output_files = [final_fa]
    return result


def step_transdecoder_longorfs(env: CondaEnvManager, ctx: AnalysisContext,
                               log: Callable, progress: Callable) -> StepResult:
    """步骤8: TransDecoder LongOrfs - 预测长开放阅读框"""
    result = StepResult("transdecoder_longorfs", "TransDecoder LongOrfs")

    input_fa = ctx.renamed_fasta
    if not input_fa or not os.path.isfile(input_fa):
        result.status = StepStatus.SKIPPED
        result.message = "重命名后的 fasta 不存在，请先运行重命名步骤"
        return result

    out_dir = os.path.join(ctx.work_dir, "08_transdecoder_orf")
    os.makedirs(out_dir, exist_ok=True)
    ctx.transdecoder_orf_dir = out_dir

    result.status = StepStatus.RUNNING
    log("▶ TransDecoder LongOrfs - 预测长开放阅读框...")

    cmd = f"TransDecoder.LongOrfs -t {input_fa} --output_dir {out_dir}"
    ok, output = env.run_in_env(cmd, cwd=ctx.work_dir, timeout=86400)

    # 检查输出
    if ok:
        expected = os.path.join(out_dir, "longest_orfs.pep")
        if os.path.isfile(expected):
            log(f"✓ TransDecoder LongOrfs 完成")
            log(f"  输出目录: {out_dir}")
            log(f"  文件: longest_orfs.cds, longest_orfs.pep, longest_orfs.gff3")
        else:
            log("⚠ TransDecoder LongOrfs 完成但未找到预期输出文件")
    else:
        log(f"✗ TransDecoder LongOrfs 失败:\n{output[-300:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"TransDecoder LongOrfs 完成: {out_dir}"
    return result


def step_transdecoder_predict(env: CondaEnvManager, ctx: AnalysisContext,
                              log: Callable, progress: Callable) -> StepResult:
    """步骤9: TransDecoder Predict - 预测CDS"""
    result = StepResult("transdecoder_predict", "TransDecoder Predict")

    input_fa = ctx.renamed_fasta
    if not input_fa or not os.path.isfile(input_fa):
        result.status = StepStatus.SKIPPED
        result.message = "重命名后的 fasta 不存在"
        return result

    # Predict 使用与 LongOrfs 相同的 output_dir (包含 LongOrfs 结果)
    prev_out = ctx.transdecoder_orf_dir or os.path.join(ctx.work_dir, "08_transdecoder_orf")
    predict_dir = os.path.join(ctx.work_dir, "09_transdecoder_predict")
    os.makedirs(predict_dir, exist_ok=True)
    ctx.transdecoder_predict_dir = predict_dir

    result.status = StepStatus.RUNNING
    log("▶ TransDecoder Predict - 预测最终CDS...")

    # 把输入fasta复制到 predict 目录，并在那里运行
    import shutil
    local_fa = os.path.join(predict_dir, os.path.basename(input_fa))
    if not os.path.isfile(local_fa):
        shutil.copy(input_fa, local_fa)

    cmd = f"TransDecoder.Predict -t {local_fa} --output_dir {predict_dir}"
    ok, output = env.run_in_env(cmd, cwd=predict_dir, timeout=86400)

    if ok:
        # 记录输出文件
        base = os.path.splitext(os.path.basename(input_fa))[0]
        ctx.transdecoder_pep = os.path.join(predict_dir, f"{base}.fasta.transdecoder.pep")
        ctx.transdecoder_cds = os.path.join(predict_dir, f"{base}.fasta.transdecoder.cds")
        ctx.transdecoder_gff3 = os.path.join(predict_dir, f"{base}.fasta.transdecoder.gff3")
        log(f"✓ TransDecoder Predict 完成")
        log(f"  PEP: {ctx.transdecoder_pep}")
        log(f"  CDS: {ctx.transdecoder_cds}")
        log(f"  GFF3: {ctx.transdecoder_gff3}")
    else:
        log(f"✗ TransDecoder Predict 失败:\n{output[-300:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"TransDecoder Predict 完成: {predict_dir}"
    return result


def step_rename_gff3(env: CondaEnvManager, ctx: AnalysisContext,
                     log: Callable, progress: Callable) -> StepResult:
    """步骤10: 重命名 GFF3 文件中的基因名"""
    result = StepResult("rename_gff3", "重命名 GFF3")

    input_gff3 = ctx.transdecoder_gff3
    if not input_gff3 or not os.path.isfile(input_gff3):
        result.status = StepStatus.SKIPPED
        result.message = "TransDecoder GFF3 文件不存在"
        return result

    out_dir = os.path.join(ctx.work_dir, "09_transdecoder_predict")
    output_gff3 = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_repug_td.gff3")
    ctx.renamed_gff3 = output_gff3

    result.status = StepStatus.RUNNING
    log("▶ 重命名 GFF3 文件...")

    # 查找重命名脚本
    rename_script = _resource_path("scripts/rename_transdecoder_gff3.py")

    if os.path.isfile(rename_script):
        cmd = f"python {rename_script} {input_gff3} --output {output_gff3}"
        ok, output = env.run_in_env(cmd, cwd=out_dir, timeout=300)
        log(output)
    else:
        # 内联实现：替换 GFF3 中的 Hg 前缀为 Ug
        log("  使用内联重命名 (Hg → Ug)...")
        try:
            with open(input_gff3, "r") as fin, open(output_gff3, "w") as fout:
                for line in fin:
                    fout.write(line.replace("Hg", ctx.gene_prefix))
            log(f"✓ GFF3 重命名完成 → {output_gff3}")
        except Exception as e:
            log(f"  ✗ 失败: {e}")
            result.status = StepStatus.FAILED
            return result

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"GFF3 重命名完成: {output_gff3}"
    result.output_files = [output_gff3]
    return result


def step_gffread(env: CondaEnvManager, ctx: AnalysisContext,
                 log: Callable, progress: Callable) -> StepResult:
    """步骤11: Gffread 提取 CDS 和 Protein 序列"""
    result = StepResult("gffread", "Gffread 提取 CDS/Protein")

    gff3 = ctx.renamed_gff3
    genome_fa = ctx.renamed_fasta

    if not gff3 or not os.path.isfile(gff3):
        result.status = StepStatus.SKIPPED
        result.message = "重命名后的 GFF3 文件不存在"
        return result
    if not genome_fa or not os.path.isfile(genome_fa):
        result.status = StepStatus.SKIPPED
        result.message = "参考 fasta 文件不存在"
        return result

    out_dir = os.path.join(ctx.work_dir, "10_gffread_out")
    os.makedirs(out_dir, exist_ok=True)
    ctx.gffread_dir = out_dir

    cds_out = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_repug_cds.fasta")
    pep_out = os.path.join(out_dir, f"{ctx.species_prefix}_trinity_repug_pep.fasta")
    ctx.final_cds = cds_out
    ctx.final_pep = pep_out

    result.status = StepStatus.RUNNING
    log("▶ Gffread 提取 CDS 和 Protein 序列...")

    # 提取 CDS
    cmd_cds = f"gffread {gff3} -g {genome_fa} -x {cds_out}"
    ok, output = env.run_in_env(cmd_cds, cwd=ctx.work_dir, timeout=3600)
    if ok:
        log(f"✓ CDS 提取完成 → {cds_out}")
    else:
        log(f"✗ CDS 提取失败: {output[-200:]}")

    # 提取 Protein
    cmd_pep = f"gffread {gff3} -g {genome_fa} -y {pep_out}"
    ok, output = env.run_in_env(cmd_pep, cwd=ctx.work_dir, timeout=3600)
    if ok:
        log(f"✓ Protein 提取完成 → {pep_out}")
    else:
        log(f"✗ Protein 提取失败: {output[-200:]}")

    progress(100)
    result.status = StepStatus.SUCCESS
    result.message = f"Gffread 完成\n  CDS: {cds_out}\n  PEP: {pep_out}"
    result.output_files = [cds_out, pep_out]
    return result


# ============================================================
# 步骤注册表
# ============================================================

# 定义完整流程（按顺序）
PIPELINE_STEPS: List[dict] = [
    {
        "id": "fastqc",
        "name": "FastQC 质量评估",
        "description": "对原始测序数据进行质量评估",
        "function": step_fastqc,
        "required": True,
    },
    {
        "id": "fastp",
        "name": "Fastp 数据过滤",
        "description": "过滤低质量 reads，去除接头序列",
        "function": step_fastp,
        "required": True,
    },
    {
        "id": "rcorrector",
        "name": "Rcorrector 纠错",
        "description": "对 RNA-seq reads 进行错误纠正",
        "function": step_rcorrector,
        "required": True,
    },
    {
        "id": "trinity",
        "name": "Trinity 组装",
        "description": "将 reads 组装成转录本（耗时较长）",
        "function": step_trinity_assemble,
        "required": True,
    },
    {
        "id": "longest_isoform",
        "name": "提取最长 Isoform",
        "description": "对每个 Trinity 基因保留最长 isoform",
        "function": step_longest_isoform,
        "required": True,
    },
    {
        "id": "cd_hit",
        "name": "CD-HIT 去冗余",
        "description": "聚类去除冗余序列（默认 80% 相似度）",
        "function": step_cd_hit,
        "required": True,
    },
    {
        "id": "rename",
        "name": "重命名序列",
        "description": "将序列重命名为规范格式并转换换行符",
        "function": step_rename_sequences,
        "required": True,
    },
    {
        "id": "transdecoder_longorfs",
        "name": "TransDecoder LongOrfs",
        "description": "识别长的开放阅读框 (ORF)",
        "function": step_transdecoder_longorfs,
        "required": True,
    },
    {
        "id": "transdecoder_predict",
        "name": "TransDecoder Predict",
        "description": "最终预测编码序列 (CDS)",
        "function": step_transdecoder_predict,
        "required": True,
    },
    {
        "id": "rename_gff3",
        "name": "重命名 GFF3",
        "description": "统一 GFF3 注释文件中的基因命名",
        "function": step_rename_gff3,
        "required": True,
    },
    {
        "id": "gffread",
        "name": "Gffread 提取序列",
        "description": "从 GFF3 + 基因组提取最终的 CDS/Protein",
        "function": step_gffread,
        "required": True,
    },
]
