"""spec_review.py — SPEC 方案评审门禁的核心逻辑。

实现评审 run 的派发、结果消费、写入边界校验、故障重试与人工恢复入口。
"""

import hashlib
import json
import logging
import os
import re
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

# ── infra 失败指纹（evo-run-failure-classification-circuitbreaker D1）──────
# 评审 API 批量失败（403 网关拒绝 / 402 余额不足 / 429 限流 / quota/budget 耗尽 /
# rate limit / provider 侧熔断信号 / CLI 进程级崩溃）同属 infra——链路级问题，
# 非 spec 内容问题。指纹匹配大小写不敏感；"Exit code: 1" 不得一律判 infra
# （评审器内容失败同样 exit 1），仅当退出码非 0/1（进程级崩溃）才归 infra。
_INFRA_FINGERPRINTS = (
    "403", "402", "429",
    "quota", "budget", "余额", "insufficient balance", "rate limit",
    "provider circuit open", "provider chain exhausted",
    "model_chain_preflight_failed",
)
# CLI 进程级崩溃：error 含 "Exit code: <N>" 且 N 非 0/1
_CLI_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")


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
        """为指定 SPEC 派发一次评审 run，并在其收工后机械收口。

        本方法是评审的**唯一派发收口点**，「锚点落盘 → 快照 → 阻塞执行 → 消费结果」
        四步全在此闭合（评审门禁接线修复）：

        - **锚点（``reviewer_run``）在 run 启动之前写入**。``run_spec_review`` 为同步
          阻塞（分钟级）；若沿用「run 收工后才写锚点」的旧序，阻塞期间第二条派发通道
          （event_bus 轮询与 ``_on_spec_drafted`` 直调各一）读到锚点为空会再派一次，
          两个评审 Agent 并发改写同一 SPEC 目录（并发写者事故）。
        - **run 收工后立即 ``consume_review_result`` 收口**（approved/repaired → ready、
          rejected → blocked）。此前该消费点在全部生产路径上零调用——评审结果写盘后
          无人读，SPEC 永久停在 reviewing，随 daemon 重启被反复重派。

        Returns: True 表示评审 run 已执行收工；False 表示被拒或 run 执行失败。
        """
        # 链路级熔断短路（evo-run-failure-classification-circuitbreaker D2）：
        # spec-review 链路熔断窗口内直接返回不派发；冷却到期自动恢复重试。
        breaker = getattr(self.pm_engine, "infra_breaker", None)
        if breaker is not None:
            cond = breaker.condition("spec-review")
            if cond == "broken":
                remaining = breaker.cooldown_remaining("spec-review")
                self.logger.info(
                    "spec_review",
                    f"评审派发熔断短路: {spec_name}，冷却剩余 {remaining}s")
                return False
            if cond == "recovered":
                # 冷却到期自动恢复：落恢复 SIGNAL 记录（D3）
                self.pm_engine._emit_infra_breaker_event(
                    "recovered", spec_name, "", breaker.get_state("spec-review"))
        # 防重派：锚点在 run 启动前写入，故「在飞」与「已落锚点待消费」都表现为非空。
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            self.logger.warning("spec_review", f"SPEC 不存在: {spec_name}")
            return False
        if entry.get("reviewer_run"):
            self.logger.info("spec_review", f"已有在飞评审 run: {spec_name}")
            return False
        # 检查评审尝试次数
        try:
            attempts = int(entry.get("_review_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= MAX_REVIEW_ATTEMPTS:
            # 耗尽即转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # 改走 freeze_for_human「冻结 + 告警」成对入口——admin 对
            # 「评审器连续失败」无杠杆（模型链/配置问题）；冻结后
            # admin_monitor 的 blocked_stuck 豁免生效。
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-incomplete: 评审尝试已达上限"
                f"（{MAX_REVIEW_ATTEMPTS}）"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审尝试已达上限（{MAX_REVIEW_ATTEMPTS}），"
                    "评审器连续失败，需人工排查（模型链/配置问题）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={entry.get('reviewer_run') or '无'}; "
                    f"attempts={MAX_REVIEW_ATTEMPTS}"
                ),
                recommended_action=(
                    "人工排查评审链路（模型链/配置/结果硬门）；排查后经 "
                    "dashboard/CLI 解冻——解冻恢复原状态 reviewing，daemon "
                    "自动重派评审；或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={"reviewer_run": None, "_review_attempts": 0},
            )
            return False

        # ① 锚点先落盘：预生成 run_id，保证 STATE 里的 reviewer_run 与实际 run 一致
        run_id = f"spec-review-{spec_name}-{int(time.time())}"
        self.state_machine.update_spec(spec_name, {"reviewer_run": run_id})

        # ② 派发前快照（写入边界校验的基线）
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

        # ③ 阻塞执行评审 run（正常收工或异常后返回）
        attempt_started_at = time.time()
        try:
            result = self.agent_runner.run_spec_review(spec_name, run_id=run_id)
            run_ok = bool(getattr(result, "success", False))
            run_err = getattr(result, "error", None)
        except Exception as e:  # noqa: BLE001 — 派发异常须收口锚点，不得留残余
            run_ok, run_err = False, str(e)
        if not run_ok:
            self.logger.error("spec_review", f"评审 run 执行失败: {spec_name}: {run_err}")
            self._handle_review_failure(spec_name, f"评审 run 执行失败: {run_err}")
            return False
        self.logger.info("spec_review", f"评审 run 已收工: {spec_name} run_id={run_id}")

        # ③b 结果捞回（2026-09-15 事故修复）：评审 run 正常收工但从未调用 Write，
        # 把结果 JSON 当正文 fenced 代码块吐出。此处从转录代写落盘，避免整轮白烧
        # 重试。抽不出/已存在时不动作，交下方硬门按既有语义处理。
        salvage = getattr(self.agent_runner, "_salvage_spec_review_result", None)
        if callable(salvage):
            try:
                salvage(spec_name, run_id)
            except Exception as e:  # noqa: BLE001 — 捞回失败不得阻断收口
                self.logger.warning("spec_review", f"结果捞回异常: {spec_name}: {e}")

        # ④ 机械收口：结果缺失/越界由 _handle_review_failure 重试（保持既有语义）
        self.consume_review_result(spec_name, run_started_at=attempt_started_at)
        return True

    # ── 评审结果消费 ────────────────────────────────────────────

    def consume_review_result(self, spec_name: str,
                              run_started_at: float | None = None) -> bool:
        """消费评审结果：校验结果硬门与写入边界，按 status 机械收口。

        Args:
            run_started_at: 本轮 attempt 的启动 epoch 秒（供结果文件 mtime 新鲜度
                校验，防上轮残留合法文件替本轮放行——fix-verdict-read-failclosed
                D2 同款）。None 时跳过新鲜度校验（直调/测试兼容）。

        Returns: True 表示消费成功（状态已变更），False 表示消费失败（需重试）。
        """
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return False
        run_id = entry.get("reviewer_run")
        if not run_id:
            return False

        # 结果硬门校验（复用 _check_agent_result_artifact，spec-review 分支
        # 2026-09-15 已真接线：缺失/空/非白名单 status/陈旧 mtime 均由此拦截）
        err = self.agent_runner._check_agent_result_artifact(
            spec_name, "spec-review", run_started_at=run_started_at)
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
            # 评审否决 → 冻结转人工（fix-blocked-freeze-classification D3）：
            # admin 对「方案被否」无操作杠杆（2026-09-14 事故：17 分钟 admin
            # run 结论「无需介入」把原样 spec 弹回 reviewing → 下轮评审再次否决，
            # 整轮纯烧 token），故不打裸 blocked 而是 frozen=True + 人工升级
            # 告警，使 admin_monitor 的 blocked_stuck 豁免生效。
            findings = data.get("findings") or []
            blocking = [f for f in findings if f.get("severity") == "blocking"]
            blocked_summary = "; ".join(
                f.get("detail", "") for f in blocking
            ) if blocking else "无详情"
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-rejected: {blocked_summary}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-rejected",
                severity="major",
                description=(
                    f"'{spec_name}' 方案被评审否决，需人工修订方案或撤销"
                    f"（blocking findings: {blocked_summary}; "
                    f"评审 run={run_id}）"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={run_id}; "
                    f"findings={blocked_summary}"
                ),
                recommended_action=(
                    "人工修订 spec 方案（proposal.md/design.md）后经 dashboard/"
                    "CLI 解冻——解冻恢复原状态 reviewing，daemon 自动重派评审；"
                    "或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={"reviewer_run": None, "_review_attempts": 0},
            )
            self.logger.info("spec_review", f"评审否决已冻结转人工: {spec_name}")
            return True
        else:
            # 理论上不会到这里
            self._handle_review_failure(spec_name, f"未知 status: {status}")
            return False

    # ── 写入边界校验 ────────────────────────────────────────────

    def _take_snapshot(self, spec_name: str) -> dict:
        """派发前对 SPEC 目录与工作区脏文件记录快照。

        返回快照 dict，包含：
        - spec_files: {相对路径: 内容哈希}——SPEC 目录完整性硬门依据（删除即越界）
        - dirty_files: {相对路径: 内容哈希}（仅 git status --porcelain 列出的脏文件）
          ——仅供 `_verify_snapshot` 记 WARNING 留痕与「新增文件」去重，不作硬门
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

        **只对可归因信号开硬门**（该变动有且仅有「评审者越界」一种解释）：

        - SPEC 目录内文件被删除——评审者只被授权就地修补，删除必为越界。

        工作区扫描（既存脏文件被改动、SPEC 目录外新增未跟踪文件）**不作为硬门**：
        评审 run 同步阻塞数分钟且 cwd = 主树，期间任何并发写者（人工编辑、其他
        会话、其他 run）触碰主树都会命中，两者都无法与评审者越界区分。2026-09-14
        evo-item-retention-doc-tracking 因此连丢三份评审结果（约 $25）并空转至尝试
        耗尽。现改为记 WARNING 留痕、放行——评审者的真实写入边界由 repairs 路径
        合法性（`_check_write_boundary` 步骤 1）与结果契约共同钉死。
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

        # 工作区脏文件变动：非归因，仅留痕
        changed_dirty = []
        for rel, old_hash in snapshot.get("dirty_files", {}).items():
            full = self.project_root / rel
            if not full.exists():
                continue  # 文件被删除，可能不是评审者所为
            try:
                content = full.read_bytes()
                new_hash = hashlib.md5(content).hexdigest()
                if new_hash != old_hash:
                    changed_dirty.append(rel)
            except OSError:
                pass
        if changed_dirty:
            self.logger.warning(
                "spec_review",
                f"评审期间工作区脏文件被改动（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(changed_dirty))}",
            )

        # SPEC 目录外新增未跟踪文件：非归因（并发写者新建文件同样命中），仅留痕
        added_untracked = []
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
                                    added_untracked.append(path)
        except (subprocess.SubprocessError, OSError):
            pass
        if added_untracked:
            self.logger.warning(
                "spec_review",
                f"评审期间 SPEC 目录外新增未跟踪文件（非归因，放行）: {spec_name}: "
                f"{', '.join(sorted(added_untracked))}",
            )

        return None

    def _check_write_boundary(self, spec_name: str, review_data: dict) -> Optional[str]:
        """校验评审 run 的写入边界：repairs 路径合法性、SPEC 目录完整性、status 与改动一致。

        工作区扫描（脏文件变动 / 目录外新增文件）只留痕不拦截——非归因信号，
        见 `_verify_snapshot`。

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
            # 检查是否确实存在于 SPEC 目录内（path 为项目根相对路径）
            if not (self.project_root / path).exists():
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

    def _classify_run_failure(self, reason: str, spec_name: str) -> str:
        """三类失败分类（evo-run-failure-classification-circuitbreaker D1）。

        扩展 evo-run-failure-artifact-first 的 `_classify_run_failure(reason)`（沿用
        同名，勿另开 `_classify_failure`；该 SPEC 未落位时在本 SPEC 以同名新建）为
        三分 "artifact" | "infra" | "content"：

        - artifact：产物已落盘合法（调用 `_artifact_landed_valid`）；优先级最高；
        - infra：指纹匹配（403/402/429/quota/budget/余额/insufficient balance/
          rate limit / 既有 provider 熔断信号 "provider circuit open" /
          "provider chain exhausted"——runner.py:2458/2473，供侧熔断同属 infra）
          或 CLI 进程级崩溃（error 含 "Exit code: N" 且 N 非 0/1——"Exit code: 1"
          不得一律判 infra，评审器内容失败同样 exit 1）；或 probe 标记
          model_chain_preflight_failed；
        - content：其余（含空白轮次）。

        Returns: "artifact" | "infra" | "content"。
        """
        # artifact 分支优先级最高：产物已落盘合法 → 判别失败，直接消费不重试。
        if spec_name and self._artifact_landed_valid(spec_name):
            return "artifact"
        low = (reason or "").lower()
        for fp in _INFRA_FINGERPRINTS:
            if fp in low:
                return "infra"
        # CLI 进程级崩溃：exit code 非 0/1（0 正常 / 1 内容失败）
        m = _CLI_EXIT_CODE_RE.search(reason or "")
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
            if code not in (None, 0, 1):
                return "infra"
        return "content"

    def _artifact_landed_valid(self, spec_name: str) -> bool:
        """产物是否已合法落盘（evo-run-failure-artifact-first 的 `_artifact_landed_valid`）。

        评审 run 的产物 = `.fenix/spec-review/<spec>/.fenix-run-result.json`：
        存在、非空、JSON 可解析且 status 在白名单内 → 合法产物。
        该 SPEC（run-failure-artifact-first）未实现时此处按同语义回退 content。
        """
        result_path = spec_review_result_path(self.project_root, spec_name)
        try:
            if not result_path.exists() or result_path.stat().st_size == 0:
                return False
            data = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            return data.get("status") in spec_review_result_status_whitelist
        except (OSError, json.JSONDecodeError):
            return False

    def _handle_review_failure(self, spec_name: str, reason: str):
        """处理评审失败：按失败分类落点（D1/D2）。

        - artifact：产物已落盘合法 → 直接消费（不重试，run-failure-artifact-first
          承接；`_artifact_landed_valid` 缺失时回退 content）；
        - infra：熔断计数 + 升级告警；清 reviewer_run、**不递增 _review_attempts**
          （熔断前与冷却期均不计入——infra 属链路级问题而非 spec 内容问题；若递增，
          第 3 次 infra 会同时触 MAX_REVIEW_ATTEMPTS=3 freeze 破坏「冷却后自动
          恢复」；若不清锚点，冷却到期后 dispatch_review 见 reviewer_run 非空拒派
          （spec_review.py:67-69），spec 永久卡 reviewing）；
        - content：维持既有重试语义（递增 _review_attempts，达上限转冻结转人工）。
        """
        failure_type = self._classify_run_failure(reason, spec_name)

        if failure_type == "artifact":
            # 判别失败：产物已落盘合法 → 直接消费收口，不重试。
            self.logger.info(
                "spec_review",
                f"判别失败（产物已落盘）→ 直接消费: {spec_name}")
            self.consume_review_result(spec_name)
            return

        if failure_type == "infra":
            # infra 失败：熔断计数 + 升级告警（触发熔断时恰好落一条 critical）。
            breaker = getattr(self.pm_engine, "infra_breaker", None)
            if breaker is not None:
                triggered = breaker.record_failure("spec-review")
                if triggered:
                    self.pm_engine._emit_infra_breaker_event(
                        "triggered", spec_name, reason,
                        breaker.get_state("spec-review"))
            # 清 reviewer_run、不递增 _review_attempts（保持原值）
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "error": f"spec-review-incomplete: infra failure: {reason}",
            })
            self.logger.warning(
                "spec_review",
                f"评审 infra 失败（熔断计数，不递增尝试）: {spec_name}: {reason}")
            return

        # ── content 分支：既有重试语义 ──
        entry = self.state_machine.read_one(spec_name)
        if not entry:
            return
        try:
            attempts = int(entry.get("_review_attempts", 0) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts < MAX_REVIEW_ATTEMPTS:
            # 重试：保持 reviewing 状态，清除 reviewer_run
            self.state_machine.update_spec(spec_name, {
                "reviewer_run": None,
                "_review_attempts": attempts + 1,
                "error": f"spec-review-incomplete: {reason}",
            })
            self.logger.info("spec_review", f"评审失败重试: {spec_name} attempt={attempts+1}")
        else:
            # 达上限转冻结转人工（fix-blocked-freeze-classification 2.2）：
            # admin 对「评审器连续失败」无操作杠杆（模型链/配置问题），
            # 改走 freeze_for_human「冻结 + 告警」成对入口，使 admin_monitor
            # 的 blocked_stuck 豁免生效。
            r_id = entry.get("reviewer_run")
            error_msg = (
                f"{FREEZE_ERROR_PREFIX}原状态 reviewing · "
                f"spec-review-incomplete: {reason}"
            )
            self.state_machine.freeze_for_human(
                spec_name,
                error=error_msg,
                signal_type="spec-review-incomplete",
                severity="major",
                description=(
                    f"'{spec_name}' 评审器连续失败（模型链/配置问题）至"
                    f"尝试上限（{MAX_REVIEW_ATTEMPTS}），需人工排查"
                ),
                evidence=(
                    f"spec={spec_name}; run_id={r_id or '无'}; reason={reason}"
                ),
                recommended_action=(
                    "人工排查评审链路根因（模型链/配置/结果硬门/写入边界）；"
                    "排查后经 dashboard/CLI 解冻——解冻恢复原状态 reviewing，"
                    "daemon 自动重派评审；或直接撤销该 spec"
                ),
                alert_callback=self.pm_engine._send_human_escalation_alert,
                extra_updates={"reviewer_run": None, "_review_attempts": 0},
            )
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

        # 派发新评审（agent_runner 为 None 的 CLI 场景跳过派发，
        # 由 daemon full_scan recovery 的 reviewing 分支拾取）
        if self.agent_runner is not None:
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