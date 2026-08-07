"""
转录组de novo组装软件 - 流程编排器与后台工作线程

PipelineRunner: 按顺序执行分析步骤，管理上下文和状态
AnalysisWorker: QThread 后台线程，避免阻塞 GUI
"""

import os
import time
import traceback
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field

from PyQt5.QtCore import QThread, pyqtSignal

from .env_manager import CondaEnvManager
from .steps import PIPELINE_STEPS, StepStatus, StepResult, AnalysisContext


# ============================================================
# 流程编排器
# ============================================================

@dataclass
class PipelineState:
    """流程执行状态"""
    current_step_index: int = -1
    step_results: List[StepResult] = field(default_factory=list)
    is_running: bool = False
    is_cancelled: bool = False
    start_time: float = 0.0
    total_steps: int = 0
    # 选择要执行的步骤 (默认全部)
    active_step_ids: List[str] = field(default_factory=list)


class PipelineRunner:
    """
    流程编排器 - 按顺序执行所有分析步骤

    使用方式:
        runner = PipelineRunner(env_manager, context)
        runner.set_log_callback(my_log_func)
        runner.set_progress_callback(my_progress_func)
        results = runner.run_all()
    """

    def __init__(self, env: CondaEnvManager, ctx: AnalysisContext,
                 extra_params: Optional[dict] = None):
        self.env = env
        self.ctx = ctx
        self.extra_params = extra_params or {}
        self.state = PipelineState()
        self._log_callback: Optional[Callable] = None
        self._progress_callback: Optional[Callable] = None
        self._step_callback: Optional[Callable] = None

    def set_callbacks(self,
                      log: Optional[Callable] = None,
                      progress: Optional[Callable] = None,
                      on_step: Optional[Callable] = None):
        """设置回调函数"""
        self._log_callback = log
        self._progress_callback = progress
        self._step_callback = on_step

    def _log(self, msg: str):
        if self._log_callback:
            self._log_callback(msg)

    def _progress(self, pct: int):
        if self._progress_callback:
            self._progress_callback(pct)

    def _on_step_change(self, step_id: str, status: StepStatus):
        if self._step_callback:
            self._step_callback(step_id, status)

    def _get_step_kwargs(self, step_id: str) -> dict:
        """根据步骤ID从extra_params中提取对应的参数"""
        ep = self.extra_params
        mapping = {
            "fastp": {
                "quality_threshold": ep.get("fastp_quality", 20),
                "min_length": ep.get("fastp_min_length", 50),
            },
            "trinity": {
                "max_memory": ep.get("trinity_max_memory", "50G"),
            },
            "cd_hit": {
                "identity": ep.get("cd_hit_identity", 0.80),
            },
        }
        return mapping.get(step_id, {})

    def run_all(self) -> List[StepResult]:
        """执行所有选中的步骤"""
        self.state.is_running = True
        self.state.start_time = time.time()
        self.state.step_results = []

        # 确定要执行的步骤
        active_ids = self.state.active_step_ids
        steps_to_run = [
            s for s in PIPELINE_STEPS
            if not active_ids or s["id"] in active_ids
        ]
        self.state.total_steps = len(steps_to_run)

        self._log("=" * 60)
        self._log("  转录组 de novo 组装流程开始")
        self._log(f"  物种前缀: {self.ctx.species_prefix}")
        self._log(f"  工作目录: {self.ctx.work_dir}")
        self._log(f"  线程数: {self.ctx.threads}")
        self._log(f"  样本数: {len(self.ctx.samples)}")
        self._log(f"  执行步骤: {len(steps_to_run)} 个")
        self._log("=" * 60)

        for i, step_def in enumerate(steps_to_run):
            if self.state.is_cancelled:
                self._log("\n⚠ 流程已被用户取消")
                break

            step_id = step_def["id"]
            step_name = step_def["name"]
            step_fn = step_def["function"]

            self.state.current_step_index = i
            self._on_step_change(step_id, StepStatus.RUNNING)

            self._log(f"\n{'─' * 50}")
            self._log(f"  [{i+1}/{self.state.total_steps}] {step_name}")
            self._log(f"{'─' * 50}")

            # 进度回调：整体进度
            base_progress = int((i / self.state.total_steps) * 100)

            def step_progress(pct):
                overall = base_progress + int(pct / self.state.total_steps)
                self._progress(min(overall, 100))

            # 根据步骤ID构建额外参数
            step_kwargs = self._get_step_kwargs(step_id)

            try:
                start_t = time.time()
                result = step_fn(self.env, self.ctx, self._log, step_progress, **step_kwargs)

                if result is None:
                    result = StepResult(step_id, step_name)
                    result.status = StepStatus.SUCCESS
                    result.message = f"{step_name} 完成"

                result.duration_sec = time.time() - start_t
                self.state.step_results.append(result)

                if result.status == StepStatus.FAILED:
                    self._on_step_change(step_id, StepStatus.FAILED)
                    self._log(f"\n✗ {step_name} 失败，流程终止")
                    self._log(f"  错误: {result.message}")
                    break
                else:
                    self._on_step_change(step_id, StepStatus.SUCCESS)
                    elapsed = result.duration_sec
                    if elapsed > 60:
                        self._log(f"\n✓ {step_name} 完成 (耗时 {elapsed/60:.1f} 分钟)")
                    else:
                        self._log(f"\n✓ {step_name} 完成 (耗时 {elapsed:.1f} 秒)")

            except Exception as e:
                result = StepResult(step_id, step_name)
                result.status = StepStatus.FAILED
                result.message = f"{e}\n{traceback.format_exc()}"
                self.state.step_results.append(result)
                self._on_step_change(step_id, StepStatus.FAILED)
                self._log(f"\n✗ {step_name} 异常: {e}")
                self._log(traceback.format_exc())
                break

        self.state.is_running = False
        self._progress(100)

        total_elapsed = time.time() - self.state.start_time
        success_count = sum(
            1 for r in self.state.step_results
            if r.status == StepStatus.SUCCESS
        )
        self._log(f"\n{'=' * 60}")
        self._log(f"  流程结束: {success_count}/{self.state.total_steps} 步骤成功")
        self._log(f"  总耗时: {total_elapsed/60:.1f} 分钟")
        self._log(f"{'=' * 60}")

        # 输出最终结果文件
        if self.ctx.final_cds and os.path.exists(self.ctx.final_cds):
            self._log(f"\n🎉 最终输出文件:")
            self._log(f"  CDS:  {self.ctx.final_cds}")
        if self.ctx.final_pep and os.path.exists(self.ctx.final_pep):
            self._log(f"  PEP:  {self.ctx.final_pep}")

        return self.state.step_results

    def cancel(self):
        """取消运行"""
        self.state.is_cancelled = True
        self._log("\n⚠ 正在取消流程...")


