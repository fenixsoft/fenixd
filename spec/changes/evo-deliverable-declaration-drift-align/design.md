# Design: deliverable-declaration-drift-align

## D1: 漂移判定（对齐孤儿预分类数据通道）

core/deliverables.py 已有孤儿判定数据通道（deliverable-dispute-orphan-preclassify，deliverables.py:1397 起）：
- `git log --all -- <path>` 历史命中检测（_git_path_history_hit，返回 {hit, commits}）
- 历史零命中 → 孤儿判定；历史命中 → 现行走人工（漂移特征）

本 SPEC 在「历史命中」分支前插入漂移对齐判定：

```python
def _locate_drift_target(project_root: str, declared_path: str) -> list:
    """全仓定位拆包后候选落点。
    规则：以 declared_path 的 basename（去 .py）为关键词，递归扫描
    pathspec 下（core/）所有 .py 文件；命中目录含同 basename 子目录
    （拆包特征）时，候选 = 目录内与被拆函数同名的模块（如 worktree_manager.py
    → worktree_manager/mergeback.py）。
    Returns: 候选列表（长度 1 = 可机械对齐；0 或 >1 = fail-open 回人工）
    """
```

scoring：候选按「目录名 == 旧 basename」优先，其次「文件名 == 旧 basename 内联页（mergeback / queue 等）」；若两候选可分辨（旧文件拆出的模块与既有文件同名冲突），拒绝（>1）回人工。

## D2: 机械对齐与审计

对齐执行：
1. 读取 tasks.md 的 Deliverables 声明段（fenced yaml），定位 `- path: <declared_path>` 行
2. 替换为新落点 path（kind 保持原值）
3. 写回 tasks.md（保留原文件其余内容）
4. 写 audit：`{"kind": "dispute-audit", "spec": ..., "verdicts": [{"element": <声明路径>, "verdict": "drift-aligned", "actual_path": <新落点>, "reasoning": "..."}], "finalize": "drift-auto-aligned"}`
5. 解除 blocked：清 error、置回 implementing（若实现 run 仍可重入）或 ready 重排

fail-open 准则（高度保守）：任何一步异常（读 tasks.md 失败、找不到声明行、候选不唯一、写回失败）→ 终止机械对齐，走既有人工裁决通道。

## D3: 派发前同源草案收敛检查

core/pm_engine/engine.py `_on_spec_ready`（派发 implementer 前）：
1. 收集 spec/changes/ 下所有目录的 SUPERSEDED.md
2. 解析每份 SUPERSEDED.md 的被取代目录名与生效落点
3. 若本 spec ∈ 任一被取代名单，或本 spec 目录自身含 SUPERSEDED.md（且未删除）→ 拦截派发、置 blocked（error=同源草案收敛义务未满足: <SUPERSEDED.md 相对路径>）
4. 收敛完成的信号：被取代目录被删除或 SUPERSEDED.md 被移除

检查键：capability + name 归一（同需求草案名去除时间戳后缀后相等，或 SUPERSEDED.md 显式点名）。

## D4: 测试策略

tests/test_deliverable_drift_align.py：
- 漂移判定：mock git 历史命中 + 目录扫描，覆盖唯一候选/多候选/零候选（fail-open）
- 对齐执行：构造临时 spec 目录（tasks.md 声明段 yaml），断言改写 + audit 落盘 + blocked 解除
- 同源检查：两草案目录 + SUPERSEDED.md，断言派发拦截与解收敛后恢复