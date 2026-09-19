"""adjudication.py — V 交付物裁定/dispute（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 9 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。组内自洽度最高——本组方法互调均在
组内经宿主实例 `self.<method>` 协作，跨组件/门面访问一律经
`self._pm.<method>`（design D3 规则 3 私有点名回引）。

D3 patch 缝隙：本组使用 `time` 模块（`_adjudicate_deliverable_missing`
组 judge run id），经模块顶部导入——测试 patch time 模块对象属性全进程
共享，重绑依旧生效。
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class VAdjudicationMixin:
    """V 交付物裁定/dispute（design D1 表 B V 组）。"""

    def _effective_declaration(self, spec_name: str, result=None) -> dict:
        """经统一解析入口取「生效声明」（add-declaration-relocation-protocol D1）。

        与收工守卫同源（worktree 内文件 > ``git show <branch>`` > 主树回退），
        供预分类/裁决/语境摘录共用——MUST NOT 自行拼接主树 spec 目录直读
        （读分支、写主树的错层正是本次事故根因）。``result`` 提供分支/worktree
        上下文（可选；缺失时按主树回退语义解析）。

        Returns:
            ``resolve_effective_declaration`` 同构 dict（含 deliverables/
            references/entries/source/spec_dir）。
        """
        from core.deliverables import resolve_effective_declaration

        branch = getattr(result, "branch", None) if result is not None else None
        worktree_path = None
        if branch:
            try:
                worktree_path = self._pm.agent_runner.worktree_manager.find_worktree_path(
                    branch
                )
            except Exception:
                worktree_path = None
        return resolve_effective_declaration(
            spec_name,
            branch=branch,
            worktree_path=worktree_path,
            project_root=self._pm.project_root,
        )

    def _record_impl_diagnosis(
        self, spec_name: str, result, impl_result, final_error: str | None
    ) -> None:
        """run 终结时写入 spec 级结构化诊断字段 ``_impl_diagnosis``。

        fix-run-hang-amplification 2.3：诊断摘要 = 终态类型 + 归因 + 已定性
        结论 + 已提交进度（分支 + 已勾选任务数）。重派 attempt 经
        PromptBuilder 注入该字段，使新 run 继承上一轮结论而非从零再探测。

        结构（存 JSON 字符串，STATE.md 行内可往返解析）：
        {"terminal": "...", "attribution": "...", "conclusion": "...",
         "progress": {"branch": "...", "tasks_checked": n}}。

        任何无法分类/读取失败时字段落最小可用值，不抛异常（诊断是附加物）。
        """
        terminal = "error"
        if getattr(result, "cancelled", False):
            terminal = "cancelled"
        elif final_error:
            low = str(final_error).lower()
            if "timeout after" in low and "extension budget exhausted" in low:
                terminal = "timeout_budget_exhausted"
            elif "stagnant" in low:
                terminal = "stagnant"
            elif "interrupted" in low:
                terminal = "interrupted"
            else:
                terminal = "error"
        elif impl_status_success := bool(impl_result and impl_result.get("status") == "success"):
            terminal = "result"
        elif (impl_result or {}).get("status") == "partial":
            # fix-impl-tasks-completion-gate D6：partial 是诚实申报未完成的合法
            # 终态——诊断终态单列 partial，不落入默认 error 也不落入 result。
            terminal = "partial"
        conclusion = ""
        if impl_result:
            try:
                summary = impl_result.get("summary")
                if isinstance(summary, str) and summary.strip():
                    conclusion = summary.strip()[:500]
            except Exception:
                conclusion = ""
        branch = getattr(result, "branch", None) or None
        tasks_checked = None
        # 已提交进度：从主树 spec 目录 tasks.md 数已勾选任务（_sync_task_progress
        # 在成功路径已把 worktree 勾选同步回主树，失败路径读主树现状即可）。
        try:
            spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
            tasks_path = spec_dir / "tasks.md"
            if tasks_path.is_file():
                tasks_checked = sum(
                    1
                    for line in tasks_path.read_text(encoding="utf-8").splitlines()
                    if line.strip().startswith("- [x]")
                )
        except Exception:
            tasks_checked = None
        diagnosis = {
            "terminal": terminal,
            "attribution": str(final_error or "")[:500],
            "conclusion": conclusion,
            "progress": {
                "branch": branch,
                "tasks_checked": tasks_checked,
            },
        }
        self._pm.state_machine.update_spec(
            spec_name, {"_impl_diagnosis": json.dumps(diagnosis, ensure_ascii=False)}
        )
        self._pm.logger.info(
            "pm_engine",
            f"实现诊断已记录 '{spec_name}': terminal={terminal}, "
            f"branch={branch}, tasks_checked={tasks_checked}",
        )

    # ── 缺件 LLM 终审与裁决机械执行（add-deliverable-declaration-triage D3/D4）──

    def _build_dispute_judge_input(
        self, spec_name: str, impl_result, missing: list, kind_by_path: "dict | None" = None
    ) -> dict:
        """组装 dispute-judge 输入（4.1/4.5）：缺件 + kind + basename 候选 + 语境。

        ``missing`` 兼容两种形态：路径列表（``list[str]``）或守卫返回的
        结构化条目（``list[dict]``，每项含 ``path``/``kind``/``violation``）。
        ``kind_by_path`` 可选：声明段 path→kind 映射，供 judge 看到「该路径应被
        删除」而非仅看到缺件路径（add-deliverable-delete-kind 4.5）——条目级
        kind 优先于映射，映射优先于默认 ``"new"``。

        Returns:
            dict：``{"spec", "missing": [{"path", "kind", "candidates"}],
            "spec_context": {"excerpts", "declared_entries"},
            "findings": [...]}``。任一部件读取失败静默降级（fail-open）。
        """
        from core.deliverables import match_basename_in_tree

        missing_entries = []
        for m in missing:
            if isinstance(m, dict):
                m_path = str(m.get("path") or "")
                m_kind = str(m.get("kind") or "")
            else:
                m_path = str(m)
                m_kind = ""
            if not m_path:
                continue
            candidates = []
            try:
                candidates = match_basename_in_tree(self._pm.project_root, m_path)
            except Exception:
                candidates = []
            if not m_kind and kind_by_path:
                m_kind = kind_by_path.get(m_path, "new")
            missing_entries.append(
                {
                    "path": m_path,
                    "kind": m_kind or "new",
                    "candidates": candidates,
                }
            )

        findings = []
        if isinstance(impl_result, dict):
            findings = impl_result.get("findings") or []

        return {
            "spec": spec_name,
            "missing": missing_entries,
            "spec_context": self._dispute_spec_context(
                spec_name, [m["path"] for m in missing_entries]
            ),
            "findings": findings,
        }

    def _dispute_spec_context(self, spec_name: str, missing: list) -> dict:
        """spec 三文档语境摘录：含缺件路径的段落 + Deliverables 声明段全文。

        对 proposal.md/design.md/tasks.md/specs/*.md：以缺件路径为关键词抽取
        命中行 ±2 行上下文（每文档独立段落清单）；tasks.md 的声明段经
        ``extract_declared_entries`` 结构化摘录。读取失败静默跳过（fail-open）。
        """
        import re as _re
        from pathlib import Path as _Path

        spec_dir = _Path(self._pm.project_root) / "spec" / "changes" / spec_name
        docs = {}
        for name in ("proposal.md", "design.md", "tasks.md"):
            p = spec_dir / name
            if p.is_file():
                try:
                    docs[name] = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    pass
        specs_dir = spec_dir / "specs"
        if specs_dir.is_dir():
            try:
                for f in sorted(specs_dir.rglob("*.md")):
                    if f.is_file():
                        docs[f.name] = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

        excerpts = {}
        for name, text in docs.items():
            lines = text.splitlines()
            hits: list = []
            for i, line in enumerate(lines):
                if any(m in line for m in missing):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    block = "\n".join(lines[start:end])
                    if block not in hits:
                        hits.append(block)
            if hits:
                excerpts[name] = hits

        context: dict = {"excerpts": excerpts}
        try:
            # 声明段条目经统一解析入口取（add-declaration-relocation-protocol
            # D1：worktree/分支版本优先、主树回退），与收工守卫同源——MUST NOT
            # 自行拼接主树 spec 目录直读（读分支、写主树的错层正是本次事故根因）。
            resolved = self._effective_declaration(spec_name)
            if resolved.get("entries"):
                context["declared_entries"] = resolved["entries"]
        except Exception:
            pass
        return context

    def _read_dispute_verdicts(
        self, spec_name: str, judge_run_id: str, judge_result
    ) -> "dict | None":
        """读取 dispute-judge 裁决 JSON（4.2 结果消费）。

        判据：run 未成功收工 / 结果文件缺失或 JSON 不合法 / 顶层 status 非
        success / verdicts 缺失或非列表 → 返回 None（调用方等价 ``unclear``，
        全部待裁缺件转人工）。

        Returns:
            合法裁决 JSON dict 或 None。
        """
        result_path = (
            self._pm.project_root
            / ".fenix"
            / "verify-progress"
            / spec_name
            / "dispute_judge_result.json"
        )
        if judge_result is None or not getattr(judge_result, "success", False):
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge run 失败 '{spec_name}'（等价 unclear）: "
                f"{getattr(judge_result, 'error', '') or ''}",
            )
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 JSON 不合法 '{spec_name}'（等价 unclear）",
            )
            return None
        if not isinstance(data, dict) or data.get("status") != "success":
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 status 非 success '{spec_name}'（等价 unclear）",
            )
            return None
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, list) or not verdicts:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果缺 verdicts '{spec_name}'（等价 unclear）",
            )
            return None
        return data

    def _commit_softened_declaration(self, spec_name: str, element: str) -> None:
        """软化/修正声明段后立即提交 tasks.md（fix-merge-back-deadlock 同类修复）。

        ``soften_declared_kind`` / ``replace_declared_path`` 直接改写主树
        ``spec/changes/<spec>/tasks.md`` 但不提交，使 merge-back 陷入死锁：
        ``ensure_clean_tree`` 的 autostash 显式 ``:(exclude)spec/changes``
        （fix-comment：spec 文件是框架运行必需，不得被卷走），于是该文件永远
        以 dirty 状态进 merge，而实现分支同样改了该文件 → git 拒绝
        「Your local changes to the following files would be overwritten by
        merge」→ 合并永久失败（2026-09-15 事故：dispute judge 软化
        ``data/_legacy.py → reference`` 后 merge-back 失败，spec 被 merge
        指纹熔断冻结 blocked）。

        提交动作与软化写盘同事务语义：软化已写盘、此处立即固化，主树恢复
        干净 → 下一次 merge-back 的 autostash 不再命中该文件。提交失败仅
        WARNING（软化内容仍在工作区，不静默丢失；下一次派发前的
        ``ensure_spec_committed`` 会兜底提交）。
        """
        rel = f"spec/changes/{spec_name}/tasks.md"
        try:
            ok, err = self._pm._git_commit([rel], f"[fenix] {spec_name}: 声明段修正（{element}）")
            if ok:
                self._pm.logger.info(
                    "pm_engine",
                    f"声明段软化已提交 '{spec_name}': {element}",
                )
            else:
                self._pm.logger.warning(
                    "pm_engine",
                    f"声明段软化提交失败 '{spec_name}'（{element}，非阻塞，"
                    f"派发前 ensure_spec_committed 兜底）: {err}",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"声明段软化提交异常 '{spec_name}'（{element}，非阻塞）: {e}",
            )

    def _preclassify_missing(self, spec_name: str, result, missing: list) -> dict:
        """守卫缺件确定性预分类（add-declaration-premechanize D4，Task 4.1-4.3）。

        在组装 judge 输入之前，对缺件清单做确定性分类：命中不可交付模式
        （gitignored / 仓库外）的条目直接机械软化 + 审计 + 重跑守卫；全清走
        放行分支且不派 judge run；剩余项才进入 dispute-judge。

        预分类异常全量回退既有 judge 流程（fail-open：不因解析/软化异常阻塞
        终审）。

        Returns:
            {"action": "proceed"} → 全部缺件已确定性软化，守卫重跑通过；
            {"action": "continue", "remaining": [...]} → 仍有剩余，带入 judge；
            {"action": "fallback"} → 预分类不可用，回退既有 judge 流程
            （missing 不变）。
        """
        from core.deliverables import classify_unsatisfiable

        # 声明段条目经统一解析入口取（add-declaration-relocation-protocol D1：
        # worktree/分支版本优先、主树回退，与收工守卫同源）——MUST NOT 自行拼接
        # 主树 spec 目录直读（读分支、写主树的错层正是本次事故根因）。
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        # 声明段无条目（存量 spec 正则提取 / 两处均不可用）→ 不预分类，回退 judge
        if not entries:
            return {"action": "fallback"}

        # 软化执行目标 = 生效声明所在位置（worktree 内 → 分支 → 主树回退）
        spec_dir = resolved.get("spec_dir")
        if not spec_dir:
            spec_dir = self._pm.project_root / "spec" / "changes" / spec_name

        # 快照软化前 tasks.md 声明段（供审计 diff.before）
        before_text = ""
        tasks_path = Path(spec_dir) / "tasks.md"
        if tasks_path.exists():
            try:
                before_text = tasks_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                before_text = ""

        # 将条目列表转为 path → entry 映射（按 path 查找）
        entry_by_path: dict = {}
        for e in entries:
            if isinstance(e, dict) and e.get("path"):
                entry_by_path[e["path"]] = e

        # 缺件入参兼容两种形态：守卫返回 list[dict]（path/kind/violation）与
        # 既有调用/测试的 list[str]。统一规范化为路径列表（匹配逻辑只认路径）。
        missing_paths = [m["path"] if isinstance(m, dict) else str(m) for m in missing]

        # 分类：确定性命中 → deterministic；声明段无该条目或不命中 → 留在 remaining
        deterministic: list = []
        remaining: list = []
        for m in missing_paths:
            entry = entry_by_path.get(m)
            # add-deliverable-delete-kind D4：kind: delete 条目 MUST NOT 参与软化
            # （classify_unsatisfiable 已恒 False，此处显式排除 + 审计留痕防将来
            # 新增软化路径时无声破防）；delete 条目保留在待处置清单进入后继流程。
            if entry and entry.get("kind") == "delete":
                remaining.append(m)
                continue
            if entry and classify_unsatisfiable(entry, self._pm.project_root):
                deterministic.append(m)
            else:
                remaining.append(m)

        if not deterministic:
            # 无可软化缺件 → 回退 judge 流程（remaining == missing）
            return {"action": "fallback"}

        # 逐条软化（单条异常留在 remaining 并 warning）
        diff_by_element: dict = {}
        for m in deterministic[:]:  # copy以便异常时移除
            entry = entry_by_path[m]
            try:
                from core.deliverables import soften_declared_kind

                diff = soften_declared_kind(spec_dir, m)
                diff_by_element[m] = diff
                self._commit_softened_declaration(spec_name, m)
            except Exception as exc:
                # 单条软化异常：留在 remaining 清单（异常不阻塞其余）
                remaining.append(m)
                deterministic.remove(m)
                self._pm.logger.warning(
                    "pm_engine",
                    f"预分类软化异常 '{spec_name}'（{m} 回退 judge）: {exc}",
                )

        if not deterministic:
            # 全部软化异常 → 回退 judge
            return {"action": "fallback"}

        # 审计留痕（reasoning 前缀 guard-preclassify）
        try:
            from core.admin_store import DisputeAuditStore

            # after 已是软化后文本（soften_declared_kind 已写盘）
            after_text = ""
            if tasks_path.exists():
                after_text = tasks_path.read_text(encoding="utf-8")
            DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                {
                    "spec": spec_name,
                    "trigger_run_id": "",
                    "judge_run_id": "",
                    "verdicts": [
                        {
                            "element": m,
                            "verdict": "reference",
                            "reasoning": "guard-preclassify: gitignored/outside-root",
                        }
                        for m in deterministic
                    ],
                    "diff": {
                        "before": before_text,
                        "after": after_text,
                    },
                }
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"预分类审计写盘失败 '{spec_name}'（非阻塞）: {e}",
            )

        # 重跑守卫对账
        try:
            gate_result = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"预分类后守卫重跑异常 '{spec_name}'（回退 judge）: {e}",
            )
            # 异常回退：把已软化条目放回 remaining（soften 已写盘，无法回滚）
            remaining.extend(deterministic)
            return {"action": "fallback"}

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支
            self._pm.logger.warning(
                "pm_engine",
                f"预分类缺件全清 '{spec_name}' — 守卫重跑通过，放行 merge",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "implementing",
                    "error": None,
                },
            )
            return {"action": "proceed"}

        # 仍有剩余 → remaining 带入 judge
        return {"action": "continue", "remaining": remaining}

    # ── 孤儿声明机械预分类（deliverable-dispute-orphan-preclassify）────────

    def _preclassify_orphan(
        self, spec_name: str, result, impl_result, disputed: list, missing: list
    ) -> dict:
        """缺件异议分支内的孤儿声明机械预分类（design「机械预分类在裁决链
        中的位置」）。

        实现 run 对缺件提出 deliverable-dispute 异议（blocked 待人工）之前，
        先跑按 kind 分化的孤儿判定（``is_orphan_declaration``，规则 1 源码面
        git grep 零引用 / 规则 2 历史仅 modify / 规则 3 任务清单零出现）：
        判为孤儿（声明残留）→ 机械删除声明 + 审计 + 重跑守卫对账，不 blocked；
        非孤儿 → 维持 blocked 待人工（宁可多走人工，不误删真实交付物）。
        kind: delete 不参与预分类（防洗白，一律进人工裁决）。

        删除后的续走契约 MUST 与 ``_preclassify_missing``（本模块 295 行）的
        proceed 分支逐条对齐（design「删除后的续走契约」节）：

        1. 删声明：改写 tasks.md 声明段（只删该条的 path+kind 两行），留
           .history 备份（对齐 admin 处置 .history 备份惯例）；
        2. **立即提交**改写的 tasks.md（同 ``_commit_softened_declaration``，
           fix-merge-back-deadlock 教训：主树 spec 文件被 merge-back 的
           autostash 显式排除，残留 dirty 会让「主树改了 tasks.md + 实现分支
           也改了 tasks.md」的 merge 被 git 拒绝 → spec 被 merge 指纹熔断冻结
           blocked）。提交失败仅 WARNING（派发前 ensure_spec_committed 兜底）；
        3. 重跑守卫对账：删除后以重跑 ``_deliverable_gate_missing(spec_name,
           result)`` 的结果替换 ``missing``；全清 → ``status=implementing`` +
           ``error=None`` + ``{"action": "proceed"}``（对齐 ``_preclassify_missing``
           全清分支），放行 merge；
        4. 仍有缺件：把重跑后的 remaining 作为新的 ``missing`` 续走既有后续
           代码（剩余项仍带 dispute 异议 → 调用方 blocked 待人工；无异议项 →
           既有 ``_adjudicate_deliverable_missing`` LLM 终审），不得因「已判过
           一批孤儿」就整段跳过；
        5. 任一环节异常 → 全量回退既有 blocked 待人工路径（fail-open，不因
           预分类故障改变处置）。

        Returns:
            {"action": "proceed"} → 全部孤儿声明已删除，守卫重跑通过（调用方
            继续 merge 推进）；
            {"action": "continue", "remaining_missing": [...], "remaining_disputed": [...]}
            → 仍有缺件：remaining_missing 为守卫重跑后的缺件清单（调用方续走
            既有后续，remaining_disputed 为其中仍带异议的项，非空则 blocked
            待人工）；
            {"action": "fallback"} → 判定/改写/提交任一环节异常，全量回退既有
            blocked 待人工路径（missing 不变，disputed 全量仍待人工）。
        """
        from core.deliverables import is_orphan_declaration, remove_declared_entry

        # 声明段条目经统一解析入口取（add-declaration-relocation-protocol D1：
        # worktree/分支版本优先、主树回退）——MUST NOT 自行拼接主树 spec 目录
        # 直读（读分支、写主树的错层正是 refactor-giant-classes 事故根因）。
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        spec_dir = resolved.get("spec_dir")
        if not entries:
            # 声明段无条目 → 无声明可删，回退 blocked 待人工
            return {"action": "fallback"}
        if not spec_dir:
            spec_dir = self._pm.project_root / "spec" / "changes" / spec_name

        # 缺件入参兼容 list[dict]（path/kind/violation）与 list[str]
        missing_paths = [m["path"] if isinstance(m, dict) else str(m) for m in missing]
        entry_by_path: dict = {}
        for e in entries:
            if isinstance(e, dict) and e.get("path"):
                entry_by_path[e["path"]] = e

        # 逐条孤儿判定（单条判定异常 → 保留 disputed 走人工，不整段跳过）
        orphans: list = []
        non_orphans: list = []
        for d in disputed:
            entry = entry_by_path.get(d)
            if entry is None:
                # 声明段无该条目（缺件来自正则回退/基线）→ 无从删除，保留人工
                non_orphans.append(d)
                continue
            try:
                oc = is_orphan_declaration(
                    self._pm.project_root, spec_name, entry, spec_dir
                )
            except Exception as exc:
                # 判定异常 → fail-open：该条维持 blocked 待人工
                non_orphans.append(d)
                self._pm.logger.warning(
                    "pm_engine",
                    f"孤儿判定异常 '{spec_name}'（{d} 保留人工）: {exc}",
                )
                continue
            if oc.get("orphan"):
                orphans.append(d)
            else:
                non_orphans.append(d)

        if not orphans:
            # 无孤儿可删 → 全量维持 blocked 待人工（非孤儿/判定异常）
            return {"action": "fallback"}

        # 快照删除前 tasks.md 声明段（供审计 diff.before）
        before_text = ""
        tasks_path = Path(spec_dir) / "tasks.md"
        if tasks_path.exists():
            try:
                before_text = tasks_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                before_text = ""

        # 1. 逐条删声明 + 留 .history 备份 + 立即提交
        diff_by_element: dict = {}
        deleted: list = []
        for m in orphans[:]:  # copy 以便异常时移除
            try:
                # .history 备份（对齐 admin 处置备份惯例）：备份文件不可写/
                # 目录异常不阻塞删除本身（备份是附加留痕，fail-open）。
                self._backup_to_history(spec_name, m, before_text)
                diff = remove_declared_entry(spec_dir, m)
                diff_by_element[m] = diff
                self._commit_softened_declaration(spec_name, m)
                deleted.append(m)
            except Exception as exc:
                # 单条删除异常：保留 disputed 走人工（异常不阻塞其余，也不整段
                # 跳过后续——本 spec 语境下最接近 fail-open 的处置）
                non_orphans.append(m)
                orphans.remove(m)
                self._pm.logger.warning(
                    "pm_engine",
                    f"孤儿声明删除异常 '{spec_name}'（{m} 保留人工）: {exc}",
                )

        if not deleted:
            # 全部删除异常 → 全量回退 blocked 待人工
            return {"action": "fallback"}

        # 2/3. 审计留痕（reasoning 前缀 orphan-preclassify，judge_run_id 空串）
        try:
            from core.admin_store import DisputeAuditStore

            after_text = ""
            if tasks_path.exists():
                after_text = tasks_path.read_text(encoding="utf-8")
            DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                {
                    "spec": spec_name,
                    "trigger_run_id": "",
                    "judge_run_id": "",
                    "verdicts": [
                        {
                            "element": m,
                            "verdict": "orphan-preclassify",
                            "reasoning": (
                                "orphan-preclassify: 源码面 git grep 零引用 "
                                "+ 任务清单（全路径与 basename 皆）零出现，"
                                "声明残留，机械删除声明条目"
                            ),
                        }
                        for m in deleted
                    ],
                    "diff": {
                        "before": before_text,
                        "after": after_text,
                    },
                }
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿预分类审计写盘失败 '{spec_name}'（非阻塞）: {e}",
            )

        # 4. 重跑守卫对账：以重跑结果替换 missing
        try:
            gate_result = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"孤儿删除后守卫重跑异常 '{spec_name}'（回退 blocked）: {e}",
            )
            # 异常回退：声明已删除无法回滚，但处置维持 blocked 待人工
            # （fail-open 不改既有处置：剩余缺件全部按未预分类处理）
            return {"action": "fallback"}

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支（对齐 _preclassify_missing）
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿声明删除全清 '{spec_name}' — 守卫重跑通过，放行 merge",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "implementing",
                    "error": None,
                },
            )
            return {"action": "proceed"}

        # 仍有缺件 → 以重跑后的 remaining 续走既有后续（remaining_disputed 供
        # 调用方判断 blocked vs LLM 终审；非孤儿 disputed 项同样计入）
        remaining_paths = [g["path"] if isinstance(g, dict) else str(g) for g in gate_result]
        remaining_disputed = [r for r in remaining_paths if r in (disputed + non_orphans)]
        return {
            "action": "continue",
            "remaining_missing": gate_result,
            "remaining_disputed": remaining_disputed,
        }

    # ── 漂移笔误机械对齐（evo-deliverable-declaration-drift-align D1/D2）────────

    def _preclassify_drift(
        self, spec_name: str, result, impl_result, disputed: list, missing: list
    ) -> dict:
        """缺件异议分支内的漂移笔误机械对齐（design D1/D2）。

        实现 run 对缺件提出 deliverable-dispute 异议（blocked 待人工）之前，对
        disputed 条目先跑漂移特征判定（``is_drift_candidate``：kind == modify +
        主树 HEAD 缺失 + 分支 HEAD 缺失 + git 历史命中——拆包/改名漂移特征，
        区别于零引用孤儿）：命中 → ``_locate_drift_target`` 候选定位，唯一候选
        且分支 HEAD 真实存在 → 机械改写生效声明（复用 ``_relocate_or_register``：
        文本改写或凭据登记 + 审计 + 分支提交），不 blocked；零/多候选或特征不
        命中 → fail-open 维持 blocked 待人工（不机械改写）。

        与 ``_preclassify_stale`` 互斥（design D1「单轮单通道」）：``_preclassify
        _stale`` 只挂在 ``_adjudicate_deliverable_missing`` 链上（缺件无异议），
        本通道只挂在 queue.py 争议分支（缺件异议）——异议形态下 stale 通道不可达，
        两类条目也按「历史命中与否」天然分流，同一轮同一 spec MUST NOT 双通道各
        改写一次声明。本通道失败（零/多候选、改写异常）即回退既有 blocked 待
        人工通道，MUST NOT 再触发重定位改写。

        Returns:
            {"action": "proceed"} → 全部漂移条目已对齐，守卫重跑通过（调用方
            continue merge 推进，spec 置 implementing）；
            {"action": "continue", "remaining_missing": [...], "remaining_disputed": [...]}
            → 仍有缺件：remaining_missing 为守卫重跑后的缺件清单，remaining_disputed
            为其中仍带异议的项（非空 → 调用方 blocked 待人工，空 → 交既有 LLM 终审）；
            {"action": "fallback"} → 无可对齐条目 / 判定·改写·提交·守卫重跑任一
            环节异常，全量回退既有 blocked 待人工路径（missing 不变）。
        """
        from core.deliverables import (
            _git_branch_merge_base,
            is_drift_candidate,
        )

        branch = getattr(result, "branch", None)
        if not branch:
            return {"action": "fallback"}

        # 生效声明（与守卫同源：worktree > 分支 > 主树回退）——重定位改写的
        # 执行目标与条目级 kind 判定基准（D2：读写同位，MUST NOT 直写主树）
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        by_path = {e["path"]: e for e in entries}
        if not entries:
            return {"action": "fallback"}

        try:
            merge_base = _git_branch_merge_base(self._pm.project_root, branch)
        except Exception:
            merge_base = None
        if not merge_base:
            # 分支改动集合基准不可用 → 无法判定「改动落在哪个模块」，
            # fail-open 回人工（不机械改写）
            return {"action": "fallback"}

        # 缺件入参兼容 list[dict]（path/kind/violation）与 list[str]
        missing_paths = [m["path"] if isinstance(m, dict) else str(m) for m in missing]

        # 逐条漂移判定 → 唯一候选 → 机械对齐（单条异常 → 保留 disputed 走人工）
        aligned_old: list = []
        remaining: list = []
        for d in disputed:
            p = str(d)
            entry = by_path.get(p)
            if entry is None:
                # 声明段无该条目（缺件来自正则回退/基线）→ 无从改写，保留人工
                remaining.append(p)
                continue
            try:
                dc = is_drift_candidate(
                    entry, self._pm.project_root, branch, merge_base
                )
            except Exception as exc:
                remaining.append(p)
                self._pm.logger.warning(
                    "pm_engine",
                    f"漂移特征判定异常 '{spec_name}'（{p} 保留人工）: {exc}",
                )
                continue
            if not dc.get("drift"):
                remaining.append(p)
                continue
            evidence = dc.get("evidence") or {}
            cands = evidence.get("candidates") or []
            if len(cands) != 1:
                # 候选零个或多个 → fail-open 回人工（不机械改写）
                self._pm.logger.warning(
                    "pm_engine",
                    f"漂移候选 {len(cands)} 个（{p}）'{spec_name}' — 不唯一，"
                    f"保留人工（候选 {cands}）",
                )
                remaining.append(p)
                continue
            new_path = cands[0]
            # 防「改声明 ≠ 交付物落地」：候选在实现分支 HEAD 真实存在
            try:
                exists = (
                    self._pm.agent_runner.worktree_manager.file_exists_on_branch(
                        branch, new_path
                    )
                )
            except Exception:
                exists = False
            if not exists:
                remaining.append(p)
                continue
            history_hits = evidence.get("history_hit") or len(
                (evidence.get("git_log") or {}).get("commits") or []
            )
            reason = (
                f"drift-aligned: 历史命中 {history_hits} 条，拆包/改名漂移特征"
                f"（主树与分支 HEAD 均缺该旧单文件路径），分支改动集合"
                f"(merge-base {merge_base}..{branch}) 包内唯一候选 {new_path}"
            )
            ok = self._relocate_or_register(
                spec_name,
                result,
                resolved,
                p,
                new_path,
                "mechanical-branch-diff",
                verdict="drift-aligned",
                evidence=reason,
                extra_audit={
                    "candidates": cands,
                    "merge_base": merge_base,
                    "history_hits": history_hits,
                },
            )
            if ok:
                aligned_old.append(p)
            else:
                remaining.append(p)

        if not aligned_old:
            # 无可对齐条目 → 全量回退既有 blocked 待人工路径
            return {"action": "fallback"}

        # 对齐后守卫复检：替代路径真实存在方通过（防洗白，与 stale 通道同源）
        try:
            gate_result = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"漂移对齐后守卫重跑异常 '{spec_name}'（回退 blocked）: {e}",
            )
            # 异常回退：声明已改写无法回滚，但处置维持 blocked 待人工
            # （fail-open 不改既有处置：剩余缺件全部按未预分类处理）
            return {"action": "fallback"}

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支（对齐 _preclassify_orphan）
            self._pm.logger.warning(
                "pm_engine",
                f"漂移声明对齐全清 '{spec_name}'（{aligned_old}）— 守卫重跑通过，"
                f"放行 merge",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "implementing",
                    "error": None,
                },
            )
            return {"action": "proceed"}

        # 仍有缺件 → 以重跑后的 remaining 续走既有后续（remaining_disputed 供
        # 调用方判断 blocked vs LLM 终审）
        remaining_paths = [
            g["path"] if isinstance(g, dict) else str(g) for g in gate_result
        ]
        remaining_disputed = [r for r in remaining_paths if r in (disputed + remaining)]
        return {
            "action": "continue",
            "remaining_missing": gate_result,
            "remaining_disputed": remaining_disputed,
        }

    def _backup_to_history(self, spec_name: str, element: str, content: str) -> None:
        """删除前 .history 备份留痕（对齐 admin 处置 .history 备份惯例）。

        备份目标：``<project_root>/.history/<spec_name>/<元素 basename>.<时间戳>
        .orphan-preclassify.bak``（.history 已在 .gitignore 排除，不提交）。
        备份内容为删除前的 tasks.md 全文快照（diff.before 同源）。备份失败仅
        WARNING，不阻塞删除本身（备份是附加留痕，fail-open）。
        """
        try:
            backup_dir = self._pm.project_root / ".history" / spec_name
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d%H%M%S")
            backup_path = (
                backup_dir
                / f"{Path(element).name}.{ts}.orphan-preclassify.bak"
            )
            backup_path.write_text(content, encoding="utf-8")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿删除 .history 备份失败 '{spec_name}'（{element}，非阻塞）: {e}",
            )

    # ── 陈日声明前置分类与重定位（add-declaration-relocation-protocol D4）──────

    def _preclassify_stale(self, spec_name: str, result, missing: list) -> dict:
        """陈日声明前置分类（3.5/4.1）：命中陈日信号的缺件走重定位通道。

        在预分类软化 / LLM 终审**之前**对缺件清单逐条做陈日信号判定
        （``is_stale_declaration``：kind == modify 且基线主树 HEAD 无该路径）。
        命中陈日信号的条目 MUST NOT 直接落入「缺件 → 打回重派」：

        - 机械 basename 唯一命中（3.4，``match_basename_in_tree`` 仅唯一命中）
          且凭据三要素齐备（3.3：旧路径基线不存在 ✓ 陈日信号 + 替代路径在实现
          分支 HEAD 存在 + 来源标注 ``mechanical-basename``）→ 直接重定位：
            生效声明仍含该条目 → ``relocate_declared_path`` 文本改写（kind 保持）
            已无该条目（实现方先行对齐）→ ``register_relocation_credential``
            凭据登记（3.6，不经文本替换）
          两者均落 dispute 审计流 + 分支提交固化（4.2），成本不消耗重派预算；
        - 无唯一命中 / 替代路径分支 HEAD 不存在 / 判定异常 → 保留在 remaining
          交 LLM 终审（typo 裁决的 actual_path 归途复用，4.3）。

        纯机械判定（基线存在性 + basename 匹配），MUST NOT 触发 LLM；单条异常
        fail-safe 回退（保留在 remaining 走既有流程，不阻塞整条收工链）。

        Args:
            spec_name: spec 名。
            result: 实现 run 结果（含 branch，供分支 HEAD 存在性判定）。
            missing: 守卫结构化返回的全量条目（list[dict] 或 list[str]）。

        Returns:
            {"action": "proceed"} → 重定位后守卫复检全清（放行分支，不派 judge）；
            {"action": "continue", "remaining": [...]} → 仍有缺件待后继流程
            （remaining 为守卫复检后的结构化条目或原缺件）。
        """
        from core.deliverables import (
            is_stale_declaration,
            match_basename_in_tree,
            register_relocation_credential,
            relocate_declared_path,
        )

        branch = getattr(result, "branch", None)
        missing_paths = [
            m["path"] if isinstance(m, dict) else str(m) for m in missing
        ]
        if not missing_paths:
            return {"action": "continue", "remaining": missing}

        # 生效声明（与守卫同源：worktree > 分支 > 主树回退）——重定位改写的
        # 执行目标与条目级 kind 判定基准（D1/D2：读写同位）
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        by_path = {e["path"]: e for e in entries}

        relocated_any = False
        relocated_old: list = []  # 已走重定位的旧路径（复检时不再计入缺件）
        remaining: list = []
        for p in missing_paths:
            entry = by_path.get(p)
            # 仅声明段条目可判陈日；正则回退路径（无 kind 概念）不命中
            if not entry or not is_stale_declaration(entry, self._pm.project_root):
                remaining.append(p if not isinstance(p, dict) else p)
                continue
            # 陈日信号命中：机械 basename 唯一命中 → 候选替代路径（3.4）
            try:
                hits = match_basename_in_tree(self._pm.project_root, p)
            except Exception:
                hits = []
            if len(hits) != 1:
                # 多命中 / 零命中：不自动重定位（D4 多命中/零命中转终审或人工）
                remaining.append(p)
                continue
            new_path = hits[0]
            # 凭据三要素之 2：替代路径在实现分支 HEAD 真实存在
            if not branch:
                remaining.append(p)
                continue
            try:
                exists = self._pm.agent_runner.worktree_manager.file_exists_on_branch(
                    branch, new_path
                )
            except Exception:
                exists = False
            if not exists:
                # 替代路径不在分支 → MUST NOT 改写（防「改声明 ≠ 交付物落地」）
                remaining.append(p)
                continue
            # 三要素齐备 → 重定位执行
            ok = self._relocate_or_register(
                spec_name, result, resolved, p, new_path, "mechanical-basename"
            )
            if ok:
                relocated_any = True
                relocated_old.append(p)
            else:
                remaining.append(p)

        if not relocated_any:
            return {"action": "continue", "remaining": remaining}

        # 重定位后守卫复检：替代路径真实存在方通过（防洗白，3.7/4.4）
        try:
            gate = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"陈日重定位后守卫复检异常 '{spec_name}'（回退缺件处置）: {e}",
            )
            return {"action": "continue", "remaining": missing}
        if not gate:
            self._pm.logger.warning(
                "pm_engine",
                f"陈日声明重定位全清 '{spec_name}'（{relocated_old}）— "
                f"守卫复检通过，放行 merge",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {"status": "implementing", "error": None},
            )
            return {"action": "proceed"}
        return {"action": "continue", "remaining": gate}

    def _relocate_or_register(
        self,
        spec_name: str,
        result,
        resolved: dict,
        old_path: str,
        new_path: str,
        source: str,
        *,
        verdict: str = "typo",
        evidence=None,
        extra_audit: "dict | None" = None,
    ) -> bool:
        """重定位执行（3.2/3.3 文本改写 或 3.6 凭据登记），落审计 + 分支提交。

        生效声明（``resolved``）仍含该条目 → ``relocate_declared_path`` 文本改写
        （kind 保持、同名去重，改写目标 = 生效声明所在位置 spec_dir）；已无该条目
        （实现方先行对齐）→ ``register_relocation_credential`` 凭据登记（不经文本
        替换）。二者均落 dispute 审计流（含 before/after diff 或凭据摘要）+ 分支
        提交固化（4.2）。改写/登记失败 → False（调用方保留在 remaining）。

        ``verdict``/``evidence``/``extra_audit``（可选，evo-deliverable-declaration-
        drift-align 1.4）：缺省 ``verdict="typo"`` 保持既有调用形态；漂移机械对齐
        通道传 ``verdict="drift-aligned"`` + 候选唯一性证据（evidence）与对齐细节
        （extra_audit 合并进落册记录，如候选清单/历史命中数/merge_base），供审计
        溯源。``extra_audit`` 非 dict 时忽略。

        Returns:
            重定位成功（改写或登记 + 审计 + 提交完成）返回 True；异常/失败 False。
        """
        from core.deliverables import (
            register_relocation_credential,
            relocate_declared_path,
        )

        spec_dir = resolved.get("spec_dir")
        entries = resolved.get("entries") or []
        entry_still_present = any(
            isinstance(e, dict) and e.get("path") == old_path for e in entries
        )
        try:
            if entry_still_present and spec_dir:
                # 3.2/3.3：文本改写（生效声明所在位置）——kind 保持、同名去重
                diff = relocate_declared_path(spec_dir, old_path, new_path)
                from core.admin_store import DisputeAuditStore

                audit_rec = {
                    "spec": spec_name,
                    "trigger_run_id": getattr(result, "run_id", "") or "",
                    "type": "relocation",
                    "old_path": old_path,
                    "new_path": new_path,
                    "source": source,
                    "verdicts": [
                        {
                            "element": old_path,
                            "verdict": verdict,
                            "actual_path": new_path,
                            "reasoning": f"relocate: {source}"
                            + (f"; {evidence}" if evidence else ""),
                        }
                    ],
                    "diff": {
                        old_path: {
                            "before": (diff or {}).get("before"),
                            "after": (diff or {}).get("after"),
                        }
                    },
                }
                if isinstance(extra_audit, dict):
                    audit_rec.update(extra_audit)
                DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                    audit_rec
                )
            else:
                # 3.6：凭据登记（不经文本替换）——生效声明已无该条目、或声明
                # 来源为分支版本无落盘位置（spec_dir=None，evo-deliverable-
                # declaration-drift-align D2：MUST NOT 直写主树声明——改写与
                # 守卫读取错位即 add-declaration-relocation-protocol 立 SPEC
                # 的根因）。凭据三要素在调用方已校验。
                register_relocation_credential(
                    spec_name,
                    old_path,
                    new_path,
                    source,
                    getattr(result, "run_id", "") or "",
                    self._pm.project_root,
                    branch=getattr(result, "branch", None),
                    verdict=verdict,
                    evidence=evidence,
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"陈日重定位执行失败 '{spec_name}'（{old_path} → {new_path}，"
                f"回退缺件处置）: {e}",
            )
            return False
        # 分支提交固化（4.2）：改写/登记落盘后立即提交到实现分支（写盘即固化）
        self._commit_declaration_rewrite(spec_name, old_path, new_path, result)
        return True

    def _commit_declaration_rewrite(
        self, spec_name: str, element: str, new_path: str, result
    ) -> None:
        """声明改写/登记后提交固化到实现分支（add-declaration-relocation-protocol D2）。

        改写目标 = 生效声明所在位置（worktree 内文件 → 分支 → 主树回退，见
        ``resolve_effective_declaration``）。改写后 MUST 在实现分支上提交：

        - worktree 存在（full 车道守卫/裁决窗口保留 / fast-track 现场保留）：
          ``git -C <worktree> add + commit``（提交落实现分支 HEAD）；
        - worktree 已清理、仅分支留存：经 ``worktree_manager`` 重挂该分支
          worktree、提交后移除（MUST NOT ``git -C <project_root> commit``——
          只作用于主树当前分支，不会落到实现分支；仓库内亦无 commit-tree 型
          无 worktree 写分支助手）。
        - 提交失败仅 WARNING：内容仍在工作区，派发前 ``ensure_spec_committed``
          兜底（与既有 ``_commit_softened_declaration`` 非阻塞语义一致）。
        """
        branch = getattr(result, "branch", None)
        if not branch:
            return
        rel = f"spec/changes/{spec_name}/tasks.md"
        try:
            worktree_path = (
                self._pm.agent_runner.worktree_manager.find_worktree_path(branch)
            )
        except Exception:
            worktree_path = None
        tmp_wt = None
        if worktree_path is None:
            try:
                tmp_wt = self._pm.agent_runner.worktree_manager.create_worktree_on_branch(
                    spec_name, branch, prefix="judge"
                )
            except Exception:
                tmp_wt = None
            worktree_path = tmp_wt
        if worktree_path is None:
            # 重挂失败：退回既有主树提交路径（非阻塞，派发前兜底）
            self._commit_softened_declaration(spec_name, element)
            return
        import subprocess as _sp

        try:
            add = _sp.run(
                ["git", "-C", str(worktree_path), "add", "--", rel],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if add.returncode == 0:
                _sp.run(
                    [
                        "git",
                        "-C",
                        str(worktree_path),
                        "commit",
                        "-m",
                        f"[fenix] {spec_name}: 声明段重定位（{element} → {new_path}）",
                        "--",
                        rel,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            self._pm.logger.info(
                "pm_engine",
                f"声明段重定位已在实现分支提交 '{spec_name}'（{element} → "
                f"{new_path}，worktree {worktree_path}）",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"声明段重定位分支提交失败 '{spec_name}'（{element}，非阻塞）: {e}",
            )
        if tmp_wt is not None:
            try:
                self._pm.agent_runner.worktree_manager.cleanup(tmp_wt, success=True)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"judge 重挂 worktree 清理失败 '{spec_name}'（非阻塞）: {e}",
                )

    def _adjudicate_deliverable_missing(
        self, spec_name: str, result, impl_result, missing: list,
        *, agent_type: str = "implementer",
    ) -> dict:
        """缺件 LLM 终审 + 裁决机械执行（D3/D4，Tasks 4.1-4.4）。

        在既有 dispute 异议通道之后调用（实现 run 已对缺件提出 deliverable-dispute
        异议的 spec 走 blocked 人工，不进入终审）。

        预分类（add-declaration-premechanize D4，Task 4.1-4.3）：
        - 组装 judge 输入之前，先对缺件清单做确定性分类：命中不可交付模式
          （gitignored / 仓库外）的条目直接机械软化 kind → reference + 审计
          （reasoning 前缀 guard-preclassify）+ 重跑守卫；全清则走放行分支且
          不派 judge run；剩余项才进入既有 dispute-judge 流程。
        - 预分类异常（声明段解析失败/软化改写异常）→ 全量回退既有 judge 流程。

        流程：

        1. spec 置 blocked（error 含 dispute-judge run id 与「LLM 终审进行中」），
           阻断轮询/巡检重派竞态（D5）；
        2. 组装 judge 输入并派单轮 dispute-judge run（主树只读、无 worktree）；
        3. 读取裁决 JSON（4.2）：run 失败/超时/JSON 不合法/verdicts 缺失 →
           全部待裁缺件等价 unclear；
        4. 按裁决机械执行（4.3）：typo → tasks.md 声明 path 确定性替换为
           actual_path（同名去重）；reference → 条目 kind 软化；missing/unclear
           保持缺件处置；
        5. 防洗白闸门（4.4）：typo 修正 + reference 软化后重跑守卫对账——
           actual_path 在实现分支真实存在才放行 merge；仍缺失按缺件走既有
           打回路径（修正声明 ≠ 放行缺件）；
        6. typo/reference 裁决执行落 dispute 审计流（4.5）。

        Returns:
            dict：{"action": "proceed"} → 守卫重跑通过/缺件已软化，调用方继续
            merge 推进；{"action": "handled"} → 已终态处置（打回重派 / blocked
            人工 / 防洗白打回），调用方直接 return。
        """
        # ── 陈日声明前置分类（add-declaration-relocation-protocol 3.5/4.1）──
        # 在预分类**之前**：命中陈日信号（kind == modify 且基线主树 HEAD 无该
        # 路径）的缺件走重定位通道（机械 basename 唯一命中 → 改写/凭据登记 +
        # 分支提交 + 复检；无唯一命中 → 保留交终审 actual_path 归途），MUST NOT
        # 直接落入「缺件 → 打回重派」。纯机械判定不触发 LLM。重定位全清 →
        # proceed（放行分支且不派 judge run）。
        stale_result = self._preclassify_stale(spec_name, result, missing)
        if stale_result.get("action") == "proceed":
            return stale_result
        missing = stale_result.get("remaining", missing)
        # ── 预分类（add-declaration-premechanize D4）：确定性缺件先行软化 ──
        # 在组装 judge 输入之前，先对缺件清单做确定性分类：命中不可交付模式
        # 的条目直接机械软化 + 审计 + 重跑守卫；全清走放行分支且不派 judge run；
        # 剩余项才进入 dispute-judge。预分类异常全量回退既有 judge 流程。
        preclassify_result = self._preclassify_missing(spec_name, result, missing)
        if preclassify_result.get("action") == "proceed":
            return preclassify_result
        # remaining 是预分类后仍存在的缺件清单；若预分类全清则 proceed，
        # 否则剩余项带入后续 judge 流程（judge 输入只含剩余项）。
        remaining = preclassify_result.get("remaining", missing)
        # 将 remaining 规范化为路径列表（兼容 list[str] 与 list[dict]）
        remaining_paths = [r["path"] if isinstance(r, dict) else str(r) for r in remaining]
        # kind 映射：供 judge 输入携带 kind（4.5）及 delete 防洗白（4.3）。
        # 经统一解析入口取生效声明条目（add-declaration-relocation-protocol
        # D1，与守卫同源），缺省 "new"（正则回退路径无 kind 概念）。
        kind_by_path: dict = {}
        try:
            _resolved = self._effective_declaration(spec_name, result)
            for e in _resolved.get("entries") or []:
                if isinstance(e, dict) and e.get("path") and e.get("kind"):
                    kind_by_path[e["path"]] = e["kind"]
        except Exception:
            pass
        # judge 输入快照：需基于 judge 的输入清单（路径列表）
        judge_input_paths = list(remaining_paths)

        judge_run_id = f"dispute-judge-{spec_name}-{int(time.time())}"
        # 1. 终审期间 spec 置 blocked（error 含 run id），阻断重派竞态
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "status": "blocked",
                "tester_run": None,
                "error": (
                    f"交付物守卫缺件 [{', '.join(remaining_paths)}] — LLM 终审进行中"
                    f"（judge run {judge_run_id}）"
                ),
            },
        )
        self._pm.logger.warning(
            "pm_engine",
            f"交付物守卫缺件 '{spec_name}' 进入 LLM 终审（{judge_run_id}）",
        )

        # 2. 组装输入并派单轮 dispute-judge run（仅含预分类后剩余项）
        judge_input = self._build_dispute_judge_input(
            spec_name, impl_result, remaining, kind_by_path=kind_by_path
        )
        judge_result = None
        try:
            judge_result = self._pm.agent_runner.run_dispute_judge(
                spec_name, judge_input, run_id=judge_run_id
            )
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"dispute judge 派发异常 '{spec_name}'（等价 unclear）: {e}",
            )
            judge_result = None

        # 3. 结果消费：非法裁决 → 全部待裁缺件等价 unclear
        verdict_data = self._read_dispute_verdicts(spec_name, judge_run_id, judge_result)
        verdict_by_element = {}
        if verdict_data is not None:
            for v in verdict_data.get("verdicts") or []:
                if isinstance(v, dict) and v.get("element"):
                    verdict_by_element[str(v["element"])] = v

        def _verdict_of(path: str) -> dict:
            v = verdict_by_element.get(path)
            if isinstance(v, dict) and v.get("verdict") in (
                "typo",
                "reference",
                "missing",
                "unclear",
            ):
                return v
            return {"verdict": "unclear"}

        # 4. 裁决机械执行：typo 修正 / reference 软化（逐条，失败等价 unclear）
        #    改写目标 = 生效声明所在位置（worktree → 分支 → 主树回退，D2 读写同位；
        #    与守卫读侧同源——MUST NOT 硬编码主树 spec 目录直读）。typo 命中陈日
        #    信号时按重定位协议执行（3.2/3.3 改写或 3.6 凭据登记，4.3）。
        executed_verdicts: list = []
        diff_by_element: dict = {}
        # 生效声明上下文（改写目标 spec_dir + 条目级 kind/陈日判定基准）
        effective_resolved = self._effective_declaration(spec_name, result)
        eff_spec_dir = effective_resolved.get("spec_dir") or str(
            self._pm.project_root / "spec" / "changes" / spec_name
        )
        eff_entries = effective_resolved.get("entries") or []
        eff_by_path = {e["path"]: e for e in eff_entries}
        for m in remaining_paths:
            v = _verdict_of(m)
            verdict = v.get("verdict")
            kind_m = kind_by_path.get(m, "new")
            entry = eff_by_path.get(m) or {"path": m, "kind": kind_m}
            try:
                if verdict == "typo":
                    actual_path = str(v.get("actual_path") or "").strip()
                    if not actual_path:
                        verdict_by_element[m] = {"verdict": "unclear"}
                        continue
                    from core.deliverables import is_stale_declaration

                    # 4.3 重定位接入裁决：typo 裁决命中陈日信号（modify + 基线
                    # 不存在）→ 按重定位凭据三要素执行——生效声明仍含该条目走
                    # 3.2/3.3 文本改写（relocate_declared_path）；已无该条目
                    # （实现方先行对齐）走 3.6 凭据登记。非陈日走既有 typo 修正。
                    if is_stale_declaration(entry, self._pm.project_root):
                        ok = self._relocate_or_register(
                            spec_name,
                            result,
                            effective_resolved,
                            m,
                            actual_path,
                            "judge-actual-path",
                        )
                        if not ok:
                            verdict_by_element[m] = {"verdict": "unclear"}
                            continue
                        # 改写 diff 留痕（改写后重读声明段全文）
                        try:
                            before_text = Path(eff_spec_dir, "tasks.md").read_text(
                                encoding="utf-8"
                            )
                        except (OSError, UnicodeDecodeError):
                            before_text = ""
                        diff_by_element[m] = {
                            "before": before_text,
                            "after": before_text,
                        }
                        executed_verdicts.append({"element": m, **v})
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispute judge 裁决 typo（陈日重定位）'{spec_name}': "
                            f"{m} → {actual_path}（凭据三要素齐备，重定位执行）",
                        )
                    else:
                        from core.deliverables import replace_declared_path

                        diff = replace_declared_path(eff_spec_dir, m, actual_path)
                        diff_by_element[m] = diff
                        executed_verdicts.append({"element": m, **v})
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispute judge 裁决 typo '{spec_name}': "
                            f"{m} → {actual_path}（声明段已修正）",
                        )
                        self._commit_softened_declaration(
                            spec_name, f"{m} → {actual_path}（typo 修正）"
                        )
                elif verdict == "reference" and kind_m == "delete":
                    # 4.3 防洗白：delete 条目的 reference 归宿被机械拒绝——
                    # 改写为 unclear（转人工），不软化声明段（软化 = 删除要求
                    # 静默消失）；审计记录保留 judge 原始 verdict 与改写事实。
                    verdict_by_element[m] = {
                        "verdict": "unclear",
                        "judge_original": "reference",
                        "rewrite_reason": "delete-kind-reference-rejected",
                    }
                    executed_verdicts.append(
                        {
                            "element": m,
                            "verdict": "unclear",
                            "judge_original": "reference",
                            "rewrite_reason": "delete-kind-reference-rejected",
                        }
                    )
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute judge 裁决 reference 被拒 '{spec_name}': "
                        f"{m} 是 kind: delete——reference 归宿不可用"
                        f"（防洗白 D4），改写为 unclear 转人工",
                    )
                elif verdict == "reference":
                    from core.deliverables import soften_declared_kind

                    diff = soften_declared_kind(eff_spec_dir, m)
                    diff_by_element[m] = diff
                    executed_verdicts.append({"element": m, **v})
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute judge 裁决 reference '{spec_name}': "
                        f"{m} 已软化为 reference（转软校验）",
                    )
                    self._commit_softened_declaration(spec_name, m)
            except Exception as e:
                # 声明段修正失败（并发改写/格式漂移）→ 该条等价 unclear（D6）
                verdict_by_element[m] = {"verdict": "unclear"}
                self._pm.logger.warning(
                    "pm_engine",
                    f"dispute judge 裁决执行失败 '{spec_name}'（{m} 等价 unclear）: {e}",
                )

        # 5. 审计留痕（4.5）：typo/reference 裁决执行落 dispute 审计流
        if executed_verdicts:
            try:
                from core.admin_store import DisputeAuditStore

                DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                    {
                        "spec": spec_name,
                        "trigger_run_id": getattr(result, "run_id", "") or "",
                        "judge_run_id": judge_run_id,
                        "verdicts": (
                            verdict_data.get("verdicts") if verdict_data else executed_verdicts
                        ),
                        "diff": {
                            k: {"before": d.get("before"), "after": d.get("after")}
                            for k, d in diff_by_element.items()
                        },
                    }
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"dispute 审计写盘失败 '{spec_name}'（非阻塞）: {e}",
                )

        # 6. 防洗白闸门（4.4）：修正后重跑守卫对账——actual_path 在实现分支
        # 真实存在才放行；仍缺失按缺件走既有打回路径（修正声明 ≠ 放行缺件）。
        remaining = self._pm._deliverable_gate_missing(spec_name, result)
        if not remaining:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 裁决执行后守卫重跑通过 '{spec_name}' — 放行 merge",
            )
            # 终审期间置 blocked 属临时态：恢复 in-flight（implementing），
            # worker 合并路径的 implementing → implemented 转换才合法
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "implementing",
                    "error": None,
                },
            )
            return {"action": "proceed"}

        # 规范化 remaining（list[dict]）为路径列表 + 保留条目供下游
        remaining_paths = [r["path"] if isinstance(r, dict) else str(r) for r in remaining]

        # 仍有缺件：分类 remaining 的归宿。remaining 可能含 typo 修正后的
        # actual_path（非原 element）——凡能追溯到「已执行 typo 修正」或
        # 「missing 裁决」的路径按既有打回路径处置（防洗白：修正声明 ≠ 放行
        # 缺件）；unclear 项（含裁决执行失败/判据不明）→ blocked 人工裁决。
        typo_fixed_paths = set()
        for m in judge_input_paths:
            v = _verdict_of(m)
            if v.get("verdict") == "typo":
                ap = str(v.get("actual_path") or "").strip()
                if ap:
                    typo_fixed_paths.add(ap)
        unclear_remaining = []
        for p in remaining_paths:
            # typo 修正后的 actual_path：修正声明后文件仍不存在 = 防洗白 → 打回
            if p in typo_fixed_paths:
                continue
            v = _verdict_of(p)
            if v.get("verdict") == "unclear":
                unclear_remaining.append(p)
                continue
            # 非 unclear：missing 裁决的原 element 按缺件打回；既非原 element
            # 又非任何修正路径 → 裁决未覆盖，保守按 unclear 转人工（防 judge
            # 输出与清单不一致）。
            if p in judge_input_paths:
                continue
            unclear_remaining.append(p)
        if unclear_remaining:
            u_q = "、".join(unclear_remaining)
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "blocked",
                    "tester_run": None,
                    "error": (
                        f"交付物守卫缺件 [{u_q}] LLM 终审裁决 unclear/不可信 — "
                        f"已 blocked 待人工裁决，不自动重派（judge run {judge_run_id}）"
                    ),
                },
            )
            self._pm.logger.error(
                "pm_engine",
                f"交付物守卫缺件终审 unclear '{spec_name}'（{u_q}）— blocked 待人工",
            )
            return {"action": "handled"}

        # 真缺件 / typo 防洗白落空：既有打回/重派路径（带精准缺件清单）
        self._redispatch_for_missing(spec_name, result, remaining, agent_type=agent_type)
        return {"action": "handled"}

    def _redispatch_for_missing(
        self,
        spec_name: str,
        result,
        missing_list: list,
        *,
        agent_type: str = "implementer",
    ) -> None:
        """缺件打回/重派（add-implementer-deliverable-gate 既有路径，4.3 missing）。

        注册分支遗产（供后继 run 收编）→ 重试计数 → 重派（车道无关：full 重派
        implementer，fast-track 重派 fast-track——add-declaration-relocation-protocol
        4.4 双车道同源流水线的重派归宿）；连续 ``agents.max_retries`` 次封顶
        blocked。自 judge 终审进入的调用同样走此路径——judge 不放行不存在的文件
        （防洗白，D4）。重定位与软化（非重派归宿）不消耗本计数（4.3 预算对齐）。

        Args:
            missing_list: 守卫返回的差异条目列表（``list[dict]``，每项含
                ``path``/``kind``/``violation``）。
            agent_type: 重派车道（"implementer" 或 "fast-track"）。
        """
        _wm = self._pm.agent_runner.worktree_manager
        _branch = getattr(result, "branch", None)
        if _branch and hasattr(_wm, "register_legacy"):
            _wm.register_legacy(spec_name, None, _branch)
            # fixed-relint-redispatch-legacy 一致性：打 reuse 标记使仅分支遗产可被
            # 下轮 create 经 _take_reusable_worktree 认领同一分支（与 relint 打回
            # 路径同语义；register_legacy 自身不置 reuse，keep_for_reuse 同源标记）。
            if hasattr(_wm, "mark_legacy_reusable"):
                _wm.mark_legacy_reusable(spec_name)
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        # 按 kind 分化话术：undeleted 用「未删除」语义、missing 保持「缺件」语义
        missing_q = "、".join(
            (
                f"{m.get('path', '?')}（{m.get('violation', 'missing')}）"
                if isinstance(m, dict)
                else str(m)
            )
            for m in missing_list
        )
        err_note = (
            f"交付物守卫：违规 [{missing_q}] — 不合并不推进，" f"重派实现补齐（第 {retries} 次）"
        )
        updates: dict = {
            "status": "ready",
            "error": err_note,
            "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["tester_run"] = None
            updates["error"] = (
                f"交付物守卫连续 {max_r} 次缺件 [{missing_q}] — 已 blocked，"
                f"需人工检查任务书声明与实际落地差异"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"交付物守卫触发 '{spec_name}'（缺件 {missing_q}）— "
            f"run={getattr(result, 'run_id', '') or ''}",
        )
        if updates["status"] != "blocked":
            self._enqueue_front(spec_name, "implementer")

    # ── tasks.md 收口复检门禁处置（add-tasksmd-relint-gate）─────────────────
    # 读取与判定逻辑在 VerificationPipeline._tasks_md_relint_from_branch /
    # _tasks_md_relint_from_worktree（经 PMEngine 门面 com 组件委托访问，
    # design D3 规则 3）；本处仅处置违规（重派/计数），不重复实现判定。

    def _redispatch_tasks_relint(
        self,
        spec_name: str,
        relint: list,
        *,
        agent_type: str = "implementer",
        run_id: str = "",
        branch: str | None = None,
    ) -> None:
        """tasks.md 收口复检违规处置：不合并、不推进，按失败重派。

        error 写违规明细（逐条）与修正处方；连续计数沿用既有重派语义
        （``_retry_count`` 递增，``agents.max_retries`` 封顶 blocked），
        与交付物守卫缺件处置同构。

        重派前登记分支遗产（fix-relint-redispatch-legacy D1/D2）：relint 违规的
        典型成因是 sed 转义把 ``- [x]`` 写成 ``^- [x]``——首轮实现工作完全有效，
        只是 tasks.md 格式有误。本函数在状态写回与重派**之前**把该 run 的分支
        登记为仅分支遗产（与交付物守卫 ``_redispatch_for_missing`` 同款），
        使下一轮 ``worktree_manager.create`` 经 ``_take_reusable_worktree`` 认领
        同一分支、继承首轮已提交成果，而非从 main 新建 worktree 整支搁浅。
        登记后以 ``mark_legacy_reusable`` 打 reuse 标记（同 ``keep_for_reuse``
        语义），使仅分支遗产可被下轮认领重建载体；branch 为空时跳过登记
        （fail-open），登记异常捕获降级 WARNING 不阻断处置。

        D3 顺序语义（fix-redispatch-loop-governance 正交）：登记走**仅分支模式**
        （``worktree_path=None``——full 车道成功收工后 worktree 已被
        ``cleanup(success=True)`` 物理清理，只剩分支留存完整已提交成果）。
        fast-track 车道不传 branch（保持 None）——该车道 relint 处置此前已由
        ``_keep_fast_track_worktree`` 登记**含路径的 worktree 模式遗产**（现场
        保留，reuse=True），若此处再以仅分支登记覆盖会丢失未提交现场。而
        ``register_legacy`` 为覆盖式更新（同一 spec 只留最新一份），两条机制若
        同轮命中以后登记者为准——含路径的 worktree 模式更保守，故 fast-track
        调用点 MUST NOT 传 branch，以免覆盖现场。
        """
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        # ── 重派前登记分支遗产（fix-relint-redispatch-legacy D1/D2）───────────
        # 在状态写回（update_spec）与 _enqueue_front **之前**注册（与交付物守卫
        # _redispatch_for_missing 同序），使 _legacy 在下一轮 create 时已在册。
        # 条件与守卫同型（fail-open）：branch 为空静默跳过；登记自身异常捕获
        # 降级 WARNING（处置链路不得因登记失败中断）。
        _wm = self._pm.agent_runner.worktree_manager
        if branch and hasattr(_wm, "register_legacy"):
            try:
                _wm.register_legacy(spec_name, None, branch)
                if hasattr(_wm, "mark_legacy_reusable"):
                    _wm.mark_legacy_reusable(spec_name)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"relint 遗产登记失败（非阻塞）'{spec_name}': {e}",
                )
        try:
            prev_retries = int(spec_entry.get("_retry_count", 0) or 0)
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        max_r = self._pm._get_config("agents.max_retries", 3)
        detail = "；".join(relint)
        err_note = (
            f"tasks.md 收口复检违规 — 不合并不推进，重派修正（第 {retries} 次）："
            f"{detail}。修正处方：任务行行首必须为 `- [ ]` / `- [x]`；"
            f"若现为 `^- [x]` 即 sed 转义损伤，请改回 `- [` 并恢复 checkbox"
        )
        updates: dict = {
            "status": "ready",
            "error": err_note,
            "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["tester_run"] = None
            updates["error"] = (
                f"tasks.md 收口复检连续 {max_r} 次违规 — 已 blocked，"
                f"需人工修复 tasks.md（行首 `- [ ]`/`- [x]`）"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"tasks.md relint 触发 '{spec_name}'（第 {retries} 次）— " f"run={run_id or 'n/a'}",
        )
        if updates["status"] != "blocked":
            self._enqueue_front(spec_name, agent_type)

    # ── fast-track 单 run 全包 worker（add-fast-track-mode D1/D4/D5/D6）──