# ============================================================
# 后台工作线程 (QThread)
# ============================================================

class AnalysisWorker(QThread):
    """
    后台分析线程 - 不阻塞 GUI

    信号:
        log_message(str): 日志消息
        progress_updated(int): 整体进度 0-100
        step_changed(str, str): 步骤变更 (step_id, status)
        finished_all(list): 全部完成 (StepResult列表)
        error_occurred(str): 发生错误
    """

    log_message = pyqtSignal(str)
    progress_updated = pyqtSignal(int)
    step_changed = pyqtSignal(str, str)  # step_id, status

    def __init__(self, env: CondaEnvManager, ctx: AnalysisContext,
                 extra_params: dict = None,
                 active_steps: List[str] = None,
                 parent=None):
        super().__init__(parent)
        self.env = env
        self.ctx = ctx
        self.extra_params = extra_params or {}
        self.active_steps = active_steps or []
        self._runner: Optional[PipelineRunner] = None

    def run(self):
        """线程主函数"""
        try:
            self._runner = PipelineRunner(self.env, self.ctx, self.extra_params)
            self._runner.state.active_step_ids = self.active_steps
            self._runner.set_callbacks(
                log=self._emit_log,
                progress=self._emit_progress,
                on_step=self._emit_step_change,
            )
            self._runner.run_all()
        except Exception as e:
            self.log_message.emit(f"严重错误: {e}\n{traceback.format_exc()}")

    def cancel(self):
        """取消执行"""
        if self._runner:
            self._runner.cancel()

    def _emit_log(self, msg: str):
        self.log_message.emit(msg)

    def _emit_progress(self, pct: int):
        self.progress_updated.emit(pct)

    def _emit_step_change(self, step_id: str, status: StepStatus):
        self.step_changed.emit(step_id, status.value)
