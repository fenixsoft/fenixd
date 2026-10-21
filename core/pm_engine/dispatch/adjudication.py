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

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

# agents.max_retries 归一读取器收敛三车道单一落点（code-review item
# 00af54aa1442）：本模块 _resolve_max_retries 曾保留 max(..., 1) 下限且不拒
# bool/浮点，与 repair_lane._max_retries（无下限：0=不自动重试为合法语义；
# 显式拒绝 bool/非整值浮点并 WARNING 留痕）同键跨通道语义分裂——读取点全部
# 转调单一读取器，本模块双写实现删除。
from core.pm_engine.dispatch.repair_lane import _max_retries


def _entry_by_path(entries) -> dict:
    """声明条目列表 → path 条目映射（四预分类器共用，防复制漂移）。

    code-review item f9e0fc21eff6：四个预分类器 impl 各持一份同构构建
    （missing/orphan 为循环版、drift/stale 为推导式版），判据一致
    （code-review item f204e70e4aa8：非 dict / 缺 path 的畸形条目过滤）
    ——收敛单点后，同类修复不再逐点扫齐。路径重复时后写覆盖先写，与提取
    前各处行为逐字一致。
    """
    return {
        e["path"]: e
        for e in entries
        if isinstance(e, dict) and e.get("path")
    }


def _diff_by_element_projection(diff_by_element: dict) -> dict:
    """逐元素 diff 投影（审计落册 by_element 段共用，防复制漂移）。

    仅保留 ``before``/``after`` 两键、非 dict 的 diff 值丢弃——与
    _preclassify_missing/_preclassify_orphan 审计段的既有投影逐字一致。
    """
    return {
        k: {"before": d.get("before"), "after": d.get("after")}
        for k, d in diff_by_element.items()
        if isinstance(d, dict)
    }


