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


class VAdjudicationMixin:
    """V 交付物裁定/dispute（design D1 表 B V 组）。"""

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
            from core.deliverables import extract_declared_entries

            entries = extract_declared_entries(spec_dir)
            if entries:
                context["declared_entries"] = entries
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
        from core.deliverables import classify_unsatisfiable, extract_declared_entries

        # 声明段无条目（存量 spec 正则提取）→ 不预分类，回退 judge
        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        entries = extract_declared_entries(spec_dir)
        if not entries:
            return {"action": "fallback"}

        # 快照软化前 tasks.md 声明段（供审计 diff.before）
        before_text = ""
        tasks_path = spec_dir / "tasks.md"
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

    def _adjudicate_deliverable_missing(
        self, spec_name: str, result, impl_result, missing: list
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
        # 从声明段条目提取，缺省 "new"（正则回退路径无 kind 概念）。
        kind_by_path: dict = {}
        try:
            from core.deliverables import extract_declared_entries as _ede

            _spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
            for e in _ede(_spec_dir) or []:
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
        executed_verdicts: list = []
        diff_by_element: dict = {}
        for m in remaining_paths:
            v = _verdict_of(m)
            verdict = v.get("verdict")
            kind_m = kind_by_path.get(m, "new")
            try:
                if verdict == "typo":
                    actual_path = str(v.get("actual_path") or "").strip()
                    if not actual_path:
                        verdict_by_element[m] = {"verdict": "unclear"}
                        continue
                    from core.deliverables import replace_declared_path

                    diff = replace_declared_path(
                        self._pm.project_root / "spec" / "changes" / spec_name, m, actual_path
                    )
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

                    diff = soften_declared_kind(
                        self._pm.project_root / "spec" / "changes" / spec_name, m
                    )
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
        self._redispatch_for_missing(spec_name, result, remaining)
        return {"action": "handled"}

    def _redispatch_for_missing(self, spec_name: str, result, missing_list: list) -> None:
        """缺件打回/重派（add-implementer-deliverable-gate 既有路径，4.3 missing）。

        注册分支遗产（供后继 run 收编）→ 重试计数 → 重派 implementer；
        连续 ``agents.max_retries`` 次封顶 blocked。自 judge 终审进入的调用
        同样走此路径——judge 不放行不存在的文件（防洗白，D4）。

        Args:
            missing_list: 守卫返回的差异条目列表（``list[dict]``，每项含
                ``path``/``kind``/``violation``）。
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
