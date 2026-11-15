# code-fix 定向重试轮：回归失败的基线对照判法（2026-11-14 实操）

## 场景
code-fix 批收尾全量回归报失败 2 例（test_escalation_chain e2e、test_task_artifact_ownership 零误拦守卫），框架提示「修复可能引入回归」。

## 判法（先证归属，再动手）
1. **基线对照**：`git worktree add --detach /tmp/base-wt-<ts> <批基线提交>`，在其中跑同一失败用例。archive 导出（无 .git）不可用——`_collect_tasks_files` 等依赖 `git ls-tree` 会 128。基线/HEAD 违规集逐字节相同（grep -oE 提取文件名后 diff）= 失败批前已存在，非本批引入。
2. **零交集核查**：`git diff <基线>..HEAD --stat -- <失败用例覆盖目录>` 为空 = 本批对该面零触碰。
3. **瞬态定性**：单测连跑 5/5 + 整测试文件连跑 3/3 全绿 + 首轮回归未曾失败 → 定性瞬态，不改代码（为未确诊假设动产品代码反而给回归门引入新风险），交框架复验。

## 本轮实锤两例
- **test_task_artifact_ownership 5.4 零误拦守卫**：批外提交 177117189（2026-11-12 windows-native-support 事故响应）往 `lint_tasks_text` 加了缺编号判定，其可解析性违规先于产物归属段短路返回——对存量归档 corpus（11 文件）属真阳性（处方「补编号后重新晋升」对归档件不可达），而守卫测试 docstring 只守「产物归属违规」，实现却收全部违规。修法：归属段提取 `ownership_violations_for_tasks_text` 单源（lint_tasks_text 委托，行为逐字节等价），守卫测试独立全量扫描归属面（短路不吞归属校验）。教训：**往既有 lint 函数追加新违规类目时，必须同步核查按 docstring 收窄范围的守卫类测试**——它们的实现常按「函数返回值全集」断言，新类目落库即整批回归门全红。
- **test_escalation_chain e2e**：`_write_chain_event` 的 recurrence+escalated 在配额耗尽分支同发；失败形态 escalated 无 recurrence 指向反抖分支或台账 append 静默吞异常，但零交集+连绿证据下按瞬态收口。

## 关联域
code-fix-lane（批收尾回归门与失败明细映射）、implementer-lane（交付物 lint）、verdict-adjudication（失败归因）。