class VAdjudicationMixin:
    """V 交付物裁定/dispute（design D1 表 B V 组）。"""

    def _find_worktree_for(self, result) -> "str | None":
        """branch → worktree_path 查找样板（声明读取/写回各方法共用）。

        ``result`` 无分支上下文或查找失败一律回 ``None``，调用方按主树回退
        语义继续——与提取前各调用点行为逐字一致。
        """
        branch = getattr(result, "branch", None) if result is not None else None
        if not branch:
            return None
        try:
            return self._pm.agent_runner.worktree_manager.find_worktree_path(branch)
        except Exception:
            return None

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
        worktree_path = self._find_worktree_for(result)
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
        elif impl_result and impl_result.get("status") == "success":
            # （code-review item 71664501d3f3）原为 `elif impl_status_success := ...`
            # 海象赋值，该变量在方法内从未被读取（死状态且误导性地长寿）；改为
            # 普通布尔条件，语义不变。
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
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {"_impl_diagnosis": json.dumps(diagnosis, ensure_ascii=False)},
            )
            self._pm.logger.info(
                "pm_engine",
                f"实现诊断已记录 '{spec_name}': terminal={terminal}, "
                f"branch={branch}, tasks_checked={tasks_checked}",
            )
        except Exception as e:
            # 诊断是附加物（本方法 docstring 契约：不抛异常）：STATE.md 瞬态
            # IO 异常 MUST NOT 抛穿 run 终结处置流程（code-review item
            # ac84e8dc1873，对齐同文件备份/审计等附加性写盘的容错姿态）。
            self._pm.logger.warning(
                "pm_engine",
                f"实现诊断写盘失败 '{spec_name}'（非阻塞）: {e}",
            )

    # ── 缺件 LLM 终审与裁决机械执行（add-deliverable-declaration-triage D3/D4）──

    def _build_dispute_judge_input(
        self, spec_name: str, impl_result, missing: list,
        kind_by_path: "dict | None" = None, result=None,
    ) -> dict:
        """组装 dispute-judge 输入（4.1/4.5）：缺件 + kind + basename 候选 + 语境。

        ``missing`` 兼容两种形态：路径列表（``list[str]``）或守卫返回的
        结构化条目（``list[dict]``，每项含 ``path``/``kind``/``violation``）。
        ``kind_by_path`` 可选：声明段 path→kind 映射，供 judge 看到「该路径应被
        删除」而非仅看到缺件路径（add-deliverable-delete-kind 4.5）——条目级
        kind 优先于映射，映射优先于默认 ``"new"``。``result`` 可选：run 上下文
        （含 branch/worktree），透传给语境摘录经统一解析入口取生效层，与
        kind_by_path 同源（code-review item 3c39fe0b78d9）。

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
                spec_name, [m["path"] for m in missing_entries], result=result
            ),
            "findings": findings,
        }

    def _dispute_spec_context(
        self, spec_name: str, missing: list, result=None
    ) -> dict:
        """spec 三文档语境摘录：含缺件路径的段落 + Deliverables 声明段全文。

        对 proposal.md/design.md/tasks.md/specs/**/*.md：以缺件路径为关键词
        抽取命中行 ±2 行上下文（每文档独立段落清单，specs 文档以相对
        specs/ 的相对路径为键）；tasks.md 的声明段经
        ``extract_declared_entries`` 结构化摘录。读取失败逐文件跳过并留痕
        （fail-open，单文件失败不中断其余收集）。

        三文档摘录的读取目录取统一解析入口（``_effective_declaration``，D1：
        worktree/分支版本优先、主树回退）返回的生效层 ``spec_dir``，与
        declared_entries 取同一解析结果——MUST NOT 自行拼接主树 spec 目录
        直读（生效声明命中 worktree/分支层时，摘录取主树陈本而条目取生效层，
        judge 两段口径分裂；读分支、写主树的错层正是本次事故根因，
        code-review item 3c39fe0b78d9）。``result`` 提供分支/worktree 上下文
        （可选；缺失时按主树回退语义解析）。分支版本无落盘位置
        （spec_dir 为 None）或解析失败时，摘录回退主树目录（fail-open）。
        """
        from pathlib import Path as _Path

        resolved: dict = {}
        try:
            resolved = self._effective_declaration(spec_name, result)
        except Exception as e:
            # 声明解析失败不再静默吞（code-review item bb46425e6eae）：判定输入
            # 缺失 declared_entries 会静默劣化 judge 口径；记 WARNING（与本文件
            # 其它 fail-open 助手同款留痕），使劣化可诊断。摘录按主树回退目录
            # 继续收集（fail-open）。
            self._pm.logger.warning(
                "pm_engine",
                f"有效声明解析失败 '{spec_name}'（judge 输入缺 declared_entries）: "
                f"{type(e).__name__}: {e}",
            )
        spec_dir = _Path(
            resolved.get("spec_dir")
            or _Path(self._pm.project_root) / "spec" / "changes" / spec_name
        )
        docs = {}
        for name in ("proposal.md", "design.md", "tasks.md"):
            p = spec_dir / name
            if p.is_file():
                try:
                    docs[name] = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as e:
                    # 顶层文档读取失败不再静默吞（code-review item
                    # 883212783043）：与下方 specs 循环及 bb46425e6eae 的留痕
                    # 口径对齐——tasks.md 是裁决最核心的声明文档，文件存在但
                    # 读取失败（权限/解码）会使 judge 输入静默缺失主声明文档，
                    # 劣化须可诊断。
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute 语境读文档失败 '{p}'（跳过单文件）: "
                        f"{type(e).__name__}: {e}",
                    )
        specs_dir = spec_dir / "specs"
        if specs_dir.is_dir():
            # 键用相对 specs/ 的路径而非 basename（code-review item
            # d11709b19335）：specs 子目录下同名文件（a/overview.md 与
            # b/overview.md）以 f.name 为键会静默互相覆盖，judge 摘录丢其
            # 一；容错收敛到单文件粒度——单个文件读取失败仅跳过自身并
            # 留痕，不再中断整轮收集。
            for f in sorted(specs_dir.rglob("*.md")):
                if not f.is_file():
                    continue
                try:
                    docs[str(f.relative_to(specs_dir))] = f.read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeDecodeError) as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute 语境读 specs 文件失败 '{f}'（跳过单文件）: "
                        f"{type(e).__name__}: {e}",
                    )

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
        if resolved.get("entries"):
            context["declared_entries"] = resolved["entries"]
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
                f"dispute judge run 失败 '{spec_name}'（judge run {judge_run_id}，"
                f"等价 unclear）: "
                f"{getattr(judge_result, 'error', '') or ''}",
            )
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 JSON 不合法 '{spec_name}'"
                f"（judge run {judge_run_id}，等价 unclear）",
            )
            return None
        if not isinstance(data, dict) or data.get("status") != "success":
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 status 非 success '{spec_name}'"
                f"（judge run {judge_run_id}，等价 unclear）",
            )
            return None
        # run stamp 严格匹配（code-review item 01d1335a9902）：结果文件按 spec
        # 固定路径跨轮复用，写侧 runner.run_dispute_judge 派发前 unlink，但
        # unlink 失败 + 本轮写盘失败时旧文件残留——文件内 run_id 与本次 judge
        # run 不一致 → 视为陈旧裁决拒绝，等价 unclear（对齐
        # _cleanup_shared_result_file 的 stamp 严格匹配范式，fail-closed）。
        if data.get("run_id") != judge_run_id:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果 run stamp 与本次 judge run 不符 '{spec_name}'"
                f"（judge run {judge_run_id}，等价 unclear）",
            )
            return None
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, list) or not verdicts:
            self._pm.logger.warning(
                "pm_engine",
                f"dispute judge 结果缺 verdicts '{spec_name}'"
                f"（judge run {judge_run_id}，等价 unclear）",
            )
            return None
        return data

    def _commit_softened_declaration(
        self, spec_name: str, element: str, repo_root=None
    ) -> bool:
        """软化/修正声明段后立即提交 tasks.md（fix-merge-back-deadlock 同类修复）。

        ``soften_declared_kind`` / ``replace_declared_path`` 直接改写生效声明所在
        位置的 ``spec/changes/<spec>/tasks.md`` 但不提交，使 merge-back 陷入死锁：
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

        ``repo_root``（fix-relocation-writeback-layer Task 1.3）：提交根随**写回层**
        ——生效声明命中 worktree 时 MUST 提交到该 worktree 的分支（`git -C
        <worktree>`），命中主树时提交到 ``project_root``（缺省保持既有行为）。
        返回 True 表示已成功提交（调用方据此判定「修正是否已落命中层」，失败时
        走打回/凭据降级通道，MUST NOT 误判成功）。
        """
        rel = f"spec/changes/{spec_name}/tasks.md"
        try:
            ok, err = self._pm._git_commit(
                [rel],
                f"[fenix] {spec_name}: 声明段修正（{element}）",
                repo_root=repo_root,
            )
            if ok:
                self._pm.logger.info(
                    "pm_engine",
                    f"声明段软化已提交 '{spec_name}': {element}"
                    + (f"（提交根 {repo_root}）" if repo_root else "（主树）"),
                )
                return True
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
        return False

    def _writeback_target(self, spec_name: str, result=None) -> dict:
        """裁决侧写回层判定入口（fix-relocation-writeback-layer D1，Task 1.1）。

        与守卫读取同源（``_effective_declaration``）：同一 ``resolve_effective
        _declaration`` 优先序下的 ``source`` 决定修正的写入落点与提交根。返回
        ``{"writable", "spec_dir", "source", "commit_root", "declaration"}``。
        """
        from core.deliverables import resolve_writeback_target

        branch = getattr(result, "branch", None) if result is not None else None
        worktree_path = self._find_worktree_for(result)
        return resolve_writeback_target(
            spec_name,
            branch=branch,
            worktree_path=worktree_path,
            project_root=self._pm.project_root,
        )

    def _apply_declaration_correction(
        self, spec_name: str, element: str, apply_fn, *, wb: dict
    ) -> tuple:
        """在**写回层**执行声明改写并立即提交（fix-relocation-writeback-layer 1.3/1.4）。

        ``apply_fn(spec_dir)`` 为文本改写（``replace_declared_path`` /
        ``soften_declared_kind`` / ``remove_declared_entry``）。写回层不可写
        （``source == "branch"`` 无落盘位置 / 两处均不可用）或改写/提交失败
        （worktree 被实现 run 占用、git add/commit 冲突或异常）→ 返回
        ``(False, 原因, None)``，调用方 MUST 走打回/凭据降级通道——MUST NOT 改落
        主树「兜底」、MUST NOT 静默判修正成功。

        Returns:
            ``(ok, detail, diff)``：``ok`` 为「改写已生效于守卫读取基准层」
            （**非**「已提交」——提交成败按写回层分叉：main 层提交失败仍返回
            ``ok=True``，守卫读取基准即主树工作区、内容已生效，由
            ensure_spec_committed 派发前兜底提交；worktree 层提交失败则返回
            ``ok=False`` 并回滚半写残留）；``diff`` 为改写函数返回的条目级
            diff（异常时 None）。
        """
        if not wb.get("writable") or not wb.get("spec_dir"):
            return False, f"写回层不可写（source={wb.get('source')}）", None
        # Task 1.4：改写前快照 tasks.md——提交失败时回滚半写残留。不回滚的话
        # 写回层磁盘上是未提交的新路径，守卫（同源读取该层）下一轮读到的是
        # 「从未提交」的声明：旧路径凭据核销（D4）与复发计数（D5）双双失锚，
        # 死循环换个形态继续。
        tasks_file = Path(wb["spec_dir"]) / "tasks.md"
        try:
            before_bytes = tasks_file.read_bytes()
        except Exception:
            before_bytes = None

        def _rollback(reason: str) -> None:
            if before_bytes is None:
                # 快照缺失 ≠ 无需回滚（code-review item c48b885e16b4）：
                # tasks.md 改写前不存在/读取失败时，apply_fn 若在该状态下仍
                # 产生了写入（如新建文件），写回层会残留「从未提交」的半写
                # 声明——守卫（同源读取该层）下一轮读到它，凭据核销（D4）
                # 与复发计数（D5）即失锚。此时以删除代替还原，使「快照缺失」
                # 与「无需回滚」可区分；当前内置 apply_fn（soften/replace/
                # remove）均先读声明段后写、文件缺失即上抛不落盘，本分支属
                # 防御性兜底而非现行可达路径。
                try:
                    if tasks_file.exists():
                        tasks_file.unlink()
                        self._pm.logger.warning(
                            "pm_engine",
                            f"声明改写已回滚（删除改写前不存在的新建 tasks.md）"
                            f"'{spec_name}'（{wb.get('source')} 层改写/提交失败，"
                            f"清除半写残留防读取错层）: {reason}",
                        )
                except Exception as rb_err:
                    self._pm.logger.error(
                        "pm_engine",
                        f"声明改写回滚失败 '{spec_name}'（写回层残留未提交新建"
                        f"声明，需人工核对声明落层）: {rb_err}",
                    )
                return
            try:
                tasks_file.write_bytes(before_bytes)
                self._pm.logger.warning(
                    "pm_engine",
                    f"声明改写已回滚 '{spec_name}'（{wb.get('source')} 层"
                    f"改写/提交失败，还原半写残留防读取错层）: {reason}",
                )
            except Exception as rb_err:
                self._pm.logger.error(
                    "pm_engine",
                    f"声明改写回滚失败 '{spec_name}'（写回层残留未提交改写，"
                    f"需人工核对声明落层）: {rb_err}",
                )

        try:
            diff = apply_fn(wb["spec_dir"])
        except Exception as e:
            _rollback(f"改写异常: {e}")
            return False, f"声明改写失败（{wb.get('spec_dir')}）: {e}", None
        if not self._commit_softened_declaration(
            spec_name, element, repo_root=wb.get("commit_root")
        ):
            if wb.get("source") == "worktree":
                # Task 1.4（worktree 层）：worktree 被实现 run 占用、git 冲突
                # → 回滚半写残留 + 降级打回/凭据通道。不回滚的话写回层磁盘上
                # 是未提交的新路径，凭据核销（D4）/复发计数（D5）双双失锚。
                _rollback(f"提交失败（commit_root={wb.get('commit_root')}）")
                return (
                    False,
                    "改写已落盘但提交失败（worktree 层占用/冲突，已回滚）",
                    diff if isinstance(diff, dict) else None,
                )
            # main 层（Task 6.2a 既有语义，2026-09-15 merge-back 死锁修复）：
            # 守卫读取基准就是主树工作区——软化内容即刻生效，提交失败仅
            # WARNING（_commit_softened_declaration 已记），ensure_spec_committed
            # 派发前兜底提交。MUST NOT 回滚（会让软化内容丢失、裁决错判）。
            self._pm.logger.warning(
                "pm_engine",
                f"main 层声明修正提交失败（内容已生效，ensure_spec_committed "
                f"兜底提交）'{spec_name}': {element}",
            )
            return (
                True,
                "main 层提交失败但内容已生效（ensure_spec_committed 兜底）",
                diff if isinstance(diff, dict) else None,
            )
        return True, "", diff if isinstance(diff, dict) else None

    def _readback_correction(
        self, spec_name: str, result, corrected_path: str, kind: str = None
    ) -> tuple:
        """修正后读取一致性复检（Task 3.1/3.2）。

        以守卫读取基准（生效声明解析入口）复读：``corrected_path`` 已被替代路径
        取代（或不再以原 ``kind`` 出现）即通过。复检不一致 → 记 error 明细
        （source/spec_dir）并 ``logger.warning``，MUST NOT 静默销账。

        ``kind``（可选）：reference 软化后条目仍在声明中、仅 kind 变为
        ``reference``——复检 MUST 限定「原 kind」（否则软化的条目仍以新 kind
        在册会被误判未修正；typo 修正传原 kind 同样更精确）。

        Returns:
            ``(ok, detail)``：``detail`` 含 ``source`` / ``spec_dir``（供 error 明细）。
        """
        from core.deliverables import verify_correction_readback

        branch = getattr(result, "branch", None) if result is not None else None
        worktree_path = self._find_worktree_for(result)
        try:
            ok = verify_correction_readback(
                spec_name,
                corrected_path,
                branch=branch,
                worktree_path=worktree_path,
                project_root=self._pm.project_root,
                kind=kind,
            )
        except Exception as e:
            ok = False
            self._pm.logger.warning(
                "pm_engine",
                f"声明修正复检异常 '{spec_name}'（{corrected_path}）: {e}",
            )
        wb = self._writeback_target(spec_name, result)
        detail = {"source": wb.get("source"), "spec_dir": wb.get("spec_dir")}
        if not ok:
            self._pm.logger.warning(
                "pm_engine",
                f"声明修正复检不一致 '{spec_name}': {corrected_path} 仍以原 kind "
                f"出现在生效声明（读取基准 source={detail['source']}, "
                f"spec_dir={detail['spec_dir']}）——修正未生效于读取基准，"
                f"MUST NOT 判为修正成功",
            )
        return ok, detail

    def _audit_deferred_correction(
        self, spec_name: str, elements: list, *, verdict: str, reason: str,
        actual_paths: "dict | None" = None,
        trigger_run_id: str = "", judge_run_id: str = "",
    ) -> None:
        """不可写层（分支命中）修正的裁决落册（Task 2.1/2.2 留册要求）。

        ``source == "branch"``（无落盘位置）时修正交由实现方在分支续做，但该条
        裁决（typo 的 element + actual_path / reference 的 element）MUST 落
        dispute 审计流——供下一轮凭据核销（D4）与跨轮核销收敛动作，而不是仅因
        「本轮无新凭据」无限重派。

        ``actual_paths``（element → 替代路径，可选）：typo 裁决 MUST 携带——
        ``relocation_credential_target``（Task 4.1）据 verdicts 中
        ``element``/``verdict == "typo"``/``actual_path`` 三元组识别凭据，缺
        ``actual_path`` 的落册无法被守卫核销（Task 4.2），留册即空转。

        ``trigger_run_id`` / ``judge_run_id``（可选，缺省空串）：judge 裁决执行
        路径（``_adjudicate_deliverable_missing``）透传当轮 run id 供 dispute
        审计溯源；预分类路径维持空串缺省。
        """
        if not elements:
            return
        actual_paths = actual_paths or {}
        try:
            from core.admin_store import DisputeAuditStore

            DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                {
                    "spec": spec_name,
                    "trigger_run_id": trigger_run_id,
                    "judge_run_id": judge_run_id,
                    "verdicts": [
                        {
                            "element": e,
                            "verdict": verdict,
                            "reasoning": reason,
                            **(
                                {"actual_path": actual_paths[e]}
                                if actual_paths.get(e)
                                else {}
                            ),
                        }
                        for e in elements
                    ],
                    "diff": {"before": "", "after": ""},
                }
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"不可写层修正裁决落册失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _writeback_recur_bump(self, spec_name: str, path: str) -> bool:
        """typo 修正后同路径复发计数递增（fix-relocation-writeback-layer D5，
        Task 5.1/5.2）。

        计数 MUST 用**独立字段**（``_writeback_recur_streak`` +
        ``_writeback_recur_path``，落 STATE.md spec entry），MUST NOT 复用
        ``_retry_count``——后者在恢复续做（``_recovery_resume`` 分支）与重建
        分支时被显式清零，且 ``resolve_env_blocked_reset_path`` 会把本类 loop
        的 blocked 复位为 ready 续走重实现（事故态实证：31 小时在飞期间
        ``_retry_count`` 恒为 0，既有封顶从未生效）。独立字段不随 blocked→ready
        / 恢复续做清零——**仅在 typo 修正复检通过**（``_writeback_recur_reset``）
        **或 SPEC 退出本形态**（守卫放行）时清零。同路径延续 streak、换路径重置。

        Returns:
            True 表示已达 ``agents.max_retries`` 上限（调用方置 blocked，
            不再自动重派）。
        """
        try:
            # 换路径判定读侧保留（同路径延续 streak、换路径重置）；递增本体收进
            # bump_counters 锁内原子读改写（code-review item 3fd0da2d3385，对齐
            # _redispatch_with_retry 的 _retry_count 同型修复 3dae7ab671a1）：原
            # 「read_one 读 → 算 +1 → update_spec 写回」读与写分处两次 STATE 锁
            # 临界区，与并发 _writeback_recur_reset 交错时可丢一次递增或把递增
            # 清零，复发熔断晚一轮触发。
            entry = self._pm.state_machine.read_one(spec_name) or {}
            # STATE.md 行式存储读回值可能为任意字符串，裸 int() 遇非数字文本抛
            # ValueError（code-review item 9a6271490cdd）：异常回退 0。
            try:
                old_streak = int(entry.get("_writeback_recur_streak") or 0)
            except (TypeError, ValueError):
                old_streak = 0
            same_path = entry.get("_writeback_recur_path") == path
            # 换路径清零经「负 delta 补差」（delta = 1 - 旧值）与递增落在同一
            # 临界区——bump_counters 负 delta 结果下限 0，串行下恒得 1（等价原
            # 「先清零再 +1」），且不引入「清零被旧值覆盖」的窗口。
            delta = 1 if same_path else 1 - old_streak
            streak = self._pm.state_machine.bump_counters(
                spec_name, {"_writeback_recur_streak": delta}
            ).get("_writeback_recur_streak", 0)
            if not same_path:
                # 路径字段与递增分写（bump_counters 只收 int delta）：置后写，
                # 写失败时下轮按「换路径」从 1 重计，不带旧路径 streak 误续。
                self._pm.state_machine.update_spec(
                    spec_name, {"_writeback_recur_path": path}
                )
            # 解析口径收敛三车道单一读取器 repair_lane._max_retries（code-
            # review item f68ba79c3e07 双写收敛 + item 00af54aa1442 跨通道
            # 统一：无下限 0=不自动重试、拒 bool/非整值浮点）。
            max_r = _max_retries(self._pm)
            self._pm.logger.warning(
                "pm_engine",
                f"声明修正复发计数 '{spec_name}': {path} 第 {streak}/{max_r} 轮"
                f"（独立字段 _writeback_recur_streak，不随 blocked→ready/恢复续做清零）",
            )
            return streak >= max_r
        except Exception as e:
            # STATE.md 瞬态 IO/锁异常不得穿透 dispute 裁决主体（code-review
            # item 9aebf947d532）：主体已把 spec 置 blocked「LLM 终审进行中」，
            # 异常穿透会让本轮裁决中断、spec 滞留该僵尸文案误导人工判读（对齐
            # 373b4b302c80 姿态）。按「未达上限」放行本轮（非阻塞），后续打回
            # 路径照常落终态，熔断最多晚一轮触发。
            self._pm.logger.warning(
                "pm_engine",
                f"声明修正复发计数失败 '{spec_name}': {path}"
                f"（非阻塞，按未达上限继续）: {type(e).__name__}: {e}",
            )
            return False

    def _writeback_recur_reset(self, spec_name: str) -> None:
        """复发计数清零（Task 5.1）：typo 修正复检通过 / SPEC 退出本形态时调用。

        先读后条件写（无残留字段时零写盘，避免每轮 typo 修正多余一次 STATE 写）。
        """
        try:
            entry = self._pm.state_machine.read_one(spec_name) or {}
        except Exception:
            return
        # STATE.md 行式存储把 int/None 读回成 str（0→'0'、None→'null'），
        # 条件须按存储现实判（既有 _retry_count 读侧 int() 强转同惯例）。
        # 非数字文本读回时强转回退 0，防异常穿透（code-review item 9a6271490cdd）。
        try:
            recur_streak = int(entry.get("_writeback_recur_streak") or 0)
        except (TypeError, ValueError):
            recur_streak = 0
        if recur_streak or (
            entry.get("_writeback_recur_path") not in (None, "", "null")
        ):
            try:
                self._pm.state_machine.update_spec(
                    spec_name,
                    {"_writeback_recur_streak": 0, "_writeback_recur_path": None},
                )
            except Exception as e:
                # 清零写盘失败不阻塞调用方后续放行/改判流程（code-review item
                # 9aebf947d532）：streak 残留下轮复检通过时再清，不影响本轮
                # 终态落定。
                self._pm.logger.warning(
                    "pm_engine",
                    f"声明修正复发计数清零失败 '{spec_name}'（非阻塞）: "
                    f"{type(e).__name__}: {e}",
                )

    def _all_clear_proceed(self, spec_name: str, message: str) -> dict:
        """守卫重跑全清放行块（四预分类器共用样板）。

        code-review item f9e0fc21eff6：四 impl 的「重跑全清 → WARNING 告警 +
        ``status=implementing`` + ``error=None`` + ``{"action": "proceed"}``」
        放行块各自拷贝（仅告警文案不同），收敛单点后放行语义调整不再逐点
        扫齐。告警文案由调用方传入（保留各通道原文案，含已对齐清单插值）。
        """
        self._pm.logger.warning("pm_engine", message)
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "status": "implementing",
                "error": None,
            },
        )
        return {"action": "proceed"}

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
        try:
            return self._preclassify_missing_impl(spec_name, result, missing)
        except Exception as e:
            # fail-open 契约落地（code-review item 779c3de79a5c）：impl 内
            # _effective_declaration / classify_unsatisfiable 等文件与 git
            # 读取不逐点包 try，入口统一兜底，异常不再穿透调用方，按本
            # docstring 承诺回退既有 judge 流程（missing 不变）。
            self._pm.logger.warning(
                "pm_engine",
                f"缺件预分类异常回退 judge '{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return {"action": "fallback"}

    def _preclassify_missing_impl(
        self, spec_name: str, result, missing: list
    ) -> dict:
        """_preclassify_missing 主体（fail-open 兜底在其入口，见上）。"""
        from core.deliverables import classify_unsatisfiable

        # 声明段条目经统一解析入口取（add-declaration-relocation-protocol D1：
        # worktree/分支版本优先、主树回退，与收工守卫同源）——MUST NOT 自行拼接
        # 主树 spec 目录直读（读分支、写主树的错层正是本次事故根因）。
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        # 声明段无条目（存量 spec 正则提取 / 两处均不可用）→ 不预分类，回退 judge
        if not entries:
            return {"action": "fallback"}

        # 软化执行目标 = **写回层**（fix-relocation-writeback-layer Task 2.2）：
        # 写入 MUST 与守卫读取基准同源——source == "worktree" 写该 worktree
        # （提交到该分支）；source == "main" 就地写主树（此时守卫读取基准即主树，
        # 同源）；source == "branch"（无落盘位置，spec_dir is None）MUST NOT 回落
        # 主树目录作为软化落点（读分支、写主树的错层正是本次事故根因）。
        wb = self._writeback_target(spec_name, result)
        # 读取用目录（快照 before/after 文本）：不可写时仅为审计读取，不落盘改写
        spec_dir = wb.get("spec_dir") or str(
            self._pm.project_root / "spec" / "changes" / spec_name
        )

        # 快照软化前 tasks.md 声明段（供审计 diff.before）
        before_text = ""
        tasks_path = Path(spec_dir) / "tasks.md"
        if tasks_path.exists():
            try:
                before_text = tasks_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                before_text = ""

        # 将条目列表转为 path → entry 映射（按 path 查找；构建收进共用
        # helper，四预分类器同判据防复制漂移，code-review item f9e0fc21eff6）
        entry_by_path = _entry_by_path(entries)

        # 缺件入参兼容两种形态：守卫返回 list[dict]（path/kind/violation）与
        # 既有调用/测试的 list[str]。统一规范化为路径列表（匹配逻辑只认路径）。
        # 缺 path 键或 path 值为 null 的畸形条目兜底空串（code-review item
        # fc62a0cdb4c3，与 _redispatch_for_missing 的 .get 取值口径对齐；
        # 0284d932e70f：`or ""` 使键存在但值为 None 的畸形条目同样兜底，
        # 伪路径 "None" 不得流入 blocked 文案 / judge 输入 / 防洗白对账）：
        # 单条畸形数据不得以 KeyError 放大为整批裁决降级；空串不命中任何
        # 声明条目、留在 remaining 交守卫重跑对账（fail-closed，不静默丢弃缺件）。
        missing_paths = [
            (m.get("path") or "") if isinstance(m, dict) else str(m) for m in missing
        ]

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

        if not wb.get("writable"):
            # 生效声明命中层为分支（无落盘位置）→ MUST NOT 软化主树（写读错层）。
            # 该条 reference 裁决落 dispute 审计流（供 D4 跨轮核销），条目留在
            # remaining 交后继缺件处置（打回重派 / 终审），修正由实现方在分支续做。
            self._audit_deferred_correction(
                spec_name,
                list(deterministic),
                verdict="reference",
                reason=(
                    "guard-preclassify-deferred: 生效声明命中层为分支（无落盘位置），"
                    "MUST NOT 软化主树，转打回/凭据通道"
                ),
            )
            self._pm.logger.warning(
                "pm_engine",
                f"预分类软化跳过 '{spec_name}'（写回层不可写，source="
                f"{wb.get('source')}）— MUST NOT 软化主树，转打回/凭据通道: "
                f"{deterministic}",
            )
            remaining.extend(deterministic)
            return {"action": "continue", "remaining": remaining}

        # 逐条软化（单条异常/未落命中层留在 remaining 并 warning）
        # diff_by_element 收集各条改写 diff 并喂入下方审计留痕的 "diff"
        # （code-review item 7d3b13d266dc：旧实现声明后从未被读，审计实际取自
        # 文件级 before_text/after_text，此处补上逐条 diff，使留痕可溯源到条目）。
        diff_by_element: dict = {}
        soft_failed: list = []
        for m in deterministic[:]:  # copy以便异常时移除
            from core.deliverables import soften_declared_kind

            ok, detail, diff = self._apply_declaration_correction(
                spec_name,
                m,
                lambda d, _m=m: soften_declared_kind(d, _m),
                wb=wb,
            )
            if not ok:
                # 软化未落命中层（改写/提交失败）：留在 remaining 转打回，
                # MUST NOT 改落主树兜底（Task 1.4）
                remaining.append(m)
                deterministic.remove(m)
                soft_failed.append(m)
                self._pm.logger.warning(
                    "pm_engine",
                    f"预分类软化未落地 '{spec_name}'（{m} 转打回/凭据通道）: {detail}",
                )
                continue
            diff_by_element[m] = diff

        if soft_failed:
            # 未落地的软化裁决一并落册（供下一轮凭据/人工核销）
            self._audit_deferred_correction(
                spec_name,
                soft_failed,
                verdict="reference",
                reason=(
                    "guard-preclassify-deferred: 软化未落生效声明命中层"
                    "（改写/提交失败），转打回/凭据通道"
                ),
            )

        if not deterministic:
            # 全部软化未落地 → 回退既有缺件处置（remaining 已含全部条目）
            return {"action": "continue", "remaining": remaining}

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
                        # by_element 投影收进共用 helper（两处同构防复制漂移，
                        # code-review item f9e0fc21eff6）
                        "by_element": _diff_by_element_projection(diff_by_element),
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
                f"预分类后守卫重跑异常 '{spec_name}'（软化已落盘，剩余项带 judge）: {e}",
            )
            # code-review item e3ea5719971e：soften 已写盘无法回滚，已软化条目
            # （deterministic）已不再缺失——MUST NOT 放回 remaining 送 judge
            # （旧 fallback 形态调用方忽略 remaining、恒回退原始 missing，已
            # 软化条目白耗一轮终审裁决）。按「软化已落盘、剩余项带 judge」续走，
            # 交由后续守卫重跑收敛。
            return {"action": "continue", "remaining": remaining}

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支（放行块收进共用
            # helper，四预分类器同语义，code-review item f9e0fc21eff6）
            return self._all_clear_proceed(
                spec_name,
                f"预分类缺件全清 '{spec_name}' — 守卫重跑通过，放行 merge",
            )

        # 仍有剩余 → 以守卫复检权威清单带入 judge（对齐 _preclassify_stale/
        # _orphan/_drift 的复检返回范式，code-review item 9842183003df：
        # 预分类时点推导的旧 remaining 不反映软化后守卫现状）
        return {"action": "continue", "remaining": gate_result}

    # ── 孤儿声明机械预分类（deliverable-dispute-orphan-preclassify）────────

    # impl_result 形参在本方法不读取（code-review item e848316b8300）：与
    # _preclassify_missing（用它经 _effective_declaration 提供分支上下文）和
    # _preclassify_drift 保持三预分类器统一签名——调度器 queue.py 以同一形态
    # 调用、测试夹具按位置传参，保留哑参数避免十余处调用点联动改动。
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

        删除后的续走契约 MUST 与 ``_preclassify_missing`` 的 proceed 分支
        逐条对齐（design「删除后的续走契约」节；对照定位用方法名，勿写裸
        行号——对齐 fast_track.py MUST 同步注释同款口径）：

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
        5. 判定/删除/提交环节异常 → 全量回退既有 blocked 待人工路径（fail-open，
           不因预分类故障改变处置）；守卫重跑异常 → 剔除已删条目续走（对齐
           _preclassify_missing 口径，见 impl）。

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
        try:
            return self._preclassify_orphan_impl(
                spec_name, result, impl_result, disputed, missing
            )
        except Exception as e:
            # fail-open 契约落地（code-review item 779c3de79a5c）：同
            # _preclassify_missing——impl 内 _effective_declaration 等文件与
            # git 读取不逐点包 try，入口统一兜底，异常不再穿透调用方，按本
            # docstring 承诺全量回退既有 blocked 待人工路径。
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿预分类异常回退 blocked '{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return {"action": "fallback"}

    def _preclassify_orphan_impl(
        self, spec_name: str, result, impl_result, disputed: list, missing: list
    ) -> dict:
        """_preclassify_orphan 主体（fail-open 兜底在其入口，见上）。"""
        from core.deliverables import is_orphan_declaration, remove_declared_entry

        # 声明段条目经统一解析入口取（add-declaration-relocation-protocol D1：
        # worktree/分支版本优先、主树回退）——MUST NOT 自行拼接主树 spec 目录
        # 直读（读分支、写主树的错层正是 refactor-giant-classes 事故根因）。
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        if not entries:
            # 声明段无条目 → 无声明可删，回退 blocked 待人工
            return {"action": "fallback"}
        # fix-relocation-writeback-layer Task 2.4：删除条目落点 = 写回层（与守卫
        # 读取基准同源，1.1 判据）。source == "branch"（声明只在分支对象库、
        # 无落盘位置）MUST NOT 回落主树目录删除并提交（读分支、写主树错层）
        # ——回退既有 blocked 待人工/续走通道，不留主树提交。
        wb = self._writeback_target(spec_name, result)
        # 读取用目录（孤儿判定基准）：不可写时仅为只读判定，不落盘改写
        spec_dir = wb.get("spec_dir") or str(
            self._pm.project_root / "spec" / "changes" / spec_name
        )

        entry_by_path = _entry_by_path(entries)

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

        # Task 2.4：写回层不可写（branch 命中无落盘位置/两处均不可用）→ 不删
        # 主树、不留主树提交，孤儿条目维持 disputed 回退既有 blocked 待人工。
        if not wb.get("writable"):
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿删除跳过 '{spec_name}'（写回层不可写，source="
                f"{wb.get('source')}）— MUST NOT 删主树声明并提交，回退 "
                f"blocked 待人工: {orphans}",
            )
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
                # before_text 为循环前批量快照——非本条删除时刻的文件现状
                # （语义见 _backup_to_history docstring）。
                self._backup_to_history(spec_name, m, before_text)
                # Task 1.4/2.4：删除经统一落点执行器（写回层 + 立即提交）；
                # 改写/提交失败（worktree 占用、git 冲突）→ 该条保留人工，
                # MUST NOT 改落主树兜底、MUST NOT 静默判删除成功。
                ok_del, detail_del, diff = self._apply_declaration_correction(
                    spec_name,
                    m,
                    lambda d, _m=m: remove_declared_entry(d, _m),
                    wb=wb,
                )
                if not ok_del:
                    non_orphans.append(m)
                    orphans.remove(m)
                    self._pm.logger.warning(
                        "pm_engine",
                        f"孤儿声明删除未落地 '{spec_name}'（{m} 保留人工）: "
                        f"{detail_del}",
                    )
                    continue
                diff_by_element[m] = diff
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
                        # 逐元素 diff 输出（code-review item d07089f200f3，同
                        # _preclassify_missing 先例 7d3b13d266dc）：文件级
                        # before/after 之外补逐条删除 diff，孤儿删除审计可溯源
                        # 到条目——此前逐元素收集后从未被读。
                        # by_element 投影收进共用 helper（两处同构防复制漂移，
                        # code-review item f9e0fc21eff6）
                        "by_element": _diff_by_element_projection(diff_by_element),
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
                f"孤儿删除后守卫重跑异常 '{spec_name}'（已删项剔除后续走）: {e}",
            )
            # code-review item d653d8709445：删除已写盘无法回滚，已删条目
            # （deleted）在生效声明中已不存在——MUST NOT 全量 fallback 令调用方
            # 以原始 disputed 全量 blocked 待人工（对已自愈声明做人工升级，白耗
            # 一次人工裁决）。对齐 _preclassify_missing（e3ea5719971e）/
            # _preclassify_stale（b543b7fa73f6）口径：剔除已删条目续走——
            # remaining_missing 取 missing 去除 deleted（守卫重跑不可用时的最佳
            # 已知清单），其中仍带异议的项（non_orphans 与 deleted 不相交）走
            # blocked、无异议项走既有 LLM 终审。
            deleted_set = set(deleted)
            return {
                "action": "continue",
                "remaining_missing": [
                    g
                    for g in missing
                    if ((g.get("path") or "") if isinstance(g, dict) else str(g))
                    not in deleted_set
                ],
                "remaining_disputed": list(non_orphans),
            }

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支（对齐
            # _preclassify_missing，放行块收进共用 helper）
            return self._all_clear_proceed(
                spec_name,
                f"孤儿声明删除全清 '{spec_name}' — 守卫重跑通过，放行 merge",
            )

        # 仍有缺件 → 以重跑后的 remaining 续走既有后续（remaining_disputed 供
        # 调用方判断 blocked vs LLM 终审；非孤儿 disputed 项同样计入）
        remaining_paths = [
            (g.get("path") or "") if isinstance(g, dict) else str(g)
            for g in gate_result
        ]
        remaining_disputed = [r for r in remaining_paths if r in (disputed + non_orphans)]
        return {
            "action": "continue",
            "remaining_missing": gate_result,
            "remaining_disputed": remaining_disputed,
        }

    # ── 漂移笔误机械对齐（evo-deliverable-declaration-drift-align D1/D2）────────

    # impl_result 形参在本方法不读取（code-review item e848316b8300）：与
    # _preclassify_orphan 同理，为三预分类器统一签名保留的哑参数（调度器与
    # 测试夹具按位置传参，见上方 _preclassify_orphan 注释）。
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
            {"action": "fallback"} → 无可对齐条目 / 判定·改写·提交环节异常，全量
            回退既有 blocked 待人工路径（missing 不变）；守卫重跑异常除外——
            已对齐条目剔除后 continue 续走（对齐姊妹通道口径，见 impl）。
        """
        try:
            return self._preclassify_drift_impl(
                spec_name, result, impl_result, disputed, missing
            )
        except Exception as e:
            # fail-open 契约落地（code-review item 779c3de79a5c）：同
            # _preclassify_missing——impl 内 _effective_declaration 等文件与
            # git 读取不逐点包 try，入口统一兜底，异常不再穿透调用方，按本
            # docstring 承诺全量回退既有 blocked 待人工路径。
            self._pm.logger.warning(
                "pm_engine",
                f"漂移预分类异常回退 blocked '{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return {"action": "fallback"}

    def _preclassify_drift_impl(
        self, spec_name: str, result, impl_result, disputed: list, missing: list
    ) -> dict:
        """_preclassify_drift 主体（fail-open 兜底在其入口，见上）。"""
        # merge-base 经公开薄包装导入（code-review item 2fe1cd927997）：私有
        # 本体 _git_branch_merge_base 仍是 deliverables 内部实现细节。
        from core.deliverables import branch_merge_base, is_drift_candidate

        branch = getattr(result, "branch", None)
        if not branch:
            return {"action": "fallback"}

        # 生效声明（与守卫同源：worktree > 分支 > 主树回退）——重定位改写的
        # 执行目标与条目级 kind 判定基准（D2：读写同位，MUST NOT 直写主树）
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        # 非 dict / 缺 path 的畸形条目过滤（code-review item f204e70e4aa8）：
        # 判据收进共用 helper _entry_by_path（四预分类器同构，防复制漂移）。
        by_path = _entry_by_path(entries)
        if not entries:
            return {"action": "fallback"}

        try:
            merge_base = branch_merge_base(self._pm.project_root, branch)
        except Exception:
            merge_base = None
        if not merge_base:
            # 分支改动集合基准不可用 → 无法判定「改动落在哪个模块」，
            # fail-open 回人工（不机械改写）
            return {"action": "fallback"}

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
                f"漂移对齐后守卫重跑异常 '{spec_name}'（已对齐项剔除后续走）: {e}",
            )
            # code-review item d653d8709445：改写已写盘无法回滚，已对齐旧路径
            # （aligned_old）在生效声明中已不存在——MUST NOT 全量 fallback 令
            # 调用方以原始 disputed 全量 blocked 待人工（对已自愈声明做人工升级，
            # 白耗一次人工裁决）。对齐 _preclassify_missing（e3ea5719971e）/
            # _preclassify_stale（b543b7fa73f6）口径：剔除已对齐条目续走——
            # remaining_missing 取 missing 去除 aligned_old（守卫重跑不可用时的
            # 最佳已知清单），其中仍带异议的项走 blocked、无异议项走既有 LLM 终审。
            aligned_set = set(aligned_old)
            remaining_missing = [
                g
                for g in missing
                if ((g.get("path") or "") if isinstance(g, dict) else str(g))
                not in aligned_set
            ]
            remaining_paths = [
                (g.get("path") or "") if isinstance(g, dict) else str(g)
                for g in remaining_missing
            ]
            return {
                "action": "continue",
                "remaining_missing": remaining_missing,
                "remaining_disputed": [
                    r for r in remaining_paths if r in (disputed + remaining)
                ],
            }

        if not gate_result:
            # 全清 → 走「裁决执行后守卫重跑通过」放行分支（对齐
            # _preclassify_orphan，放行块收进共用 helper）
            return self._all_clear_proceed(
                spec_name,
                f"漂移声明对齐全清 '{spec_name}'（{aligned_old}）— 守卫重跑通过，"
                f"放行 merge",
            )

        # 仍有缺件 → 以重跑后的 remaining 续走既有后续（remaining_disputed 供
        # 调用方判断 blocked vs LLM 终审）
        remaining_paths = [
            (g.get("path") or "") if isinstance(g, dict) else str(g)
            for g in gate_result
        ]
        remaining_disputed = [r for r in remaining_paths if r in (disputed + remaining)]
        return {
            "action": "continue",
            "remaining_missing": gate_result,
            "remaining_disputed": remaining_disputed,
        }

    def _backup_to_history(self, spec_name: str, element: str, content: str) -> None:
        """删除前 .history 备份留痕（对齐 admin 处置 .history 备份惯例）。

        备份目标：``<project_root>/.history/<spec_name>/<元素 basename>.<元素
        路径哈希前 8 位>.<时间戳>.orphan-preclassify.bak``（.history 已在
        .gitignore 排除，不提交）。
        备份内容为调用方传入的 tasks.md 全文快照（与审计 diff.before 同源）。
        唯一调用方 _preclassify_orphan_impl 传入的是删除循环**前**的批量快照：
        第二条起的备份并非该条目删除时刻的文件现状（前序已删条目仍在其中），
        逐条核对删除前状态以写回层 git 提交历史为准。备份失败仅 WARNING，
        不阻塞删除本身（备份是附加留痕，fail-open）。
        """
        try:
            backup_dir = self._pm.project_root / ".history" / spec_name
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d%H%M%S")
            # 同秒同名防覆盖（code-review item 6f9b558f5ca1）：ts 精度为秒，
            # _preclassify_orphan 同一循环对不同孤儿条目连续备份，basename
            # 相同（如不同目录下的同名文件）会互相覆盖、丢失先删条目的删除
            # 前快照——并入元素完整路径哈希使各条目备份名互不相同。
            elem_tag = hashlib.sha1(element.encode("utf-8")).hexdigest()[:8]
            backup_path = (
                backup_dir
                / f"{Path(element).name}.{elem_tag}.{ts}.orphan-preclassify.bak"
            )
            backup_path.write_text(content, encoding="utf-8")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"孤儿删除 .history 备份失败 '{spec_name}'（{element}，非阻塞）: {e}",
            )

    # ── 陈日声明前置分类与重定位（add-declaration-relocation-protocol D4）──────

    def _preclassify_stale(self, spec_name: str, result, missing: list) -> dict:
        """陈日声明前置分类入口（fail-open 兜底，对齐其余三个预分类器）。

        Returns:
            透传 ``_preclassify_stale_impl`` 的
            {"action": "proceed"} / {"action": "continue", "remaining": [...]}；
            入口异常时 fail-open 回退既有流程：
            {"action": "continue", "remaining": missing}（missing 原样带入
            后继预分类软化 / LLM 终审，不阻塞整条收工链）。
        """
        try:
            return self._preclassify_stale_impl(spec_name, result, missing)
        except Exception as e:
            # fail-open 契约落地（对齐 _preclassify_missing/_orphan/_drift 入口
            # 兜底，code-review item 779c3de79a5c）：impl 内 _effective_declaration
            # 等文件与 git 读取不逐点包 try，入口统一兜底，异常不再穿透调用方
            # （_adjudicate_deliverable_missing），missing 原样续走既有流程。
            self._pm.logger.warning(
                "pm_engine",
                f"陈日预分类异常回退既有流程 '{spec_name}': "
                f"{type(e).__name__}: {e}",
            )
            return {"action": "continue", "remaining": missing}

    def _preclassify_stale_impl(self, spec_name: str, result, missing: list) -> dict:
        """_preclassify_stale 主体（fail-open 兜底在其入口，见上）。

        陈日声明前置分类（3.5/4.1）：命中陈日信号的缺件走重定位通道。

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
        # 缺 path 键的畸形条目兜底空串（code-review item 7183c1a30d0b，与
        # _preclassify_missing 的 .get 取值口径对齐）：单条畸形数据不得以
        # KeyError 经入口 fail-open 放大为整批预分类降级；空串不命中任何
        # 声明条目、按下方 entry is None 同款保留进 remaining。
        missing_paths = [
            (m.get("path") or "") if isinstance(m, dict) else str(m) for m in missing
        ]
        if not missing_paths:
            return {"action": "continue", "remaining": missing}

        # 生效声明（与守卫同源：worktree > 分支 > 主树回退）——重定位改写的
        # 执行目标与条目级 kind 判定基准（D1/D2：读写同位）
        resolved = self._effective_declaration(spec_name, result)
        entries = resolved.get("entries") or []
        # 非 dict / 缺 path 的畸形条目过滤（code-review item f204e70e4aa8）：
        # 判据收进共用 helper _entry_by_path（四预分类器同构，防复制漂移）。
        by_path = _entry_by_path(entries)

        relocated_any = False
        relocated_old: list = []  # 已走重定位的旧路径（复检时不再计入缺件）
        remaining: list = []
        for p in missing_paths:
            entry = by_path.get(p)
            # 仅声明段条目可判陈日；正则回退路径（无 kind 概念）不命中
            if entry is None:
                remaining.append(p)
                continue
            try:
                stale = is_stale_declaration(entry, self._pm.project_root)
            except Exception as exc:
                # 单条判定异常 fail-safe 回退：保留 remaining 走既有流程（3.5，
                # 不阻塞整条收工链），对齐 _preclassify_drift 同位写法
                remaining.append(p)
                self._pm.logger.warning(
                    "pm_engine",
                    f"陈日信号判定异常 '{spec_name}'（{p} 保留既有流程）: {exc}",
                )
                continue
            if not stale:
                # missing_paths 已在上方归一为字符串，此处 `p if not isinstance(...)
                # else p` 两分支恒等（code-review item 0a8b4d70dc57），简化为直接追加。
                remaining.append(p)
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
            # code-review item b543b7fa73f6：重定位已写盘无法回滚，已重定位
            # 旧路径在生效声明中已不存在——MUST NOT 回送原始 missing 送 judge
            # （对已不存在的声明路径终审大概率 unclear → 白耗一轮 LLM 终审并
            # 误升级人工）。剔除已重定位条目续走（remaining 即 missing_paths
            # 去除 relocated_old），对齐 _preclassify_missing 的 e3ea5719971e
            # 修复口径。
            return {"action": "continue", "remaining": remaining}
        if not gate:
            # 全清放行块收进共用 helper（对齐其余三预分类器，code-review item
            # f9e0fc21eff6）
            return self._all_clear_proceed(
                spec_name,
                f"陈日声明重定位全清 '{spec_name}'（{relocated_old}）— "
                f"守卫复检通过，放行 merge",
            )
        return {"action": "continue", "remaining": gate}

    def _text_rewrite_applicable(self, resolved: dict, old_path: str) -> bool:
        """「条目仍在生效声明 + 声明命中层可写」判据单一落点。

        code-review item 1ffba1bbf0da：``_relocate_or_register`` 的改写/登记
        分流判据与陈日裁决执行处的凭据登记判别（``cred_only``，ca3447e2d676）
        原为手工镜像双写，任一侧调整（新增 source 取值、spec_dir 判空口径）
        即令「审计形态判定」与「实际改写/登记路径」分裂。收编为单一谓词：

        - 条目仍在生效声明（entries 含 old_path）；
        - 声明命中层可写（fix-relocation-writeback-layer Task 2.3，与 1.1
          判据对齐去重）：source ∈ {worktree, main} 且有落盘位置 spec_dir。
          source == "branch"（spec_dir is None）MUST NOT 写主树——判据与
          resolve_writeback_target 同源，防「spec_dir or 主树」型回退再次
          漂移进来。

        True → 文本改写路径（3.2/3.3）；False → 凭据登记路径（3.6，未发生
        tasks.md 文本改写，审计 MUST NOT 记文件级 before/after diff）。
        """
        entries = resolved.get("entries") or []
        entry_still_present = any(
            isinstance(e, dict) and e.get("path") == old_path for e in entries
        )
        wb_writable = resolved.get("source") in ("worktree", "main") and bool(
            resolved.get("spec_dir")
        )
        return entry_still_present and wb_writable

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
        替换）。二者均落 dispute 审计流（含 before/after diff 或凭据摘要）；仅
        文本改写路径随后分支提交固化（4.2）——凭据登记未改写 tasks.md，无提交
        可固化（code-review item 2f920214d8d1）。改写/登记失败 → False（调用方
        保留在 remaining）。

        ``verdict``/``evidence``/``extra_audit``（可选，evo-deliverable-declaration-
        drift-align 1.4）：缺省 ``verdict="typo"`` 保持既有调用形态；漂移机械对齐
        通道传 ``verdict="drift-aligned"`` + 候选唯一性证据（evidence）与对齐细节
        （extra_audit 合并进落册记录，如候选清单/历史命中数/merge_base），供审计
        溯源。``extra_audit`` 非 dict 时忽略。

        Returns:
            重定位成功（改写或登记 + 提交完成；审计落册尽力而为，失败仅
            WARNING 不影响成败）返回 True；异常/失败 False。
        """
        from core.deliverables import (
            register_relocation_credential,
            relocate_declared_path,
        )

        spec_dir = resolved.get("spec_dir")
        # 改写/登记分流判据单一落点（code-review item 1ffba1bbf0da）：原
        # entry_still_present/wb_writable 手工镜像收编进
        # _text_rewrite_applicable——陈日裁决执行处的 cred_only 判别
        # （ca3447e2d676）由同一谓词推导，消除双写漂移。
        text_rewrite = self._text_rewrite_applicable(resolved, old_path)
        # code-review item 2f920214d8d1：仅文本改写路径动了 tasks.md，才存在
        # 可固化的提交；凭据登记路径（3.6）跳过提交——对未改动的 tasks.md
        # add+commit 恒 nothing-to-commit，只会打出误导性「未落分支」WARNING。
        tasks_md_rewrote = False
        try:
            if text_rewrite:
                # 3.2/3.3：文本改写（生效声明所在位置）——kind 保持、同名去重
                diff = relocate_declared_path(spec_dir, old_path, new_path)
                tasks_md_rewrote = True
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
                    # diff 落册形态登记（code-review item e61146647649）：
                    # DisputeAuditStore 的 diff 字段现存两种 schema，消费方
                    # 须双形态兼容——
                    # 1) 元素键控 {old_path: {"before","after"}}：本处（重定位）
                    #    与 _adjudicate_deliverable_missing 裁决执行审计（另含
                    #    凭据回执 {"type":"credential",...} 形态，未发生文本
                    #    改写时原样透传不投影）；
                    # 2) 文件级 {"before","after","by_element"}：四预分类器审计
                    #    （_preclassify_missing/_orphan/_drift/_stale），
                    #    by_element 为逐元素投影（_diff_by_element_projection）。
                    # 仓库内暂无对 diff 字段的结构化读取
                    # （_has_relocation_credential 只消费 verdicts/actual_path）；
                    # 元素键控形态已被 drift 对齐测试按路径取值消费
                    # （test_deliverable_drift_align），统一形态须联动改测、非
                    # 最小修复——先登记两种 schema 供后续消费方遵循。
                    "diff": {
                        old_path: {
                            "before": (diff or {}).get("before"),
                            "after": (diff or {}).get("after"),
                        }
                    },
                }
                if isinstance(extra_audit, dict):
                    audit_rec.update(extra_audit)
                # code-review item 8bbf9104ee7f：审计落册单独包 try（对齐同文件
                # _audit_deferred_correction 及各预分类审计块「审计失败仅
                # WARNING 非阻塞」统一口径）——此时改写已生效
                # （tasks_md_rewrote=True）且不可回滚，审计写盘异常 MUST NOT
                # 经外层 except 整体 return False 令调用方把旧路径留在
                # remaining / 判 unclear 转 blocked（对已不存在的声明路径终审
                # 白耗一轮 LLM / 误升级人工）。重定位成败只取决于改写/凭据
                # 登记本身。
                try:
                    DisputeAuditStore(self._pm.project_root, self._pm.logger).append(
                        audit_rec
                    )
                except Exception as audit_exc:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"重定位审计落册失败 '{spec_name}'（{old_path} → "
                        f"{new_path}，改写已生效不回滚，审计非阻塞）: {audit_exc}",
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
        # 分支提交固化（4.2）：文本改写落盘后立即提交到实现分支（写盘即固化）。
        # 传入 resolved 供 _commit_declaration_rewrite 按写回层（source）判定
        # 提交落点（code-review item b306482f0d0e）。凭据登记路径（3.6）未改写
        # tasks.md，跳过提交——否则空提交恒失败并误报「未落分支」
        # （code-review item 2f920214d8d1）。
        if tasks_md_rewrote:
            self._commit_declaration_rewrite(
                spec_name, old_path, new_path, result, resolved=resolved
            )
        return True

    def _commit_declaration_rewrite(
        self, spec_name: str, element: str, new_path: str, result,
        resolved: "dict | None" = None,
    ) -> None:
        """声明改写/登记后提交固化（add-declaration-relocation-protocol D2）。

        改写目标 = 生效声明所在位置（worktree 内文件 → 分支 → 主树回退，见
        ``resolve_effective_declaration``）。``resolved`` 为该解析结果（含
        ``source``/``spec_dir``，``_relocate_or_register`` 传入），提交落点随
        **写回层**判定：

        - ``source == "main"``（命中主树层）：改写内容已落在主树工作区 →
          同层提交（commit 根 = ``project_root``，与 ``resolve_writeback_target``
          的 commit_root 语义一致），不经实现分支 worktree——分支内 add/commit
          对主树工作区改动恒 nothing-to-commit，徒增「未落分支」噪音；
        - 其余 source 在实现分支上提交：

          - worktree 存在（full 车道守卫/裁决窗口保留 / fast-track 现场保留）：
            ``git -C <worktree> add + commit``（提交落实现分支 HEAD）；
          - worktree 已清理、仅分支留存：经 ``worktree_manager`` 重挂该分支
            worktree、提交后移除（MUST NOT ``git -C <project_root> commit``——
            只作用于主树当前分支，不会落到实现分支；仓库内亦无 commit-tree 型
            无 worktree 写分支助手）；
          - 重挂失败（code-review item b306482f0d0e）：MUST NOT 回退主树提交
            （即上一条禁令——主树提交只落主树当前分支，且会把主树 tasks.md
            工作区现状一并带上去），仅 WARNING 非阻塞，改写内容保留在原层
            工作区（凭据登记路径未改写 tasks.md，本就无需提交）。

        - 提交失败仅 WARNING：内容仍在工作区，派发前 ``ensure_spec_committed``
          兜底（与既有 ``_commit_softened_declaration`` 非阻塞语义一致）。
        """
        rel = f"spec/changes/{spec_name}/tasks.md"
        # 写回层判定（code-review item b306482f0d0e）：生效声明命中主树层时
        # 改写内容就在主树工作区，同层提交（commit 根 = project_root）。
        # 主树层提交不依赖分支上下文，MUST 先于下方 `if not branch` 早退
        # （code-review item 0455fd1dd3e0）：生效声明命中主树层（resolved
        # source=main）而 result 无分支上下文时，无分支早退会静默跳过已
        # 落盘改写的主树层提交——改写停留为无留痕的工作区脏改动，审计与
        # 日志层面无法区分「已提交/提交失败/根本未尝试提交」，与同文件
        # main 层既有口径（_apply_declaration_correction 543-556：提交失败
        # 仅 WARNING、内容已生效、ensure_spec_committed 兜底）不一致。
        if (resolved or {}).get("source") == "main":
            self._commit_softened_declaration(
                spec_name, element, repo_root=self._pm.project_root
            )
            return
        branch = getattr(result, "branch", None)
        if not branch:
            return
        worktree_path = self._find_worktree_for(result)
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
            # 重挂失败（code-review item b306482f0d0e）：MUST NOT 回退主树提交
            # ——git -C project_root 只落主树当前分支、不落实现分支，且会把主树
            # tasks.md 工作区现状一并带上去。仅 WARNING 非阻塞，内容保留原层。
            self._pm.logger.warning(
                "pm_engine",
                f"声明段重定位提交未落实现分支 '{spec_name}'（{element} → "
                f"{new_path}，分支 {branch} 重挂 worktree 失败）——改写内容"
                f"保留在原层工作区，非阻塞",
            )
            return
        import subprocess as _sp

        try:
            add = _sp.run(
                ["git", "-C", str(worktree_path), "add", "--", rel],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            commit = None
            if add.returncode == 0:
                commit = _sp.run(
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
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
            # 提交结果须经校验（code-review item d75fc648a6bf）：旧实现只看
            # add.returncode 就无条件打「已提交」INFO——git add 失败或 commit
            # 失败时重定位实际未落分支，误导性日志掩盖了这一点。仅当
            # add 与 commit 均 returncode==0 才记成功；否则 WARNING（非阻塞
            # 回退经 ensure_spec_committed 仍适用）。
            if add.returncode == 0 and commit is not None and commit.returncode == 0:
                self._pm.logger.info(
                    "pm_engine",
                    f"声明段重定位已在实现分支提交 '{spec_name}'（{element} → "
                    f"{new_path}，worktree {worktree_path}）",
                )
            else:
                add_rc = add.returncode
                commit_rc = commit.returncode if commit is not None else "n/a"
                self._pm.logger.warning(
                    "pm_engine",
                    f"声明段重定位分支提交未成功 '{spec_name}'（{element} → "
                    f"{new_path}，worktree {worktree_path}，add.rc={add_rc}, "
                    f"commit.rc={commit_rc}）——重定位可能未落分支",
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
        # 将 remaining 规范化为路径列表（兼容 list[str] 与 list[dict]）；
        # 缺 path 键的畸形条目兜底空串（code-review item fc62a0cdb4c3，与
        # _redispatch_for_missing 的 .get 取值口径对齐），单条畸形数据不得
        # 以 KeyError 放大为整批终审裁决降级。
        remaining_paths = [
            (r.get("path") or "") if isinstance(r, dict) else str(r) for r in remaining
        ]
        # 空缺件早退（code-review item af1bab4a33c7）：预分类后剩余缺件为空清单
        # （上游守卫复检异常返回空 remaining / 调用方直入空 missing）MUST NOT 置
        # blocked 空「缺件 []」误导文案并派空输入 judge run（白烧一次 LLM 终审）
        # ——重跑守卫对账：全清走放行分支；仍有缺件以复检权威清单续走终审；
        # 对账异常不得盲放行（防洗白），按真实归因置 blocked 转人工。
        if not remaining_paths:
            try:
                gate_recheck = self._pm._deliverable_gate_missing(spec_name, result)
            except Exception as e:
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "blocked",
                        "tester_run": None,
                        "error": (
                            "交付物守卫缺件对账异常（预分类后剩余清单为空）— "
                            f"已 blocked 待人工裁决: {type(e).__name__}: {e}"
                        ),
                    },
                )
                self._pm.logger.error(
                    "pm_engine",
                    f"空剩余缺件守卫对账异常 '{spec_name}'（等价 unclear 转人工）: "
                    f"{type(e).__name__}: {e}",
                )
                return {"action": "handled"}
            if not gate_recheck:
                return self._all_clear_proceed(
                    spec_name,
                    f"预分类后剩余缺件为空 '{spec_name}' — 守卫对账通过，放行 merge",
                )
            # 复检仍有缺件 → 以守卫权威清单续走终审（不空派 judge）
            remaining = gate_recheck
            # 与上方规范化同口径：缺 path 键兜底空串（code-review item
            # fc62a0cdb4c3）——复检权威清单同源同型，畸形条目不得令整批
            # 裁决降级。
            remaining_paths = [
                (r.get("path") or "") if isinstance(r, dict) else str(r)
                for r in remaining
            ]
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

        # time_ns 亚秒分量（code-review item a26a8087cbec）：秒级 id 同秒重入时
        # 与残留旧结果文件的 run stamp 同串，393 行严格匹配会误放行陈旧裁决。
        judge_run_id = f"dispute-judge-{spec_name}-{time.time_ns()}"
        # 1. 终审期间 spec 置 blocked（error 含 run id），阻断重派竞态
        try:
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
        except Exception as e:
            # STATE.md 瞬态 IO/锁异常不穿透裁决主体（code-review item
            # c942deb9c1ff，对齐 _record_impl_diagnosis ac84e8dc1873 /
            # _writeback_recur_bump 9aebf947d532「非关键 STATE 写盘失败仅
            # WARNING 非阻塞」口径）：置 blocked 仅用于阻断轮询重派竞态，
            # 写失败时降级续走 —— judge run 照常派发并裁决兜底，裁决链
            # （typo 修正 / reference 软化 / missing 重派 / unclear 转人工）
            # 照常落终态，仅短暂存在重派竞态窗口（重派可恢复，有界）。
            self._pm.logger.warning(
                "pm_engine",
                f"终审置 blocked 写盘失败 '{spec_name}'（非阻塞，继续派 "
                f"{judge_run_id} 兜底）: {type(e).__name__}: {e}",
            )
        self._pm.logger.warning(
            "pm_engine",
            f"交付物守卫缺件 '{spec_name}' 进入 LLM 终审（{judge_run_id}）",
        )

        # 2. 组装输入并派单轮 dispute-judge run（仅含预分类后剩余项）
        judge_input = self._build_dispute_judge_input(
            spec_name, impl_result, remaining,
            kind_by_path=kind_by_path, result=result,
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
        # 写回层不可写而 deferred 的 typo 条目（旧路径）——供守卫重跑后的
        # 复发计数（D5）识别「typo 裁决过但读取基准仍判 missing」的条目集。
        deferred_typo_elements: list = []
        diff_by_element: dict = {}
        # 生效声明上下文（改写目标 spec_dir + 条目级 kind/陈日判定基准）
        try:
            effective_resolved = self._effective_declaration(spec_name, result)
        except Exception as e:
            # 终审解析失败（畸形 git/文件态）不得让 spec 滞留「LLM 终审进行中」
            # 僵尸文案误导人工判读（code-review item 373b4b302c80）：改写 error
            # 为真实归因后置 blocked 转人工（等价 unclear 全量待裁缺件转人工）。
            err_final = (
                f"交付物守卫缺件 [{', '.join(remaining_paths)}] LLM 终审解析失败"
                f"（judge run {judge_run_id}）— 已 blocked 待人工裁决: "
                f"{type(e).__name__}: {e}"
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {"status": "blocked", "tester_run": None, "error": err_final},
            )
            self._pm.logger.error(
                "pm_engine",
                f"交付物守卫缺件终审解析失败 '{spec_name}'"
                f"（judge run {judge_run_id}，等价 unclear 转人工）: "
                f"{type(e).__name__}: {e}",
            )
            return {"action": "handled"}
        eff_spec_dir = effective_resolved.get("spec_dir") or str(
            self._pm.project_root / "spec" / "changes" / spec_name
        )
        eff_entries = effective_resolved.get("entries") or []
        # 判据收进共用 helper _entry_by_path（与四预分类器同源，防复制漂移；
        # code-review item ccfdbcee0430）。
        eff_by_path = _entry_by_path(eff_entries)
        for m in remaining_paths:
            v = _verdict_of(m)
            verdict = v.get("verdict")
            entry = eff_by_path.get(m)
            # kind 权威取生效声明条目（eff_by_path，二次读取已就位），
            # kind_by_path 尽力读取（try/except pass，首读异常即整表为空）
            # 仅作回退（code-review item 97196707901c）：防洗白闸门与
            # _readback_correction 复检须用同一权威 kind，首读异常而次读
            # 成功时 delete 条目不得误判 "new" 绕过闸门软化声明。
            kind_m = (entry or {}).get("kind") or kind_by_path.get(m, "new")
            entry = entry or {"path": m, "kind": kind_m}
            try:
                if verdict == "typo":
                    actual_path = str(v.get("actual_path") or "").strip()
                    if not actual_path:
                        # judge 判 typo 但未给 actual_path：执行层改写为
                        # unclear 转人工。留痕对齐 delete-kind reference 拒绝
                        # 分支（code-review item 89b2076a7b9f）：登记
                        # executed_verdicts（带 judge_original/rewrite_reason）
                        # + WARNING——否则本轮全部条目都走此路径时
                        # executed_verdicts 为空、dispute 审计块整块跳过，
                        # 「judge 曾判 typo」与「执行层改写为 unclear」完全
                        # 不可追溯。
                        verdict_by_element[m] = {
                            "verdict": "unclear",
                            "judge_original": "typo",
                            "rewrite_reason": "typo-missing-actual-path",
                        }
                        executed_verdicts.append(
                            {
                                "element": m,
                                "verdict": "unclear",
                                "judge_original": "typo",
                                "rewrite_reason": "typo-missing-actual-path",
                            }
                        )
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispute judge 裁决 typo 缺 actual_path "
                            f"'{spec_name}': {m} 无法定位改写落点，改写为 "
                            f"unclear 转人工",
                        )
                        continue
                    from core.deliverables import is_stale_declaration

                    # 4.3 重定位接入裁决：typo 裁决命中陈日信号（modify + 基线
                    # 不存在）→ 按重定位凭据三要素执行——生效声明仍含该条目走
                    # 3.2/3.3 文本改写（relocate_declared_path）；已无该条目
                    # （实现方先行对齐）走 3.6 凭据登记。非陈日走既有 typo 修正。
                    if is_stale_declaration(entry, self._pm.project_root):
                        # 凭据登记路径判别（code-review item ca3447e2d676）：与
                        # _relocate_or_register 共用单一谓词
                        # _text_rewrite_applicable（1ffba1bbf0da 去镜像双写，
                        # fix-relocation-writeback-layer Task 2.3 判据）——生效
                        # 声明已无该条目、或
                        # 声明来源为分支版本无落盘位置（source == "branch"，
                        # spec_dir=None，eff_spec_dir 此时只是主树回退目录）时
                        # 走 3.6 凭据登记，不改任何 tasks.md。此路径下文件级
                        # before/after 恒相等，落 dispute 审计会呈现「声明已
                        # 改写」假象——diff 改记凭据回执形态，不做文件快照。
                        cred_only = not self._text_rewrite_applicable(
                            effective_resolved, m
                        )
                        if not cred_only:
                            # 改写前快照 tasks.md 全文（code-review item
                            # 9aab1d5262d0）：旧实现在 _relocate_or_register
                            # **之后**读取并同时赋给 before/after，导致
                            # before == after、改写前内容不可考。先拍 before，
                            # 改写后再读 after，审计 diff 才有意义。
                            try:
                                audit_before = Path(
                                    eff_spec_dir, "tasks.md"
                                ).read_text(encoding="utf-8")
                            except (OSError, UnicodeDecodeError):
                                audit_before = ""
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
                        if cred_only:
                            # 凭据登记回执（未发生 tasks.md 文本改写）：与
                            # register_relocation_credential 落册记录同要素
                            # （old_path/new_path/source），便于审计对账；
                            # MUST NOT 记 before/after 恒等文件级 diff。
                            diff_by_element[m] = {
                                "type": "credential",
                                "old_path": m,
                                "new_path": actual_path,
                                "source": "judge-actual-path",
                            }
                            # 子形态分叉（code-review item 3555ba0caac7）：
                            # cred_only 有两种成因——(a) 条目已不在生效声明
                            # （实现方先行对齐）→ 凭据登记即修正完成，下方
                            # readback 复检会通过；(b) 条目仍在生效声明、
                            # _text_rewrite_applicable 仅因可写性不成立
                            # （source == "branch" 无落盘位置）→ 声明本未被
                            # 改写，readback 对守卫基准复读恒仍见旧路径原
                            # kind（确定性失败）。后者与非陈日 typo 的「写回
                            # 层不可写」处置同型（Task 2.1）：verdict 保持
                            # typo + deferred 转打回/凭据通道，凭据核销
                            # （D4）与复发熔断（D5）下一轮才有运行机会——
                            # readback-failed 的 unclear 会落 blocked 待人工
                            # 令自动化流程停摆，凭据在册却无人核销。条目在册
                            # 判据用 eff_by_path（生效声明条目映射，与
                            # _text_rewrite_applicable 的 entry_still_present
                            # 同源键控），不另行镜像可写性判定。
                            if m in eff_by_path:
                                verdict_by_element[m] = {
                                    "verdict": "typo", "deferred": True,
                                }
                                self._audit_deferred_correction(
                                    spec_name,
                                    [m],
                                    verdict="typo",
                                    reason=(
                                        f"judge-typo-deferred: 凭据已登记但条目"
                                        f"仍在生效声明且写回层不可写（source="
                                        f"{effective_resolved.get('source')}），"
                                        f"声明未被改写、readback 恒失败——转打回/"
                                        f"凭据通道"
                                    ),
                                    actual_paths={m: actual_path},
                                    trigger_run_id=getattr(result, "run_id", "") or "",
                                    judge_run_id=judge_run_id,
                                )
                                deferred_typo_elements.append(m)
                                continue
                        else:
                            # 改写后文本（失败回退空串，diff 仍可反映「改写前非空」）
                            try:
                                after_text = Path(
                                    eff_spec_dir, "tasks.md"
                                ).read_text(encoding="utf-8")
                            except (OSError, UnicodeDecodeError):
                                after_text = ""
                            diff_by_element[m] = {
                                "before": audit_before,
                                "after": after_text,
                            }
                        # Task 3.2：陈日重定位（文本改写路径）同样复检读取
                        # 一致性——改写落层与守卫读取基准错层时不判成功（D3
                        # 不变量同款：修正被执行 ⇔ 下一次守卫读取能看到修正）。
                        rb_ok, _rb_detail = self._readback_correction(
                            spec_name, result, m, kind=kind_m
                        )
                        if not rb_ok:
                            # 陈日重定位已落生效层但复检失败：与同型 typo/reference
                            # 分支对齐（code-review item 0fcdd3476318 口径，本条
                            # b4ea54fe50a2）——复用 _audit_deferred_correction 落
                            # readback-failed 标注（不落 executed_verdicts 时
                            # dispute 审计块对其失明），并并入 deferred_typo_elements
                            # 使「修正未生效于读取基准」复发形态对 D5 熔断可见。
                            # verdict 仍转 unclear（末段归宿分类按 unclear 置
                            # blocked 待人工，不改归宿分类；streak 不清零，人工
                            # 解冻续走后 D5 逐轮累计至熔断）。
                            self._audit_deferred_correction(
                                spec_name,
                                [m],
                                verdict="typo",
                                reason=(
                                    f"judge-typo-readback-failed: 陈日重定位已落"
                                    f"生效层（文本改写或凭据登记）但复检失败，修正"
                                    f"未生效于读取基准: {_rb_detail}"
                                ),
                                actual_paths={m: actual_path},
                                trigger_run_id=getattr(result, "run_id", "") or "",
                                judge_run_id=judge_run_id,
                            )
                            deferred_typo_elements.append(m)
                            verdict_by_element[m] = {"verdict": "unclear"}
                            continue
                        self._writeback_recur_reset(spec_name)
                        executed_verdicts.append({"element": m, **v})
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispute judge 裁决 typo（陈日重定位）'{spec_name}': "
                            f"{m} → {actual_path}（凭据三要素齐备，重定位执行）",
                        )
                    else:
                        from core.deliverables import replace_declared_path

                        # fix-relocation-writeback-layer Task 2.1（事故点接线）：
                        # 改写落点 = 写回层（与守卫读取基准同源，D1）。eff_spec_dir
                        # 由 ``spec_dir or 主树`` 回退而来——source == "branch"
                        # （声明只在分支对象库、无落盘位置）时写主树即「写主树、
                        # 守卫读分支」的事故本身，MUST NOT 以此为落点假装修正已
                        # 生效：转打回/凭据通道，并把该条 typo 裁决（element +
                        # actual_path）落 dispute 审计流（供 Task 4.1/4.2 下一轮
                        # 凭据核销）。worktree/main 命中就地改写 + 提交到该层
                        # （Task 1.3/1.4：提交失败走打回，不改落主树兜底）。
                        wb = self._writeback_target(spec_name, result)
                        ok_w, detail_w, diff = self._apply_declaration_correction(
                            spec_name,
                            m,
                            lambda d, _m=m, _a=actual_path: replace_declared_path(
                                d, _m, _a
                            ),
                            wb=wb,
                        )
                        if not ok_w:
                            # Task 2.1：不可写/提交失败 → **打回/凭据通道**，不判
                            # unclear——unclear 会落「blocked 待人工」，凭据核销
                            # （D4）与复发熔断（D5）在下一轮根本没有运行机会，
                            # 事故态死循环换个形态继续。deferred 标记让分类循环
                            # 把该条按缺件打回（verdict 仍 typo，actual_path 供
                            # 核销识别）。
                            verdict_by_element[m] = {
                                "verdict": "typo", "deferred": True,
                            }
                            self._audit_deferred_correction(
                                spec_name,
                                [m],
                                verdict="typo",
                                reason=(
                                    f"judge-typo-deferred: 写回层不可写"
                                    f"（source={wb.get('source')}），MUST NOT 改写"
                                    f"主树，转打回/凭据通道: {detail_w}"
                                ),
                                actual_paths={m: actual_path},
                                trigger_run_id=getattr(result, "run_id", "") or "",
                                judge_run_id=judge_run_id,
                            )
                            deferred_typo_elements.append(m)
                            continue
                        diff_by_element[m] = diff
                        # Task 3.2：修正后以守卫读取基准复检；读回仍是旧路径
                        # → 不判修正成功（不落 executed_verdicts、转 unclear，
                        # 末段归宿分类按 unclear 置 blocked 待人工而非打回），
                        # 复发计数交守卫重跑后判定。
                        rb_ok, _rb_detail = self._readback_correction(
                            spec_name, result, m, kind=kind_m
                        )
                        if not rb_ok:
                            # 改写已落写回层但复检失败：改写事实仍须可追溯、
                            # 复发计数不漏计（code-review item 0fcdd3476318）——
                            # 同型复用 _audit_deferred_correction 落 readback-
                            # failed 标注记录（否则该条不进 executed_verdicts，
                            # dispute 审计块对其失明），并并入
                            # deferred_typo_elements 使「修正未生效于读取基准」
                            # 复发形态对 D5 熔断可见。verdict 仍转 unclear
                            # （末段归宿分类按 unclear 置 blocked 待人工而非
                            # 打回；streak 不清零，人工解冻续走后 D5 逐轮
                            # 累计至熔断）。
                            self._audit_deferred_correction(
                                spec_name,
                                [m],
                                verdict="typo",
                                reason=(
                                    f"judge-typo-readback-failed: 改写已落写回层"
                                    f"（source={wb.get('source')}）但复检失败，"
                                    f"修正未生效于读取基准: {_rb_detail}"
                                ),
                                actual_paths={m: actual_path},
                                trigger_run_id=getattr(result, "run_id", "") or "",
                                judge_run_id=judge_run_id,
                            )
                            deferred_typo_elements.append(m)
                            verdict_by_element[m] = {"verdict": "unclear"}
                            continue
                        # Task 5.1：typo 修正复检通过 → 复发计数清零
                        self._writeback_recur_reset(spec_name)
                        executed_verdicts.append({"element": m, **v})
                        self._pm.logger.warning(
                            "pm_engine",
                            f"dispute judge 裁决 typo '{spec_name}': "
                            f"{m} → {actual_path}（声明段已修正于写回层 "
                            f"source={wb.get('source')}，复检通过）",
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

                    # fix-relocation-writeback-layer Task 2.2：软化落点 = 写回层
                    #（与守卫读取基准同源）。不可写（source == "branch"）MUST NOT
                    # 软化主树——该条 reference 裁决落 dispute 审计流转打回；改写
                    # /提交失败（worktree 占用等）同样降级，不静默判成功（Task 1.4）。
                    wb = self._writeback_target(spec_name, result)
                    ok_w, detail_w, diff = self._apply_declaration_correction(
                        spec_name,
                        m,
                        lambda d, _m=m: soften_declared_kind(d, _m),
                        wb=wb,
                    )
                    if not ok_w:
                        # Task 2.2：同 2.1——deferred 标记走打回（不判 unclear
                        # 短路成 blocked 待人工），该条裁决已落审计流。
                        verdict_by_element[m] = {
                            "verdict": "reference", "deferred": True,
                        }
                        self._audit_deferred_correction(
                            spec_name,
                            [m],
                            verdict="reference",
                            reason=(
                                f"judge-reference-deferred: 写回层不可写或提交失败"
                                f"（source={wb.get('source')}），MUST NOT 软化主树，"
                                f"转打回/凭据通道: {detail_w}"
                            ),
                            trigger_run_id=getattr(result, "run_id", "") or "",
                            judge_run_id=judge_run_id,
                        )
                        continue
                    diff_by_element[m] = diff
                    # Task 3.2：复检须限定原 kind——软化后条目仍在声明中、仅
                    # kind 变 reference，不限 kind 会误判「仍读到旧路径」。
                    rb_ok, _rb_detail = self._readback_correction(
                        spec_name, result, m, kind=kind_m
                    )
                    if not rb_ok:
                        # 软化已落写回层但复检失败：该条裁决落 dispute 审计流
                        # （readback-failed 标注）使已落盘的软化事实可追溯
                        #（code-review item 0fcdd3476318，与 typo 分支同型——
                        # 不落 executed_verdicts 时 dispute 审计块对其失明）。
                        # verdict 仍转 unclear（末段归宿分类按 unclear 置
                        # blocked 待人工而非打回；本分支不入
                        # deferred_typo_elements，不参与 D5 复发计数）。
                        self._audit_deferred_correction(
                            spec_name,
                            [m],
                            verdict="reference",
                            reason=(
                                f"judge-reference-readback-failed: 软化已落写回层"
                                f"（source={wb.get('source')}）但复检失败，修正"
                                f"未生效于读取基准: {_rb_detail}"
                            ),
                            trigger_run_id=getattr(result, "run_id", "") or "",
                            judge_run_id=judge_run_id,
                        )
                        verdict_by_element[m] = {"verdict": "unclear"}
                        continue
                    executed_verdicts.append({"element": m, **v})
                    self._pm.logger.warning(
                        "pm_engine",
                        f"dispute judge 裁决 reference '{spec_name}': "
                        f"{m} 已软化为 reference（写回层 source={wb.get('source')}"
                        f"，复检通过）",
                    )
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
                        # judge 原始 verdicts 与执行层改写后 verdicts 都落审计：
                        # 防白洗改写（如 delete-kind reference 被拒改写为
                        # unclear 带 judge_original/rewrite_reason）若只写
                        # judge 原始输出，改写事实在审计轨迹中不可见。
                        "verdicts": (
                            verdict_data.get("verdicts") if verdict_data else executed_verdicts
                        ),
                        "executed_verdicts": executed_verdicts,
                        # 凭据登记条目（type=credential，未发生 tasks.md 文本
                        # 改写）原样透传回执要素——MUST NOT 投影成 before/after
                        # （凭据路径无文本变化，恒等 diff 会呈现「声明已改写」
                        # 假象，code-review item ca3447e2d676）；真实文本改写
                        # 保持既有投影形状。
                        "diff": {
                            k: (
                                dict(d)
                                if d.get("type") == "credential"
                                else {
                                    "before": d.get("before"),
                                    "after": d.get("after"),
                                }
                            )
                            for k, d in diff_by_element.items()
                            # 非 dict（_apply_declaration_correction 改写失败
                            # 返回 None）跳过该键，与预分类审计投影同口径——
                            # 单条 diff 异常不得令整条 dispute 审计记录丢失。
                            if isinstance(d, dict)
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
        # 守卫重跑独立 try/except（code-review item 0133485d7dff）：本模块其它
        # 重跑点（_preclassify_missing/_orphan/_drift/_stale）均包裹该守卫；若它
        # 在此抛异常，旧实现会让异常在 spec 仍处临时 blocked 态时逃逸、中止裁决。
        # 失败按「仍缺件」保守处置（fail-closed：不放行 merge），error 走既有
        # blocked/人工裁决路径。
        try:
            remaining = self._pm._deliverable_gate_missing(spec_name, result)
        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"dispute judge 裁决后守卫重跑异常 '{spec_name}'（保守按仍缺件处置）: {e}",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "blocked",
                    "tester_run": None,
                    "error": f"dispute judge 裁决后守卫重跑异常（需人工复核）: {e}",
                },
            )
            return {"action": "handled"}
        if not remaining:
            # Task 5.1：SPEC 退出本形态（守卫放行）→ 复发计数清零
            self._writeback_recur_reset(spec_name)
            # 终审期间置 blocked 属临时态：恢复 in-flight（implementing），
            # worker 合并路径的 implementing → implemented 转换才合法
            # （放行块收敛复用 _all_clear_proceed——code-review item
            # 6bc523df28ae，放行语义调整不再与本类四预分类器两处同步）
            return self._all_clear_proceed(
                spec_name,
                f"dispute judge 裁决执行后守卫重跑通过 '{spec_name}' — 放行 merge",
            )

        # 规范化 remaining（list[dict]）为路径列表 + 保留条目供下游；
        # 缺 path 键兜底空串（code-review item fc62a0cdb4c3，.get 取值口径
        # 与 _redispatch_for_missing 对齐）——本处位于守卫重跑 try/except
        # 之外，畸形条目不得以 KeyError 逃逸令复发对账整批降级。
        remaining_paths = [
            (r.get("path") or "") if isinstance(r, dict) else str(r) for r in remaining
        ]

        # fix-relocation-writeback-layer D5（Task 5.1/5.2）：typo 修正后同路径
        # 复发熔断。守卫重跑（读取基准）仍判**旧路径** missing ⇔「修正未生效于
        # 读取基准」复发——修正生效时旧路径已不在生效声明，守卫只会报替代路径
        # 缺件（真缺交付物，打回实现方），不属复发。计数用独立字段
        # _writeback_recur_streak（MUST NOT 复用 _retry_count：恢复续做/重建
        # 分支显式清零之、env-blocked 复位旁路之，事故态 31h 在飞恒为 0），仅
        # 复检通过或本形态放行时清零（Task 5.3）。达 agents.max_retries 上限
        # → blocked（「修正未生效」形态文案），不再自动重派（迁移期兜住未覆盖
        # 形态，防 31h/$44.98 型空转）。
        typo_touched = {
            ed["element"]
            for ed in executed_verdicts
            if ed.get("verdict") == "typo"
        } | set(deferred_typo_elements)
        # 同轮只取一条（sorted 首条）参与计数（code-review f6a837457bb8）：
        # _writeback_recur_streak 是单值字段且「换路径清零」，同轮多条复发
        # 路径逐条 bump 会互相清零（每轮 streak 恒为 1）致熔断永不触发；
        # 每轮只计首条，单路径行为不变，多路径同轮持续复发由持续在场的一
        # 条累计到上限触发。
        for recur_path in sorted(set(remaining_paths) & typo_touched)[:1]:
            if not self._writeback_recur_bump(spec_name, recur_path):
                continue
            # 解析口径收敛三车道单一读取器 repair_lane._max_retries（code-
            # review item f68ba79c3e07 + item 00af54aa1442 跨通道统一），与
            # _writeback_recur_bump 同源——文案轮数与实际熔断阈值一致。
            max_r = _max_retries(self._pm)
            recur_entry = self._pm.state_machine.read_one(spec_name) or {}
            err = (
                f"声明修正连续复发熔断（形态=修正未生效于读取基准，非普通缺件）: "
                f"{recur_path} 经 typo 修正/凭据落册后连续 {max_r} 轮守卫仍判 "
                f"missing（streak={recur_entry.get('_writeback_recur_streak')}）"
                f"——需人工核对声明落层与凭据核销条件"
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {"status": "blocked", "error": err, "tester_run": None},
            )
            self._pm.logger.error(
                "pm_engine",
                f"声明修正复发熔断置 blocked '{spec_name}': {err}",
            )
            return {"action": "handled"}

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

    def _redispatch_with_retry(
        self,
        spec_name: str,
        error_builder: Callable[[int, int], tuple[str, str]],
        log_builder: Callable[[int], str],
        *,
        agent_type: str = "implementer",
        branch: str | None = None,
        legacy_warn_prefix: str = "遗产登记失败",
    ) -> None:
        """打回重派样板：交付物守卫缺件 / tasks.md relint 处置共用（code-review
        item 462dd0549885）。

        两处置路径原本各持一份同构流水线，计数与封顶逻辑双写易漂移，现收口
        单点维护：``bump_counters`` 锁内原子递增 ``_retry_count``（返回写后
        值）→ ``agents.max_retries`` 封顶 → 组装 ready/blocked updates（封顶时置
        ``tester_run=None`` 并换 blocked 文案）→ update_spec → error 日志 →
        未封顶时按车道 ``_enqueue_front`` 前置入队。分支遗产登记（fail-open，
        异常捕获降级 WARNING 不阻断处置）在状态写回与入队**之前**执行
        （D3 顺序语义）。

        Args:
            error_builder: ``(retries, max_r) -> (未封顶 error, 封顶 error)``，
                由调用点闭合各自的违规明细文案。
            log_builder: ``retries -> 日志文案``（logger.error，pm_engine 通道）。
            agent_type: 重派车道透传给 ``_enqueue_front``（code-review item
                9ea41826c63f：由调用方声明以选择 fast-track/implementer 车道）。
            branch: 非空时重派前登记仅分支遗产（``register_legacy`` 仅分支模式
                + ``mark_legacy_reusable`` 打 reuse 标记，使下轮 create 可认领
                同一分支）；空则静默跳过登记。``register_legacy`` 只写
                worktree_manager 内存注册表、不触碰 spec 状态，故 read_one
                先后无观测差异。
            legacy_warn_prefix: 登记失败 WARNING 文案前缀（调用点各自保留原文案，
                如 ``缺件打回遗产登记失败`` / ``relint 遗产登记失败``）。
        """
        _wm = self._pm.agent_runner.worktree_manager
        if branch and hasattr(_wm, "register_legacy"):
            try:
                _wm.register_legacy(spec_name, None, branch)
                # fixed-relint-redispatch-legacy 一致性：打 reuse 标记使仅分支遗产
                # 可被下轮 create 经 _take_reusable_worktree 认领同一分支（两打回
                # 路径同语义；register_legacy 自身不置 reuse，keep_for_reuse 同源标记）。
                if hasattr(_wm, "mark_legacy_reusable"):
                    _wm.mark_legacy_reusable(spec_name)
            except Exception as e:
                # 登记异常捕获降级 WARNING 不阻断处置：登记失败不应中断
                # 打回的状态写回与重派。
                self._pm.logger.warning(
                    "pm_engine",
                    f"{legacy_warn_prefix}（非阻塞）'{spec_name}': {e}",
                )
        # _retry_count 走锁内原子递增（bump_counters 返回写后值，code-review
        # item 3dae7ab671a1）：原先「read_one 读 → 算 +1 → 并进 update_spec
        # 写回」读与写分处两次 STATE 锁临界区，与并发失败链（queue.py
        # merge-only 重试 / WIP 周期消费者）交错时各持相同旧值写回同一
        # _retry_count，丢一次递增、agents.max_retries 封顶晚一轮触发。对齐
        # repair_lane.py _fallback_after_repair 同型修复：_retry_count 不再
        # 并入下方 update_spec（避免并发覆盖丢增量）。
        retries = self._pm.state_machine.bump_counters(spec_name, {"_retry_count": 1}).get(
            "_retry_count", 0
        )
        # 解析口径收敛三车道单一读取器 repair_lane._max_retries（code-review
        # item f68ba79c3e07 三处共用 + item 00af54aa1442 跨通道统一）。
        max_r = _max_retries(self._pm)
        err_ready, err_blocked = error_builder(retries, max_r)
        updates: dict = {
            "status": "ready",
            "error": err_ready,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["tester_run"] = None
            updates["error"] = err_blocked
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error("pm_engine", log_builder(retries))
        if updates["status"] != "blocked":
            self._enqueue_front(spec_name, agent_type)

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

        计数/封顶/登记样板由 ``_redispatch_with_retry`` 统一承载（与
        ``_redispatch_tasks_relint`` 共用，防双写漂移）。
        """
        # 按 kind 分化话术：undeleted 用「未删除」语义、missing 保持「缺件」语义
        missing_q = "、".join(
            (
                f"{m.get('path', '?')}（{m.get('violation', 'missing')}）"
                if isinstance(m, dict)
                else str(m)
            )
            for m in missing_list
        )
        self._redispatch_with_retry(
            spec_name,
            lambda retries, max_r: (
                f"交付物守卫：违规 [{missing_q}] — 不合并不推进，"
                f"重派实现补齐（第 {retries} 次）",
                f"交付物守卫连续 {max_r} 次缺件 [{missing_q}] — 已 blocked，"
                f"需人工检查任务书声明与实际落地差异",
            ),
            lambda retries: (
                f"交付物守卫触发 '{spec_name}'（缺件 {missing_q}）— "
                f"run={getattr(result, 'run_id', '') or ''}"
            ),
            agent_type=agent_type,
            branch=getattr(result, "branch", None),
            legacy_warn_prefix="缺件打回遗产登记失败",
        )

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
        detail = "；".join(relint)
        self._redispatch_with_retry(
            spec_name,
            lambda retries, max_r: (
                f"tasks.md 收口复检违规 — 不合并不推进，重派修正（第 {retries} 次）："
                f"{detail}。修正处方：任务行行首必须为 `- [ ]` / `- [x]`；"
                f"若现为 `^- [x]` 即 sed 转义损伤，请改回 `- [` 并恢复 checkbox",
                f"tasks.md 收口复检连续 {max_r} 次违规 — 已 blocked，"
                f"需人工修复 tasks.md（行首 `- [ ]`/`- [x]`）",
            ),
            lambda retries: (
                f"tasks.md relint 触发 '{spec_name}'（第 {retries} 次）— "
                f"run={run_id or 'n/a'}"
            ),
            agent_type=agent_type,
            branch=branch,
            legacy_warn_prefix="relint 遗产登记失败",
        )
