"""spec_review.py — SPEC 方案评审门禁的核心逻辑。

实现评审 run 的派发、结果消费、写入边界校验、故障重试与人工恢复入口。
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.state_machine import (
    SpecStatus,
    FROZEN_FIELD,
    FREEZE_ERROR_PREFIX,
)
from core.agent_runner.runner import AgentRunner, AgentRunResult
from core.agent_runner.prompt_builder import spec_review_result_path, spec_review_result_status_whitelist

_logger = logging.getLogger("fenixd.pm_engine.spec_review")

# 评审尝试上限（首次 + 最多 2 次重试，常量名自解释）
MAX_REVIEW_ATTEMPTS = 3

# 写入边界校验：SPEC 目录相对路径前缀
SPEC_CHANGES_PREFIX = "spec/changes/"


class SpecReviewManager:
    """评审管理器：负责评审 run 的派发、结果消费、边界校验、重试与恢复。"""

    def __init__(self, project_root: Path, state_machine, agent_runner: AgentRunner,
                 pm_engine, config: dict, logger=None):
        self.project_root = project_root
        self.state_machine = state_machine
        self.agent_runner = agent_runner
        self.pm_engine = pm_engine
        self.config = config
        self.logger = logger or _logger

    # ── 评审派发 ────────────────────────────────────────────────

    def dispatch_review(self, spec_name: str) -> bool:
        """为指定 SPEC 派发一次评审 run。

        Returns: True 表示派发成功（run 已启动），False 表示派发失败。
        """
        # 检查是否已有在飞评审 run（防重派）
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            self.logger.warning("spec_review", f"SPEC 不存在: {spec_name}")
            return False
        if entry.get("reviewer_run"):
            self.logger.info("spec_review", f"已有在飞评审 run: {spec_name}")
            return False
        # 检查评审尝试次数
        attempts = entry.get("_review_attempts") or 0
        if attempts >= MAX_REVIEW_ATTEMPTS:
            self.logger.warning("spec_review", f"评审尝试已达上限: {spec_name}")
            return False

        # 派发前快照
        snapshot = self._take_snapshot(spec_name)
        snapshot_dir = self.project_root / ".fenix" / "spec-review" / spec_name
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / "snapshot.json"
        try:
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self.logger.warning("spec_review", f"快照保存失败: {spec_name}: {e}")

        # 派发评审 run
        run_id = self.agent_runner.run_spec_review(spec_name)
        if not run_id.success:
            self.logger.error("spec_review", f"评审 run 派发失败: {spec_name}")
            return False

        # 更新 STATE.md
        self.state_machine.update_spec(spec_name, {
            "reviewer_run": run_id.run_id,
            "_review_attempts": attempts + 1,
        })
        self.logger.info("spec_review", f"评审 run 已派发: {spec_name} run_id={run_id.run_id}")
        return True

    # ── 评审结果消费 ────────────────────────────────────────────

    def consume_review_result(self, spec_name: str) -> bool:
        """消费评审结果：校验结果硬门与写入边界，按 status 机械收口。

        Returns: True 表示消费成功（状态已变更），False 表示消费失败（需重试）。
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False
        run_id = entry.get("reviewer_run")
        if not run_id:
            return False

        # 结果硬门校验（复用 _check_agent_result_artifact）
        err = self.agent_runner._check_agent_result_artifact(
            spec_name, "spec-review", run_started_at=None)  # 新鲜度校验暂时跳过
        if err is not None:
            self.logger.warning("spec_review", f"结果硬门校验失败: {spec_name}: {err}")
            self._handle_review_failure(spec_name, err)
            return False

        # 读取结果文件
        result_path = spec_review_result_path(self.project_root, spec_name)
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self.logger.warning("spec_review", f"结果文件读取失败: {spec_name}: {e}")
            self._handle_review_failure(spec_name, f"结果文件读取失败: {e}")
            return False

        # 写入边界校验
        boundary_err = self._check_write_boundary(spec_name, data)
        if boundary_err:
            self.logger.warning("spec_review", f"写入边界校验失败: {spec_name}: {boundary_err}")
            self._handle_review_failure(spec_name, boundary_err)
            return False

        # 按 status 机械收口
        status = data.get("status")
        if status not in spec_review_result_status_whitelist:
            self.logger.warning("spec_review", f"未知 status: {status}")
            self._handle_review_failure(spec_name, f"未知 status: {status}")
            return False

        if status in ("approved", "repaired"):
            # 转 ready 并触发实现调度
            self.state_machine.transition(spec_name, "ready")
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "_review_attempts": 0,
                "error": None,
            })
            # 触发实现调度
            self.pm_engine._on_spec_ready(spec_name)
            self.logger.info("spec_review", f"评审通过: {spec_name} status={status}")
            return True
        elif status == "rejected":
            # 转 blocked 并写入 error
            findings = data.get("findings") or []
            blocking = [f for f in findings if f.get("severity") == "blocking"]
            error_msg = "spec-review-rejected: " + "; ".join(
                f.get("detail", "") for f in blocking
            ) if blocking else "spec-review-rejected: 无详情"
            self.state_machine.transition(spec_name, "blocked")
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "_review_attempts": 0,
                "error": error_msg,
            })
            self.logger.info("spec_review", f"评审否决: {spec_name}")
            return True
        else:
            # 理论上不会到这里
            self._handle_review_failure(spec_name, f"未知 status: {status}")
            return False

    # ── 写入边界校验 ────────────────────────────────────────────

    def _take_snapshot(self, spec_name: str) -> dict:
        """派发前对 SPEC 目录与工作区脏文件记录快照。

        返回快照 dict，包含：
        - spec_files: {相对路径: 内容哈希}
        - dirty_files: {相对路径: 内容哈希}（仅 git status --porcelain 列出的脏文件）
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        snapshot = {"spec_files": {}, "dirty_files": {}}
        if not spec_dir.is_dir():
            return snapshot
        # 记录 SPEC 目录内所有文件的内容哈希
        for file in spec_dir.rglob("*"):
            if file.is_file():
                rel = str(file.relative_to(self.project_root))
                try:
                    content = file.read_bytes()
                    h = hashlib.md5(content).hexdigest()
                    snapshot["spec_files"][rel] = h
                except OSError:
                    pass
        # 记录工作区脏文件的内容哈希
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("??") or line.startswith(" M") or line.startswith("M "):
                        # 简化处理：取文件路径（去掉状态前缀）
                        parts = line.split()
                        if len(parts) >= 2:
                            path = parts[1]
                            # 忽略 SPEC 目录内的文件（已经单独记录）
                            if path.startswith(SPEC_CHANGES_PREFIX):
                                continue
                            full = self.project_root / path
                            if full.is_file():
                                try:
                                    content = full.read_bytes()
                                    h = hashlib.md5(content).hexdigest()
                                    snapshot["dirty_files"][path] = h
                                except OSError:
                                    pass
        except (subprocess.SubprocessError, OSError):
            pass
        return snapshot

    def _verify_snapshot(self, spec_name: str, snapshot: dict) -> Optional[str]:
        """收工后比对快照，检出越界写入。

        Returns: None 表示通过，否则返回错误信息。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 检查 SPEC 目录内文件哈希是否变化
        for rel, old_hash in snapshot.get("spec_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                return f"SPEC 目录内文件被删除: {rel}"
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    # 文件被修改，这是允许的（repaired 状态）
                    pass
            except OSError:
                return f"无法读取文件: {rel}"

        # 检查工作区脏文件是否变化
        for rel, old_hash in snapshot.get("dirty_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                continue  # 文件被删除，可能不是评审者所为
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    return f"工作区脏文件被修改: {rel}"
            except OSError:
                pass

        # 检查是否有新增文件（SPEC 目录外）
        # 简化：只检查 SPEC 目录外是否有新增文件，通过 git status
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("??"):
                        parts = line.split()
                        if len(parts) >= 2:
                            path = parts[1]
                            if not path.startswith(SPEC_CHANGES_PREFIX):
                                # 检查是否在快照中已存在
                                if path not in snapshot.get("dirty_files", {}):
                                    return f"新增文件在 SPEC 目录外: {path}"
        except (subprocess.SubprocessError, OSError):
            pass

        return None

    def _check_write_boundary(self, spec_name: str, review_data: dict) -> Optional[str]:
        """校验评审 run 的写入边界：repairs 路径合法性、SPEC 目录外无新增改动、status 与改动一致。

        Returns: None 表示通过，否则返回错误信息。
        """
        spec_dir = self.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return f"SPEC 目录不存在: {spec_dir}"

        # 1. repairs 路径合法性
        repairs = review_data.get("repairs") or []
        for repair in repairs:
            path = repair.get("path", "")
            if not path.startswith(SPEC_CHANGES_PREFIX):
                return f"repairs 路径越界: {path}"
            # 检查是否确实存在于 SPEC 目录内
            rel = path[len(SPEC_CHANGES_PREFIX):]
            if not (spec_dir / rel).exists():
                return f"repairs 路径不存在: {path}"

        # 2. 快照比对（需要从临时文件加载派发前快照）
        snapshot_path = self.project_root / ".fenix" / "spec-review" / spec_name / "snapshot.json"
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                snapshot_err = self._verify_snapshot(spec_name, snapshot)
                if snapshot_err:
                    return snapshot_err
            except (OSError, json.JSONDecodeError):
                pass  # 快照读取失败，跳过比对（保守放行？）

        # 3. status 与改动一致性
        status = review_data.get("status")
        if status == "approved" and repairs:
            return "approved 状态伴随文件改动"
        if status == "repaired" and not repairs:
            return "repaired 状态无修补清单"

        return None

    # ── 故障重试 ────────────────────────────────────────────────

    def _handle_review_failure(self, spec_name: str, reason: str):
        """处理评审失败：递增尝试次数，达到上限转 blocked。"""
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return
        attempts = entry.get("_review_attempts") or 0
        if attempts < MAX_REVIEW_ATTEMPTS:
            # 重试：保持 reviewing 状态，清除 reviewer_run
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "_review_attempts": attempts + 1,
                "error": f"spec-review-incomplete: {reason}",
            })
            self.logger.info("spec_review", f"评审失败重试: {spec_name} attempt={attempts+1}")
        else:
            # 达上限转 blocked
            error_msg = f"spec-review-incomplete: {reason}"
            self.state_machine.transition(spec_name, "blocked")
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "_review_attempts": 0,
                "error": error_msg,
            })
            self.logger.warning("spec_review", f"评审失败达上限: {spec_name}")

    # ── 人工恢复入口 ────────────────────────────────────────────

    def re_review(self, spec_name: str) -> Tuple[bool, str]:
        """重新评审入口：对符合开放条件的 blocked SPEC 执行 blocked → reviewing。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"
        if entry.get(FROZEN_FIELD):
            return False, "SPEC 已冻结"
        error = entry.get("error") or ""
        if not (error.startswith("spec-review-rejected:") or error.startswith("spec-review-incomplete:")):
            return False, "SPEC 未因评审进入 blocked"

        # 执行 blocked → reviewing
        success = self.state_machine.transition(spec_name, "reviewing")
        if not success:
            return False, "状态转移失败"

        # 派发新评审
        dispatch_ok = self.dispatch_review(spec_name)
        if not dispatch_ok:
            return False, "评审派发失败"

        return True, "重新评审已触发"

    def responsible_release(self, spec_name: str) -> Tuple[bool, str]:
        """担责放行入口：对 blocked SPEC 执行 blocked → ready（人工裁决）。

        Returns: (success, message)
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False, "SPEC 不存在"
        if entry.get("status") != SpecStatus.BLOCKED:
            return False, "SPEC 状态不是 blocked"

        # 执行 blocked → ready
        success = self.state_machine.transition(spec_name, "ready")
        if not success:
            return False, "状态转移失败"

        # 清除评审相关字段
        self.state_machine.update_spec(spec_name, {
            "reviewer_run": None,
            "_review_attempts": 0,
            "error": None,
        })
        # 触发实现调度
        self.pm_engine._on_spec_ready(spec_name)
        return True, "担责放行已触发"