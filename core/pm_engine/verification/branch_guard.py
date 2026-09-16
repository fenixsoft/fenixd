"""core.pm_engine.verification.branch_guard — 分支门 / 交付物门（refactor-verification-module D2）。

从 VerificationPipeline 摘出的分支门禁（分支提交数、零变更哨兵）、交付物门
（交付物缺失）、tasks.md 重新 lint（分支/worktree）、争议交付物、replan 错误
提取与残留断言、env 阻塞复位路径解析。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from core.state_machine import FREEZE_ERROR_PREFIX

# git 合并判定超时（subprocess timeout；异常/超时按「未合并」fail-safe 回退
# ready 通道——宁可多重实现不可错误直达 testing）。
ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS = 10


def resolve_env_blocked_reset_path(spec: dict, project_root) -> str | None:
    """env 阻塞复位路径判定（D1 守卫链）。

    Args:
        spec: STATE.md spec entry（须含 status/error/frozen/branch）。
        project_root: 主树 project_root——git 合并判定统一在此执行
            （subprocess cwd，与验证引擎其他 git 操作同侧）。

    Returns:
        "testing": branch 非空且 merge commit 已在主树历史（实现分支已合并）——
            可走 BLOCKED→TESTING 重验直通道（transition_gate）。
        "ready":   branch 为空（实现阶段熔断）或 branch 未合并——走既有
            BLOCKED→READY 重实现通道（transition）。
        None:      spec 非 blocked，或人工冻结（frozen=True / error 以冻结前缀
            开头），或无法判定——调用方不应触发任何复位转换。
    """
    if not isinstance(spec, dict) or spec.get("status") != "blocked":
        return None
    # 人工冻结：frozen 结构化标记或 error 文本契约（FREEZE_ERROR_PREFIX）任一
    # 命中即视为人工冻结，不走自动复位（人工处置是唯一出路）。
    if spec.get("frozen"):
        return None
    error = str(spec.get("error") or "")
    if error.startswith(FREEZE_ERROR_PREFIX):
        return None
    branch = spec.get("branch")
    if not branch:
        return "ready"
    if _branch_merged_into_tree(branch, project_root):
        return "testing"
    return "ready"


def _branch_merged_into_tree(branch: str, project_root) -> bool:
    """branch 的 merge commit 是否存在于主树历史（git merge-base --is-ancestor）。

    统一在主树 project_root 执行（design D4：worktree 布局差异不影响判定）；
    subprocess 异常（git 不可用/仓库异常/超时）一律按「未合并」fail-safe 处理——
    宁可回退 ready 全量重实现，不可错误直达 testing 造成验证前置缺失。
    """
    try:
        from pathlib import Path

        root = Path(project_root)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(branch), "HEAD"],
            cwd=str(root),
            capture_output=True,
            timeout=ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except Exception:
        return False


def _implementation_branch_has_commits(pipeline, result) -> bool:
    """实现分支相对 main 是否已有提交（`git rev-list --count main..<branch>` > 0）。

    Conservative fail-open：``result.branch`` 为空或 rev-list 失败/超时一律
    返回 False（→ 调用方走重派，不吞风险）。供 fast-track 死亡路径分流
    （dispatch._run_fast_track_flow）与 ``_implementer_zero_change`` 共用。
    """
    count = _branch_commit_count(pipeline, result)
    return count is not None and count > 0


def _branch_commit_count(pipeline, result) -> Optional[int]:
    """实现分支相对 main 的提交数（`git rev-list --count main..<branch>`）。

    单一来源（fix-fasttrack-resultfile-missing-redispatch D1）：供
    ``_implementation_branch_has_commits`` 与 ``_implementer_zero_change``
    共用。``result.branch`` 为空或 rev-list 失败/超时返回 None
    （调用方各自按 conservative fail-open 处置，不吞风险）。
    """
    import subprocess as _sp

    branch = getattr(result, "branch", None)
    if not branch:
        return None
    try:
        r = _sp.run(
            ["git", "rev-list", "--count", f"main..{branch}"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(pipeline._context.project_root),
        )
        if r.returncode != 0:
            return None
        return int(r.stdout.strip() or "0")
    except (OSError, ValueError, _sp.TimeoutExpired):
        return None


def _implementer_zero_change(pipeline, spec_name: str, result) -> bool:
    """实现器零变更成功判定：分支零新提交 且 全程零 Edit/Write 工具调用。

    分支缺失（result.branch 为空）不判定（保持既有行为，向后兼容）。
    """
    branch = getattr(result, "branch", None)
    if not branch:
        return False
    count = _branch_commit_count(pipeline, result)
    if count is None:
        return False  # rev-list 失败/超时 → fail-open 不判零变更（既有语义）
    if count > 0:
        return False  # 有新提交 → 正常成功
    # 分支零提交，再看运行产物中是否有编辑类工具调用
    run_file = pipeline._context.project_root / ".fenix" / "runs" / f"{result.run_id}.jsonl"
    try:
        with run_file.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant":
                    continue
                for c in (d.get("message") or {}).get("content") or []:
                    if (
                        isinstance(c, dict)
                        and c.get("type") == "tool_use"
                        and c.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit")
                    ):
                        return False
    except OSError:
        return False
    return True


def _deliverable_gate_missing(pipeline, spec_name: str, result) -> list:
    """交付物守卫：返回 SPEC 声明与实现分支现实的差异条目清单。

    纯文件存在性检查（add-implementer-deliverable-gate D3）：从 SPEC 目录
    提取声明路径，逐一在 ``result.branch`` 的 HEAD 提交中校验 blob 存在。
    校验基准为实现分支（worktree 已清理，仅分支留存）。

    提取器语义升级（add-deliverable-extractor-semantics）：仅
    ``deliverables``（新建交付物）参与缺件判定；``references``（既有文件
    引用）走软校验——缺失仅记审计日志（D4），不阻断、不重派、不改状态。
    路径按字面校验（``normalize_check_path`` 已退役为恒等映射：
    ``.fenix`` 自引用符号链接设计废弃后为实体目录，历史的前缀归一化
    会在根路径同名文件存在时把 ``.fenix/x`` 缺件假放行）。

    结构化返回（add-deliverable-delete-kind D3）：返回类型为
    ``list[dict]``，每项 ``{"path": str, "kind": str,
    "violation": "missing"|"undeleted"}``。``violation`` 语义由 ``kind``
    决定——``new``/``modify``：分支 HEAD 无该 blob → ``missing``；
    ``delete``：分支 HEAD 仍有该 blob → ``undeleted``（反判）。kind 来自
    声明段 ``extract_declared_entries``；正则回退路径无 kind 概念，统一
    按 non-delete 语义（缺失即 ``missing``）。

    Returns:
        差异条目列表；空列表表示放行（含无路径 SPEC 跳过场景）。
    """
    from core.deliverables import extract_declared, extract_declared_entries, extract_paths_typed

    spec_dir = pipeline._context.project_root / "spec" / "changes" / spec_name
    if not spec_dir.is_dir():
        return []
    # 声明优先（planner 交付契约）：tasks.md 有 `## Deliverables` 段时做机械
    # 对账，不做正则语境猜测；无声明段回退 extract_paths_typed（向后兼容）。
    typed = extract_declared(spec_dir)
    decl_source = "declared"
    if typed is None:
        typed = extract_paths_typed(spec_dir)
        decl_source = "extracted"
    declared = typed["deliverables"]
    references = typed["references"]
    if not declared and not references:
        # 无路径 SPEC：跳过守卫，行为退化到守卫上线前（向后兼容）
        return []
    # kind 映射：声明段条目提供 path→kind（供反判 delete）；
    # 正则回退无 kind 概念，全部按 non-delete 语义（缺失即 missing）。
    kind_by_path: dict = {}
    if decl_source == "declared":
        for e in extract_declared_entries(spec_dir) or []:
            kind_by_path[e["path"]] = e["kind"]
    wm = pipeline._pm.agent_runner.worktree_manager
    branch = getattr(result, "branch", None)
    if not branch:
        # 无分支无法校验存活交付物：保守放行（与既有零变更哨共用缺失判定），
        # 交由零变更哨/merge 流程兜底
        return []

    def _exists_on_branch(path: str) -> bool:
        # 字面路径校验（.fenix 前缀归一化已退役，见本方法 docstring）
        return wm.file_exists_on_branch(branch, path)

    # 交付物（硬校验）：按 kind 区分违规类别——
    #   new/modify 缺失 → missing（既有一致行为）；
    #   delete 仍存在 → undeleted（反判，D3 结构化返回）。
    violations: list = []
    for p in declared:
        kind = kind_by_path.get(p, "new")
        if kind == "delete":
            if _exists_on_branch(p):
                violations.append({"path": p, "kind": "delete", "violation": "undeleted"})
        else:
            if not _exists_on_branch(p):
                violations.append({"path": p, "kind": kind, "violation": "missing"})
    violations.sort(key=lambda v: v["path"])

    # 引用（软校验，D4）：缺失仅审计留痕——引用错误不该阻断实现
    missing_refs = [p for p in references if not _exists_on_branch(p)]
    if missing_refs:
        pipeline._context.logger.warning(
            "deliverable-reference-missing",
            f"引用类路径在实现分支中不存在（仅审计留痕，不阻断）："
            f"{spec_name} -> {', '.join(missing_refs)}",
            context={
                "spec": spec_name,
                "branch": branch,
                "source": decl_source,
                "missing_references": missing_refs,
            },
        )
    return violations


def _tasks_md_relint_from_branch(pipeline, spec_name: str, branch) -> list:
    """full 车道 tasks.md 收口复检：读实现分支 HEAD 版本并判定违规。

    基准 = 分支上的 tasks.md（merge 前主树版本 = 立项旧版本，读分支才反映
    中途编辑）。``git show`` 非零退出（路径不存在）→ fail-open 返回 ``[]``，
    与 lint「文件不存在不拦」语义一致（task-track relint fail-open）。
    """
    if not branch:
        return []
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(pipeline._context.project_root),
                "show",
                f"{branch}:spec/changes/{spec_name}/tasks.md",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"tasks.md relint git show 失败（fail-open）'{spec_name}': {e}",
        )
        return []
    if proc.returncode != 0:
        # 路径不存在 → fail-open（fast-track 前置 spec 允许后补）
        return []
    from core.deliverables import lint_tasks_text

    return lint_tasks_text(proc.stdout)


def _tasks_md_relint_from_worktree(pipeline, spec_name: str, worktree_path) -> list:
    """fast-track 车道 tasks.md 收口复检：读 worktree 内版本并判定违规。

    path 不存在 → fail-open 返回 ``[]``（同晋升 lint「文件不存在不拦」语义）。
    任何异常 → WARNING + fail-open，不阻塞成功收口。
    """
    if worktree_path is None:
        return []
    try:
        tasks_file = Path(worktree_path) / "spec" / "changes" / spec_name / "tasks.md"
        if not tasks_file.exists():
            return []
        text = tasks_file.read_text(encoding="utf-8")
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"tasks.md relint 读取失败（fail-open）'{spec_name}': {e}",
        )
        return []
    from core.deliverables import lint_tasks_text

    return lint_tasks_text(text)


def _disputed_deliverables(pipeline, impl_result, missing) -> list:
    """实现 run 对缺件提出的 deliverable-dispute 异议与缺件清单求交。

    交互契约的 findings 通道（add-interaction-contract 泛化）：实现 run 认为
    某缺件路径实为运行时写入目标/既有引用而非本仓库交付物时，在
    ``.fenix-run-result.json`` findings 登记 ``deliverable-dispute`` 条目。
    守卫拒绝前先对账：命中异议的缺件**不得**自动重派（负反馈死循环会烧钱），
    由调用方转人工/裁决。

    element 与缺件路径按字面匹配（``normalize_check_path`` 已退役为
    恒等映射）。返回值为 dispute 命中路径列表（``list[str]``），供调用方
    按路径拼接 error 话术，不因 kind 区分。

    Args:
        impl_result: 实现 run 结果 dict（含 findings）。
        missing: 守卫返回的差异条目列表（``list[dict]``，每项含
            ``path``/``kind``/``violation``）。

    Returns:
        命中异议的缺件路径子集（保序）。
    """
    if not impl_result or not missing:
        return []

    disputed: list = []
    for f in impl_result.get("findings") or []:
        if not isinstance(f, dict) or f.get("type") != "deliverable-dispute":
            continue
        el = str(f.get("element") or "").strip()
        if not el:
            continue
        for m in missing:
            # missing 现在是 list[dict]，按路径匹配（D5：dispute 按路径匹配，
            # 不因 kind 失效）
            m_path = m.get("path") if isinstance(m, dict) else str(m)
            if m_path == el and m_path not in disputed:
                disputed.append(m_path)
    return disputed


@staticmethod
def _extract_replan_error_items(env_error: str) -> list[str]:
    """抽取场景验收错误文本中的逐条错误清单（消费硬门比对基准，D5）。

    场景文件验收错误文本（load_scenarios ValueError）形如：
        "场景文件包含 N 个错误:\n  - 场景'a'步骤0: ...\n  - ..."
    逐条抽取 "- " 前缀行作为错误项；无该形态（单条错误/其它来源）时
    退化为整段文本单条目，与既有「一字不差」比对语义同源。

    Returns:
        错误条目列表；env_error 为空返回空表。
    """
    if not env_error:
        return []
    items: list[str] = []
    for line in (env_error or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    if items:
        return items
    return [env_error.strip()]


@staticmethod
def _replan_errors_unconsumed(prev_items: list, cur_items: list) -> bool:
    """消费硬门判定：本轮错误清单是否为上轮相同或超集（D5）。

    上轮错误逐条在本轮全部复现（相同或超集）→ True（planner 未消费反馈）；
    错误实质性消除（数量减少或主体变化）→ False。空清单不作判定（False）。
    """
    if not prev_items:
        return False
    return set(prev_items) <= set(cur_items)
