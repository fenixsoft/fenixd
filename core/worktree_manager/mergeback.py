"""mergeback.py — G4 merge-back 主链（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 12 个方法（含 208 行 `_merge_back_from_branch_locked`），
原样搬移为 mixin（方法体零改动）。含 2 个 lazy import：
- `collapse_wip_commits`（from core.wip_checkpoint，防循环）
- `WorktreeManager`（引用类级属性 `_rehearsal_*`，方法体内延迟导入防循环）

D3 patch 缝隙：`MergeConflictInfo` 从 types 模块导入（包命名空间 re-export）。
"""

from __future__ import annotations

import shutil
import subprocess
import time

from pathlib import Path
from typing import Optional

from core.wip_checkpoint import collapse_wip_commits  # noqa: E402
from core.worktree_manager.types import MergeConflictInfo
from core.worktree_manager import WIP_GATE_STASH_PREFIX  # noqa: E402


class G4MergebackMixin:
    """G4 merge-back 主链（design D1 表 A G4）。"""


    def get_branch_name(self, wt_path: Path) -> Optional[str]:
        """Return the branch name for an active worktree, or None if unknown."""
        return self._wt_branches.get(str(wt_path))

    def merge_back(self, wt_path: Path) -> MergeConflictInfo:
        """Merge the worktree's branch into the main tree (project_root HEAD).

        Uses `git merge --no-ff` to preserve history. Idempotent: if the branch
        is already an ancestor of HEAD, skips and reports success.

        Returns: ``MergeConflictInfo``（兼容 ``(bool, str)`` 解包）。
        """
        wt_str = str(wt_path)
        branch = self._wt_branches.get(wt_str)
        if not branch:
            return MergeConflictInfo(False, f"Unknown worktree (no branch recorded): {wt_path}")
        return self.merge_back_from_branch(branch)

    def merge_back_from_branch(self, branch: str) -> MergeConflictInfo:
        """Merge a worktree branch into the main tree (project_root HEAD).

        与 merge_back(wt_path) 等价，但直接接受分支名。用于 worktree 已被清理、
        但分支仍保留的场景（implementer 成功路径）。

        主树干净由 guard 原子保证（fix-autostash-orphans）：锁内 stash→merge→pop
        同步段完成。不再依赖「派发前 stash + 成功路径才 pop」的长窗口配对——
        那种配对在任何失败/重派/异常/daemon 重启路径下都会把用户未提交改动
        滞留在 stash 栈（曾致 7 次改动"消失"事故）。段内 pop 弹到的必是刚 push
        的条目（锁串行 + LIFO），历史滞留条目由周期巡检兜底回收。

        预演闸（add-merge-tree-rehearsal D1）：真合并（stash/merge/abort 序列）
        之前先以 ``git merge-tree --write-tree`` 只读预演。语义冲突在主树零污染
        点被拦截——不 stash、不 merge、不 abort，直接返回带 ``rehearsed=True``
        标记的结构化冲突分类，调度层据此直通 repair 通道（spec 保持 in-flight、
        不经 fp 记账）；零冲突与纯产物/ignored-DU 冲突放行现行流程逐字节不变。

        Returns: ``MergeConflictInfo``——兼容 ``(bool, str)`` 解包
        （``success, err = merge_back_from_branch(...)``），额外携带冲突路径
        清单与语义冲突分类（add-merge-back-repair-lane D1，供调度层决定是否
        进入 repair 通道）。
        """
        if not branch:
            return MergeConflictInfo(False, "Empty branch name")

        with self._main_tree_lock:
            # 预演闸（add-merge-tree-rehearsal D1/D2）：guard 锁内、stash 之前只读
            # 预演。语义冲突 → 直接返回 rehearsed 标记（主树零污染，调度层直通
            # repair）；None = 放行（零冲突或产物/ignored-DU 冲突）→ 走现行流程。
            rehearsed_info = self._rehearse_merge_from_branch(branch)
            if rehearsed_info is not None:
                return rehearsed_info

            self.last_stash_pop_conflicts = []
            self.last_stash_entry_fate = {"kept": True, "sha": ""}
            # WIP 重叠闸门（evo-merge-back-wip-overlap-gate D1/D2；缺省处置已由
            # add-pipeline-throughput-governance D2/merge-back-precheck 从 auto
            # 收纳改为升级拦截，策略解析与变更依据见 _wip_gate_policy）：预演闸
            # 放行后、stash 之前，把「主树脏 tracked ∩ 分支改动」（已排除
            # spec/changes，见 _detect_wip_overlap）升级为执行级前置处置：
            #   * 无重叠 / 检测命令失败 → 放行现行 autostash→merge→pop 路径
            #     （逐字节不变；闸门自身异常 MUST 退化为不阻塞、不新增 stash）；
            #   * 有重叠 + 缺省（escalate）或显式 block 策略 → 拦截：不发起
            #     merge（不 stash、不 merge、不 pop，主树零污染），返回携带
            #     wip_gate_blocked=True 的可区分失败，dispatch 层据此旁路熔断
            #     记账、直发人工升级告警（含交集清单与两侧来源），spec 保持
            #     可重试状态（不冻结、不销毁分支与产物）；
            #   * 有重叠 + 显式 worktree.mergeback_wip_overlap_policy=auto →
            #     保留收纳语义（读侧兼容）：重叠改动随 ensure_clean_tree 的
            #     stash 卷走（闸门专用前缀 WIP_GATE_STASH_PREFIX），merge 成功
            #     后恢复；pop 冲突时保留条目 + 记录去向（last_stash_entry_fate）
            #     + 逐文件找回命令；
            #   * worktree.merge_precheck_bypass=true 逃生门（2.3）→ 跳过预检
            #     直接 merge（紧急推送用，冲突按既有失败路径处理）。
            gate_blocked, wip_overlap = self._wip_overlap_gate(branch)
            if gate_blocked is not None:
                return gate_blocked

            # ── spec 目录在飞编辑卫检查（evo-merge-back-spec-dir-inflight-guard D1）──
            # 闸门顺序（task 0.1 固化）：rehearsed（line 77）→ wip_overlap_gate
            # （line 96）→ 本卫检查 → ensure_clean_tree（line 100）。三者均为主树
            # 零污染早退，顺序不改变各自判定结果，但 MUST 固化以防把「需 repair 的
            # 冲突」误报为「等待提交」。复用 _spec_from_branch（queries.py:43）从
            # 分支名解析 spec；解析失败（非 fenix/<spec>-<ts> 形态）→ 返回 None
            # 放行（fail-open，MUST NOT 退化为对 spec/changes/ 全目录检测）。
            inflight_info = self._check_spec_dir_inflight(branch)
            if inflight_info is not None:
                return inflight_info

            stashed = self.ensure_clean_tree(
                prefix=WIP_GATE_STASH_PREFIX if wip_overlap else None
            )
            try:
                info = self._merge_back_from_branch_locked(branch)
                info.wip_overlap = wip_overlap
                return info
            finally:
                if stashed:
                    _ok, conflict_files = self.restore_after_merge()
                    if conflict_files:
                        self.last_stash_pop_conflicts = list(conflict_files)

    def _wip_gate_policy(self) -> str:
        """merge-back 前 WIP 重叠闸门策略（evo-merge-back-wip-overlap-gate D1，
        add-pipeline-throughput-governance D2 策略变更）。

        **缺省升级拦截（escalate）**——本方法的有意策略变更
        （add-pipeline-throughput-governance D2/merge-back-precheck）：交集
        非空的缺省处置从 auto stash 收纳（静默放行）改为升级人工拦截。变更
        依据：全历史 done→pushed 均值 41m（P50 仅 14s）几乎全由「尝试
        merge→冲突→autostash→回滚→重试」失败循环贡献（138 次 git 冲突告警），
        auto 收纳后的 pop 冲突是该循环的上游放大器——把可预判的重叠前置拦截，
        换取无效 merge 轮次归零。已知 trade-off：不同 hunk 本可自动合并的重叠
        也会被拦（设计 Risks「预检误拦」条目），由逃生门
        ``worktree.merge_precheck_bypass`` 与「告警附交集清单供人工秒判」兜底。

        读侧兼容：显式 ``worktree.mergeback_wip_overlap_policy=auto`` 的项目
        维持旧收纳语义不变；显式 ``block`` 并入升级出口（escalate 与 block 同
        为「不发起 merge、人工处置」，返回同构 ``wip_gate_blocked=True``，
        消费端 dispatch 层旁路熔断记账、直发人工告警的既有语义复用）。
        读取/解析异常回退 escalate——缺省方向宁紧勿松（本能力的目的正是把
        静默放行改为显式升级，故障回退 auto 会把闸门失效藏回静默路径）。
        """
        policy = getattr(self, "_mergeback_wip_overlap_policy", None)
        if isinstance(policy, bool):
            return "escalate" if policy else "auto"
        text = str(policy).strip().lower() if policy is not None else ""
        if text in ("auto", "0", "false", "no", "off"):
            return "auto"
        # 缺省（None）/ block / 未知值 → 升级拦截（block 语义并入升级出口）
        return "escalate"

    def _merge_precheck_bypass_enabled(self) -> bool:
        """merge_precheck_bypass 逃生门（add-pipeline-throughput-governance 2.3）。

        true 时跳过 WIP 重叠预检直接 merge（紧急推送用）：预检、产物对齐与
        重叠收纳均不执行，冲突时按既有 merge 失败路径处理（与未引入预检能力
        前一致）。配置经构造参数注入（缺省 False，即 ``worktree.
        merge_precheck_bypass``）；读取异常一律 False——逃生门故障 fail-open
        回预检，MUST NOT 把配置事故放大为静默跳过治理。
        """
        bypass = getattr(self, "_merge_precheck_bypass", False)
        if isinstance(bypass, bool):
            return bypass
        return str(bypass).strip().lower() in ("1", "true", "yes", "on")

    def _check_spec_dir_inflight(self, branch: str):
        """spec/changes/<spec>/ 在飞未提交编辑检测（evo-merge-back-spec-dir-inflight-guard D1）。

        在 ``_main_tree_lock`` 内、``_wip_overlap_gate`` 之后、
        ``ensure_clean_tree`` 之前调用。对 ``spec/changes/<spec>/`` 整个目录
        （含 ``specs/**``、proposal/design/tasks）执行 ``git status --porcelain
        -- <rel>`` 检测未提交改动（含 untracked）。

        Returns:
            - ``MergeConflictInfo``（``spec_dir_inflight=True``，``success=False``）
              命中时——调用方直接返回，不进入 merge、不 stash、不触碰主树；
            - ``None``——spec 目录干净（放行），或解析失败（fail-open），或命令
              失败/超时（保守放行）。

        spec 名解析复用 ``_spec_from_branch``（queries.py:43）；解析失败
        （返回 None/非 str）→ 返回 None（fail-open，MUST NOT 退化为对整个
        ``spec/changes/`` 的检测，D1 精度要求）。
        """
        spec = self._spec_from_branch(branch)
        if not spec or not isinstance(spec, str):
            return None
        rel = f"spec/changes/{spec}"
        try:
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "status",
                    "--porcelain",
                    "--",
                    rel,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if res.returncode != 0:
            return None
        dirty = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        if not dirty:
            return None
        self.logger.warning(
            "worktree_manager",
            f"spec 目录在飞编辑检测到 {rel}/ 存在 {len(dirty)} 个未提交改动文件"
            f"（含 untracked）：{dirty[:5]}{'…' if len(dirty) > 5 else ''}"
            f" — merge-back 顺延等待提交（spec_dir_inflight）",
        )
        return MergeConflictInfo(
            False,
            f"spec 目录在飞编辑：{rel}/ 有 {len(dirty)} 个未提交改动"
            f"（{dirty[0]}{'…' if len(dirty) > 1 else ''}）"
            f" — merge-back 顺延等待提交动作解除"
            f"（提交或 git commit -a 'spec: {spec}' 后重试）",
            spec_dir_inflight=True,
        )

    def _wip_overlap_gate(self, branch: str) -> tuple:
        """merge-back 前 WIP 重叠闸门（evo-merge-back-wip-overlap-gate D1/D2，
        evo-merge-back-wip-artifact-scope D3b）。

        在 ``_main_tree_lock`` 内、``ensure_clean_tree`` 之前调用。返回
        ``(blocked, overlap)``：

        - ``blocked``：非 None 时即调用方需直接返回的 ``MergeConflictInfo``
          （``wip_gate_blocked=True``，主树未被 stash/merge/pop 触碰）；
          None = 放行（无重叠 / 收纳策略 / 检测命令失败）。
        - ``overlap``：**语义**重叠文件清单（已排除 ``spec/changes/**`` 和配置
          产物），供调用方决定收纳 stash 前缀与挂到成功/失败返回值
          （``info.wip_overlap``）。产物重叠在此方法内已按 D3b 对齐 HEAD（
          ``git checkout HEAD -- <p>``），不再进入重叠集合。

        **D3b 核心动机**：`ensure_clean_tree()`（`mergeback.py:100`）在闸门放行后
        **无条件**对全树 tracked 脏改动执行 stash；产物的未提交改动**不需要
        保护**（产物是 src 的投影，merge 后由构建重建），把它纳入重叠集合只会
        制造必然的 pop 冲突与误报 major 告警。因此在 `ensure_clean_tree` 之前，
        把重叠集合中判定为产物的子集对齐 HEAD（使其变干净、不进 stash、pop 无
        产物冲突）——从源头消除「产物 → stash → pop 冲突 → 误报 major 告警」链路。
        """
        # 产物配置未裁决兜底信号（fix-artifact-paths-hardcoded-default D3）：
        # MUST 置于「无重叠早退」之前——主树干净是常态，若在早退之后判定，最
        # 常见形态永不触发起草，配置缺口被静默掩盖（本 SPEC 要消灭的「默认值
        # 掩盖配置缺口」问题的复刻）。信号不改闸门判定，只呼叫 Administrator 起草。
        self._maybe_signal_build_artifact_paths_missing(branch)
        # merge_precheck_bypass 逃生门（add-pipeline-throughput-governance 2.3）：
        # 显式豁免预检（紧急推送用）——放行现行 autostash→merge→pop 路径，
        # 与未引入预检能力前一致；冲突时按既有失败路径处理。
        if self._merge_precheck_bypass_enabled():
            self.logger.warning(
                "worktree_manager",
                "merge_precheck_bypass=true：跳过 WIP 重叠预检直接 merge"
                "（冲突时按既有失败路径处理）",
            )
            return None, []
        overlap = self._detect_wip_overlap(branch)
        if not overlap:
            return None, []

        # ── D3b：按实例判定器切分产物 / 语义重叠 ──────────────────────────
        artifact_overlap = self._artifacts.paths_in(overlap)
        semantic_overlap = self._artifacts.non_artifacts_in(overlap)

        # 产物重叠逐路径对齐 HEAD（与 _resolve_build_artifact_conflicts 的
        # 「产物无条件对齐 HEAD」同语义：产物是 src 投影，merge 后由构建重建）。
        # 只作用于重叠子集——主树独有、分支未触碰的产物改动 MUST NOT 被对齐
        # （仍走既有 stash/pop 往返），若一并丢弃等于把「用户本地刚构建、分支
        # 根本没碰」的产物静默抹掉，属净回归。
        if artifact_overlap:
            aligned_ok, aligned_fail = [], []
            for p in artifact_overlap:
                try:
                    result = subprocess.run(
                        [
                            "git", "-C", str(self.project_root),
                            "checkout", "HEAD", "--", p,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        aligned_ok.append(p)
                    else:
                        aligned_fail.append(p)
                except (subprocess.TimeoutExpired, OSError):
                    aligned_fail.append(p)

            if aligned_ok:
                self.logger.info(
                    "worktree_manager",
                    f"WIP overlap D3b: aligned {len(aligned_ok)} artifact(s) to "
                    f"HEAD before stash — {aligned_ok}",
                )
            # 对齐失败的路径**逐路径**回落：并入 semantic_overlap——即退回
            # 现行行为（照旧 stash、照旧可能 pop 冲突与告警）。
            # **fail-safe 方向 = 与现行行为一致**：MUST NOT 因对齐失败而阻塞
            # merge-back、MUST NOT 跳过 stash、MUST NOT 改宽判定。
            if aligned_fail:
                self.logger.warning(
                    "worktree_manager",
                    f"WIP overlap D3b: {len(aligned_fail)} artifact(s) failed to "
                    f"align to HEAD — falling back to semantic overlap: {aligned_fail}",
                )
                semantic_overlap = sorted(semantic_overlap + aligned_fail)

        # 对齐后返回语义集合（纯产物重叠不再阻塞 merge-back）
        if not semantic_overlap:
            return None, []
        overlap = semantic_overlap  # 语义重叠（产物已干净或回落为语义）
        # 升级拦截出口（add-pipeline-throughput-governance D2/merge-back-precheck）：
        # 缺省（escalate）与显式 block（并入升级出口）一致——不发起 merge、
        # 主树零污染，返回 wip_gate_blocked=True 由 dispatch 层直发人工升级
        # 告警（含交集清单与两侧来源：主树 WIP 未提交 × 分支已提交改动）、
        # spec 保持可重试状态（不冻结、不销毁分支与产物）。
        if self._wip_gate_policy() == "escalate":
            error = (
                f"Merge-back blocked by WIP overlap precheck (policy=escalate): "
                f"{len(overlap)} main-tree tracked file(s) with uncommitted changes "
                f"overlap branch '{branch}' changes: {overlap}. "
                f"处置：提交（git add/commit）或 stash（git stash push）主树这些"
                f"改动后重新放行该 spec（spec 保持可重试）——git stash list 查条目"
                f"去向、git show <sha>:<file> 按文件找回；紧急情况可配置 "
                f"worktree.merge_precheck_bypass=true 豁免预检"
            )
            self.logger.error("worktree_manager", error)
            return (
                MergeConflictInfo(False, error, wip_overlap=overlap, wip_gate_blocked=True),
                overlap,
            )
        # 显式 auto（读侧兼容保留）：重叠改动随 ensure_clean_tree 的 stash 卷走（闸门专用前缀，
        # 与 reclaim_stale_autostash 只认的 AUTOSTASH_MSG_PREFIX 隔离），merge
        # 成功后恢复；pop 冲突保留条目 + 去向可见。
        self.logger.warning(
            "worktree_manager",
            f"WIP overlap gate (policy=auto, default): {len(overlap)} main-tree "
            f"tracked file(s) overlapped with branch '{branch}' changes — will be "
            f"stashed with gate prefix and restored after merge: {overlap}",
        )
        return None, overlap

    def _maybe_signal_build_artifact_paths_missing(self, branch: str) -> None:
        """产物配置未裁决时的起草兜底信号（fix-artifact-paths-hardcoded-default D3）。

        仅在「需要区分产物与语义内容」的 merge-back WIP 重叠闸门咽喉触发，投喂
        Administrator 起草产物配置（`worktree.has_build_artifacts` +
        `build_artifact_paths`）。触发条件 = 判定「未裁决」（has 缺省，或 true 配
        空路径）；已裁决（false / 路径非空）不写。信号不改闸门判定，只呼叫起草。

        全链路复用 `verify_contract_missing` 模式：`AdminStore.append` 写
        kind=SIGNAL（severity=major），`admin_monitor` 摄取唤起 Administrator；
        信号带 `spec` 字段（`_spec_from_branch` 推导，merge-back 链路既有 helper），
        evidence 另附「项目名=<name>」作冗余证据（摄取侧对无 spec 形态仍支持从
        evidence 解析项目名）。在途去重（D3）：同项目同 signal_type 的未消费信号
        已存在时跳过重复写入。写入异常记 warning 不抛穿（信号通道故障不影响
        merge-back 判定）。
        """
        try:
            if not self._artifacts.is_config_unresolved():
                return
            from core.admin_store import AdminStore, SIGNAL

            project_name = self.project_root.name
            spec = self._spec_from_branch(branch)
            evidence = f"项目名={project_name}"
            if branch:
                evidence += f"; branch={branch}"
            store = AdminStore(self.project_root, self.logger)
            # 在途去重（照搬 settings_routes._api_verify_yaml_autodraft_post 的
            # inflight 判定范式：kind==SIGNAL 且未 handled 且 evidence 含项目名）
            inflight = [
                r
                for r in store.read_all()
                if r.get("kind") == SIGNAL
                and r.get("signal_type") == "build_artifact_paths_missing"
                and not r.get("handled")
                and f"项目名={project_name}" in (r.get("evidence") or "")
            ]
            if inflight:
                return
            # add-human-adjudication-choices 2.7：配置裁决类发射点快照 choices
            # （open_config/declare_no_artifacts）。kind=SIGNAL 记录不进前端
            # 告警区（unhandled 仅含 ESCALATION），choices 由 Administrator
            # 处置契约 / alert-resolve 端点消费。局部导入避免模块级环依赖。
            from core.dashboard.data.adjudication_choices import choices_for

            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "build_artifact_paths_missing",
                    "choices": list(choices_for("build_artifact_paths_missing")),
                    "spec": spec or "",
                    "severity": "major",
                    "description": (
                        f"项目 {project_name} 未声明构建产物配置"
                        f"（worktree.has_build_artifacts / build_artifact_paths "
                        f"未裁决）——merge-back WIP 重叠闸门无法区分产物与语义内容，"
                        f"产物会被当语义内容处理。请探测并填写产物路径；确无产物时"
                        f"写 has_build_artifacts=false 结案。"
                    ),
                    "evidence": evidence,
                    "recommended_action": (
                        "Administrator 起草 .fenix/config.yaml 的产物路径配置："
                        "bin/fenix_detect_artifacts.py 探测候选路径（输入源："
                        "package.json scripts / pyproject.toml / 目录结构 / "
                        "project.type）；路径合法性经 validate_build_artifact_paths "
                        "同口径校验；确无产物写 has_build_artifacts=false 结案，"
                        "不得用「路径留空」冒充已裁决"
                    ),
                }
            )
            self.logger.warning(
                "worktree_manager",
                f"build_artifact_paths_missing 信号已写入 "
                f"(spec={spec or '?'}, project={project_name}) — "
                f"呼叫 Administrator 起草产物路径配置",
            )
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"build_artifact_paths_missing 信号写入失败"
                f"（不影响 merge-back 判定）: {e}",
            )

    def _detect_wip_overlap(self, branch: str) -> list:
        """merge-back 前 WIP 重叠预检（fix-mergeback-stashpop-silent-loss D3）。

        计算主树脏 tracked 文件与 ``merge-base..branch`` 分支改动文件的交集。
        非空 → 记 WARNING（含重叠清单），返回清单供挂到 MergeConflictInfo；
        空/命令失败 → 返回空列表、零行为变化。只读不阻断：不 stash、不改状态。

        **闸门作用域（evo-merge-back-wip-overlap-gate D2）**：重叠集合排除
        ``spec/changes/**``——该前缀被 ``ensure_clean_tree`` 的 autostash 显式
        ``:(exclude)spec/changes`` 排除（收纳对它无效：stash 卷不走、merge 仍可
        能被拒绝），却可在主树长期脏（纳入闸门会让几乎每次 merge-back 被阻塞）；
        其「主树脏 + 分支同改」由既有提交通道 ``ensure_spec_committed`` /
        ``_commit_softened_declaration`` 收口，MUST NOT 为它引入新的 stash/阻塞
        语义。

        **产物排除（evo-merge-back-wip-artifact-scope D3b）**：本方法**保持只读、
        语义不变**——产物路径（配置声明的产物前缀/通配）仍在返回的重叠集合中
        交付，由调用方 ``_wip_overlap_gate`` 另行切分处置。产物的排除与
        ``spec/changes/**`` 排除**语义不同、MUST NOT 合并**：前者是「可再生的
        投影」（merge 后由构建重建），后者是「框架运行必需、有独立提交通道」。
        且产物侧无 autostash 对偶排除（``:(exclude)`` 不覆盖产物），产物仍会被
        autostash 卷走，故产物必须在 stash **之前**对齐 HEAD（见 ``_wip_overlap_gate``
        的 D3b 段）。

        Returns: 排序后的重叠文件路径列表（无重叠为空列表）。
        """
        try:
            dirty = self._list_dirty_tracked_files()
            if not dirty:
                return []
            mb = subprocess.run(
                ["git", "-C", str(self.project_root), "merge-base", "HEAD", branch],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if mb.returncode != 0 or not mb.stdout.strip():
                return []
            diff = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--name-only",
                    mb.stdout.strip(),
                    branch,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff.returncode != 0:
                return []
            branch_files = {ln.strip() for ln in diff.stdout.splitlines() if ln.strip()}
            overlap = sorted(set(dirty) & branch_files)
            # 闸门作用域（evo-merge-back-wip-overlap-gate D2）：排除 spec/changes/**
            # ——见上方 docstring，纳入闸门会分别导致「收纳无效」与「几乎每次
            # merge-back 阻塞」。该前缀的「主树脏 + 分支同改」走既有提交通道。
            overlap = [
                p
                for p in overlap
                if not (p == "spec/changes" or p.startswith("spec/changes/"))
            ]
            if overlap:
                self.logger.warning(
                    "worktree_manager",
                    f"WIP overlap precheck before merge-back of '{branch}': "
                    f"{len(overlap)} dirty tracked file(s) also changed on branch "
                    f"— {overlap} (warning only, merge proceeds)",
                )
            return overlap
        except (subprocess.TimeoutExpired, OSError):
            return []

    def _merge_tree_supported(self) -> bool:
        """``git merge-tree --write-tree`` 可用性一次性探测（进程内缓存）。

        以空参试探：git ≥ 2.38 支持该选项（输出 usage）；旧版把未知选项报为
        ``unknown option``。探测结果类级缓存（多实例共享、进程一生只探一次），
        不支持时记一次性 WARNING（不刷屏），预演闸永久跳过。
        """
        from core.worktree_manager import WorktreeManager  # lazy import to avoid cycle
        if not WorktreeManager._rehearsal_probe_done:
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "merge-tree", "--write-tree"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                WorktreeManager._rehearsal_supported = "unknown option" not in res.stderr
            except (subprocess.SubprocessError, OSError):
                WorktreeManager._rehearsal_supported = False
            WorktreeManager._rehearsal_probe_done = True
            if not WorktreeManager._rehearsal_supported:
                self.logger.warning(
                    "worktree_manager",
                    "git merge-tree --write-tree 不可用（需 git ≥ 2.38）— "
                    "merge 预演闸跳过，行为回退现行",
                )
        return WorktreeManager._rehearsal_supported

    def _rehearse_merge_from_branch(self, branch: str) -> Optional[MergeConflictInfo]:
        """真合并前只读预演（add-merge-tree-rehearsal D1/D2/D4）。

        在 ``_main_tree_lock`` 内、stash 之前调用。以 ``git merge-tree --write-tree
        --name-only HEAD <branch>`` 预演分支并入主树的结果：

        - 返回 ``None``：放行——零冲突，或预演检出冲突全部为构建产物/被 .gitignore
          忽略的 DU 运行时草稿（这两类在现行真合并里由既有产物/ignored 自愈收口，
          行为不变）；
        - 返回 ``MergeConflictInfo``（``rehearsed=True``）：预演检出语义冲突，主树
          未被 stash/merge/abort 触碰，调度层据此直通 repair 通道。

        git 不支持 merge-tree、或预演命令失败/超时时同样返回 ``None``（保守：
        宁可行现行行为，不因预演故障误拦合并）。预演自身不修改主树与分支的任何
        状态（merge-tree 只读、不触索引与工作区）。
        """
        if not self._merge_tree_supported():
            return None
        try:
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "merge-tree",
                    "--write-tree",
                    "--name-only",
                    "HEAD",
                    branch,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if res.returncode == 0:
            # 零冲突：放行现行真合并流程（逐字节不变）
            return None
        conflict_paths = self._parse_merge_tree_conflict_paths(res.stdout)
        if not conflict_paths:
            return None
        # 分类复用产物路径判定器实例（evo-merge-back-wip-artifact-scope D3）：
        # 非产物路径全部为被忽略的 DU 运行时草稿时才放行，其余视为语义冲突
        # 直通 repair。
        non_artifact = self._artifacts.non_artifacts_in(conflict_paths)
        if not non_artifact:
            return None
        if all(self._rehearsed_path_is_ignored_du(p) for p in non_artifact):
            return None
        # 语义冲突：主树零污染直通 repair。冲突清单只保留语义路径（与 abort 后
        # 分类一致——产物路径由框架自愈负责，不污染 repair agent 的冲突上下文）。
        self.logger.info(
            "worktree_manager",
            f"Merge rehearsal detected semantic conflicts for branch '{branch}': "
            f"{len(non_artifact)} path(s) {non_artifact} (total {len(conflict_paths)})"
            f" — direct to repair lane, main tree untouched",
        )
        return MergeConflictInfo(
            False,
            f"Semantic merge conflicts detected by pre-merge rehearsal "
            f"({len(non_artifact)} path(s))",
            conflict_paths=non_artifact,
            self_heal_applicable=False,
            has_semantic_conflict=True,
            rehearsed=True,
        )

    def _parse_merge_tree_conflict_paths(self, stdout: str) -> list:
        """解析 ``merge-tree --write-tree --name-only`` 输出中的冲突路径清单。

        冲突时输出结构：首行为结果 tree oid，其后冲突路径每行一个，空行后为
        信息行（Auto-merging / CONFLICT ...）。rename 双胞胎的 base 旧路径与
        两侧新路径都会列出——与 ``_collect_conflict_paths``（git status --porcelain
        的 rename ``old -> new`` 双胞胎两侧都计入）口径一致。
        """
        paths: list = []
        for line in stdout.splitlines()[1:]:
            if not line.strip():
                break
            if line.startswith("CONFLICT"):
                break
            paths.append(line.strip())
        return [p for p in paths if p]

    def _rehearsed_path_is_ignored_du(self, path: str) -> bool:
        """预演分类：非产物冲突路径是否为「被 .gitignore 忽略的运行时草稿」。

        与 abort 后 ``_resolve_ignored_modify_delete_conflicts``（仅处理 DU——
        主树删除、分支修改）口径一致：主树已删除该路径时它在 HEAD 索引中不
        存在，``git check-ignore`` 判定可靠；反向（分支删除、主树修改）路径仍
        tracked → check-ignore 返回非零 → 判为语义冲突直通，真合并中该自愈
        （仅接受 DU 状态码）同样不适用。命令失败保守返回 False。
        """
        try:
            chk = subprocess.run(
                ["git", "-C", str(self.project_root), "check-ignore", "-q", "--", path],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return chk.returncode == 0

    def _merge_back_from_branch_locked(self, branch: str) -> MergeConflictInfo:
        """merge_back_from_branch 的实现体，调用方必须已持有 _main_tree_lock。

        Returns: ``MergeConflictInfo``——兼容 ``(bool, str)`` 解包，额外携带
        冲突路径清单与语义冲突分类（add-merge-back-repair-lane D1，供调度层
        决定是否进入 repair 通道）。
        """
        backup = None  # TimeoutExpired 早于备份创建时 except 分支的兜底初值
        try:
            # Idempotency check: is branch already an ancestor of HEAD?
            ancestor = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "merge-base",
                    "--is-ancestor",
                    branch,
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if ancestor.returncode == 0:
                self.logger.info(
                    "worktree_manager",
                    f"Branch '{branch}' already merged — skipping merge-back",
                )
                return MergeConflictInfo(True, "already merged")

            # WIP 塌缩（add-impl-wip-checkpoint D4）：merge-back 前把分支上的
            # ``fenix(wip):`` 前缀提交塌缩为单提交——主树历史零 WIP 污染。
            # 无 WIP 提交时零动作（常规成功路径逐字节现行行为）；失败仅
            # WARNING 降级，merge-back 以未塌缩分支继续（D6）。塌缩是分支
            # 引用级 soft-reset 语义操作，文件内容逐字节不变。
            collapse_wip_commits(self.project_root, branch, self.logger)

            # merge 前按 implementer 分支新增路径，把主树中冲突的 untracked 文件移开
            # （Layer 2 兜底，fix-merge-untracked-guard 泛化）：即使 spec 未被
            # ensure_spec_committed 提交、或产物路径有污染，也不让 merge 因 untracked 冲突死锁。
            backup = self._backup_untracked_spec_files(branch)
            head_before = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()

            # Merge with --no-ff to preserve worktree history
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "merge",
                    "--no-ff",
                    branch,
                    "-m",
                    f"[fenix] merge implementer branch {branch}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                error = (
                    result.stderr.strip()
                    or result.stdout.strip()
                    or f"exit code {result.returncode}"
                )
                # DRY 自愈（fix-merge-dirty-ignored-draft）：主树被 ignore 的 tracked
                # 运行时草稿带未提交修改、而 merge 需写该路径时，git 直接拒绝且不进入
                # 冲突态（_resolve_ignored_modify_delete_conflicts 覆盖不到）。移出后重试。
                blockers = self._parse_merge_blockers(error)
                if blockers and self._untrack_ignored_local_changes(blockers):
                    result = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.project_root),
                            "merge",
                            "--no-ff",
                            branch,
                            "-m",
                            f"[fenix] merge implementer branch {branch}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                elif blockers and self._discard_identical_local_changes(blockers, branch):
                    result = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.project_root),
                            "merge",
                            "--no-ff",
                            branch,
                            "-m",
                            f"[fenix] merge implementer branch {branch}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
            if result.returncode == 0:
                self._drop_backup(backup)
                # merge 成功后把随分支带回 tracked 的 ignored 草稿移出（防撞车循环重启）
                if head_before:
                    self._purge_ignored_brought_in(head_before)
                # dist 冲突根治 B：触碰 static src 的 merge 从合并后 src 重建 dist
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merged branch '{branch}' into main tree",
                )
                return MergeConflictInfo(True, "")

            error = (
                result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            )
            self.logger.error(
                "worktree_manager",
                f"Merge failed for branch '{branch}': {error}",
            )
            # 构建产物冲突自愈（add-v3-spec-quick-switch / add-project-description
            # 事故治理）：实现分支各自重建 dist，内容哈希文件名跨分支必然
            # rename/delete 打架——这不是语义冲突。全部冲突路径位于构建产物目录时，
            # dist 整目录对齐实现分支版本（含本 spec 功能构建）并完成 merge；
            # dist 与合并后 src 的最终一致性由后续"merge 后从 src 重建"刷新。
            # 先于 ignored-DU 自愈跑：其判定为只读收集、解决精确（含产物 DU），
            # 而 ignored 自愈会先 rm --cached 改变冲突态、校验失败时 abort 整个
            # merge——若它先行，产物 DU 场景轮不到本自愈（add-dashboard-
            # incremental-data 目录重命名事故根因之二）。
            if self._resolve_build_artifact_conflicts(branch):
                self._drop_backup(backup)
                # dist 冲突根治 B：自愈 merge 同样从合并后 src 重建收口
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merge conflict self-healed (build artifacts aligned to "
                    f"branch) for branch '{branch}'",
                )
                return MergeConflictInfo(
                    True,
                    "",
                    self_heal_applicable=True,
                    self_heal_succeeded=True,
                )
            # merge 冲突自愈（fix-merge-modify-delete-ignored）：modify/delete 冲突
            # 且全部冲突路径都是 .gitignore 忽略的运行时草稿时，采纳主树侧的删除。
            # 场景：run-result 类草稿在移出版本控制前派生的旧分支上被改动，与主树的
            # 删除相撞——被忽略的草稿不是交付物，不应让 merge-back 死锁。
            if self._resolve_ignored_modify_delete_conflicts():
                self._drop_backup(backup)
                # dist 冲突根治 B：该路径同样可能并入 static src 变更
                self._rebuild_dist_after_merge()
                self.logger.info(
                    "worktree_manager",
                    f"Merge conflict self-healed (modify/delete on ignored files) "
                    f"for branch '{branch}'",
                )
                return MergeConflictInfo(
                    True,
                    "",
                    self_heal_applicable=True,
                    self_heal_succeeded=True,
                )
            # ── 语义冲突分类收集（add-merge-back-repair-lane D1）────────────
            # 两级自愈均不适用（冲突含非产物语义文件）时，在 abort **之前**采集
            # unmerged 冲突路径清单，并判定是否仍含语义冲突。返回的
            # MergeConflictInfo 携带结构化分类，供调度层决定是否进入 repair 通道；
            # 主树 abort 后保持干净（merge --abort 本身幂等，重复 abort 无害）。
            conflict_paths = self._collect_conflict_paths()
            self_heal_applicable = bool(conflict_paths) and all(
                self._artifacts.is_artifact(p) for p in conflict_paths
            )
            has_semantic_conflict = any(
                not self._artifacts.is_artifact(p) for p in conflict_paths
            )
            if conflict_paths:
                self.logger.warning(
                    "worktree_manager",
                    f"Merge conflict not self-healable for branch '{branch}': "
                    f"{len(conflict_paths)} path(s), "
                    f"semantic={has_semantic_conflict} — collecting for repair decision",
                )
            # Abort the merge so main tree is left clean for retry
            subprocess.run(
                ["git", "-C", str(self.project_root), "merge", "--abort"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # 恢复被移开的 untracked 文件（不丢数据，供下一轮重试）
            self._restore_backup(backup)
            return MergeConflictInfo(
                False,
                error,
                conflict_paths=conflict_paths,
                self_heal_applicable=self_heal_applicable,
                has_semantic_conflict=has_semantic_conflict,
            )

        except subprocess.TimeoutExpired:
            # 超时收口（code-review item 80e2f0795662，与既有失败路径对齐）：
            # merge 子进程被杀后索引/工作区可能停在半合并（unmerged）态——不
            # abort 会让后续 restore_after_merge 的 stash pop 失败或告警失真；
            # 已移开的 untracked 备份也不归还，会在 .fenix/merge-backup 下无限
            # 期残留。abort 幂等（无合并进行时静默失败），自身异常不再外抛。
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "merge", "--abort"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception:  # noqa: BLE001 — abort 失败不掩盖原始超时错误
                pass
            if backup is not None:
                self._restore_backup(backup)
            return MergeConflictInfo(False, "git merge timed out after 120s")
        except Exception as e:
            return MergeConflictInfo(False, str(e))

    def _backup_untracked_spec_files(self, branch: str):
        """merge 前把与 implementer 分支新增路径冲突的主树 untracked 文件移到 .fenix/merge-backup/ 备份。

        泛化原 spec/changes 限定逻辑（fix-merge-untracked-guard）：

        1. `git diff --name-only --diff-filter=A HEAD...<branch>` 取分支**新增**文件路径集合
           —— untracked 冲突只会发生在新增路径上（修改既有 tracked 文件不与 untracked 冲突）。
        2. 对每条新增路径，判断主树中该路径上的文件是否为 untracked：
           `git ls-files --error-unmatch <path>` 失败（未被 index 跟踪）即视为 untracked。
        3. 将命中的文件移入 `.fenix/merge-backup/<epoch秒>/`（保持仓库相对路径结构）。

        检测范围不限于 spec/changes/，覆盖任意产物路径（如 core/dashboard/static/v2/）。
        集合为空、或交集为空时返回 None 且不创建备份目录（零开销跳过）。

        返回备份目录路径（无冲突文件时返回 None）。merge 成功后调用 _drop_backup
        决定备份去留；merge 失败调用 _restore_backup 移回（不丢数据）。
        """
        try:
            added = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--name-only",
                    "--diff-filter=A",
                    f"HEAD...{branch}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return None
        if added.returncode != 0:
            return None
        added_paths = [ln.strip() for ln in added.stdout.splitlines() if ln.strip()]
        if not added_paths:
            return None

        # 逐路径判断：主树中存在该路径、且未被 index 跟踪（untracked）才纳入备份。
        rels = []
        for rel in added_paths:
            src = self.project_root / rel
            if not src.exists():
                continue
            ls = subprocess.run(
                ["git", "-C", str(self.project_root), "ls-files", "--error-unmatch", "--", rel],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if ls.returncode != 0:  # 0 = tracked；非 0 = untracked（含 ignored 以外）
                rels.append(rel)

        if not rels:
            return None

        backup = self.project_root / ".fenix" / "merge-backup" / str(int(time.time()))
        for rel in rels:
            src = self.project_root / rel
            dst = backup / rel
            if not src.exists():
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError:
                continue
        return backup

    def _drop_backup(self, backup) -> None:
        """merge 成功后按字节一致性决定备份去留（fix-merge-untracked-guard D3）。

        - 备份中每个文件与 merge 后 HEAD 中同路径文件字节级一致 → 删除备份目录（现状语义）
        - 存在不一致文件 → 保留备份目录不删，写 logger.warning 列出不一致路径与备份位置，
          防止主树上的有价值改动被分支版本静默覆盖后丢失

        孤儿空父目录一并清理。
        """
        if backup is None:
            return
        if not backup.is_dir():
            return

        # 字节级比对：读文件 bytes 相等即可，无需 git 命令。
        inconsistent = []
        for p in list(backup.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(backup)
            head_file = self.project_root / rel
            try:
                if not head_file.exists():
                    inconsistent.append(str(rel))
                    continue
                with open(p, "rb") as src_f, open(head_file, "rb") as head_f:
                    if src_f.read() != head_f.read():
                        inconsistent.append(str(rel))
            except OSError:
                # 读取失败：保守视为不一致，保留备份由人工裁决
                inconsistent.append(str(rel))

        if inconsistent:
            self.logger.warning(
                "worktree_manager",
                f"merge-back 后主树副本与合入版本字节级不一致，保留备份不删除："
                f"backup='{backup}'，不一致路径={inconsistent}",
            )
            return  # 保留备份目录，供人工决策

        try:
            shutil.rmtree(str(backup))
            parent = backup.parent
            if parent.exists():
                parent.rmdir()  # 空父目录一并清理；非空时抛 OSError 忽略
        except OSError:
            pass

    def _restore_backup(self, backup) -> None:
        """merge 失败后把备份文件移回原位，并移除空备份目录（不丢数据，供下一轮重试）。"""
        if backup is None or not backup.is_dir():
            return
        for p in backup.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(backup)
            dst = self.project_root / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dst))
            except OSError:
                continue
        # 移回后清空并移除备份目录（含残留空父目录）
        try:
            shutil.rmtree(str(backup))
            parent = backup.parent
            if parent.exists():
                parent.rmdir()  # 空父目录一并清理；非空时抛 OSError 忽略
        except OSError:
            pass
