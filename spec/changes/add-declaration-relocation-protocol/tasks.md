# Tasks: add-declaration-relocation-protocol

## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/verification/branch_guard.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/pm_engine/dispatch/adjudication.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/fast_track_result.py
  kind: modify
- path: tests/test_declaration_resolution.py
  kind: new
- path: tests/test_declaration_relocation.py
  kind: new
- path: tests/test_dual_lane_adjudication.py
  kind: new
```

> 注：本 spec 触及核心门禁链路（声明解析 / 收工守卫 / 双车道裁决流水线）与
> 若干读取侧消费点（提示词组装、fast-track 快照）。声明解析入口与重定位/收缩
> 校验落在 `core/deliverables.py`；守卫与裁决在 `branch_guard.py` /
> `adjudication.py`；双车道调用点在 `queue.py` / `fast_track.py`；门面委托表在
> `engine.py`。三份新增测试文件分别覆盖解析分层、重定位协议、双车道统一。

## 1. 阶段 1：统一声明解析入口（读取侧）

- [ ] 1.1 在 `core/deliverables.py` 新增 `resolve_effective_declaration(spec_name, *, branch=None, worktree_path=None, project_root=None)`：按「worktree 内文件 > `git show <branch>:spec/changes/<spec>/tasks.md` > 主树文件」优先序读取，复用既有 `extract_declared`/`extract_paths_typed` 解析，返回同构 `{"deliverables": [...], "references": [...]}`（保序去重）
- [ ] 1.2 分层回退实现：分支/worktree 读取失败（非零退出 / 超时 / 路径不存在）或解析异常 → 回退主树；两处均不可用 → 返回空结果；回退去向与原因经 logger 审计留痕（fail-safe，不抛异常）
- [ ] 1.3 成本约束：入口仅做 worktree 文件读或 `git show`/`git cat-file`，MUST NOT 触发 LLM / 测试 / 网络（纯对象库/文件读）
- [ ] 1.4 读取侧切换：`_deliverable_gate_missing`（`branch_guard.py`）、预分类与裁决中的声明读取（`adjudication.py`）、提示词组装（`agent_runner/prompt_builder.py`）、fast-track 快照（`fast_track_result.py`）改为经统一入口取「生效声明」，删除各自拼接 `project_root/spec/changes/<spec>/` 的直读
- [ ] 1.5 兼容性核对：无声明段的存量 spec、无分支场景（晋升 lint 期）回退主树后行为与现状逐字节一致（零迁移）

## 2. 阶段 2：可信基线快照与收缩防护

- [ ] 2.1 在 `core/deliverables.py` 新增 `snapshot_declaration_baseline(spec_name, run_id, project_root)`：把当前**主树**声明条目（path + kind）、快照时刻、触发 run id 原子写入 `.fenix/verify-progress/<spec>/declaration-baseline.json`；写入异常仅 WARNING 不阻塞派发
- [ ] 2.2 在实现 run 派发点（`queue.py` 的 full 车道、`fast_track.py` 的 fast-track 车道）调用 `snapshot_declaration_baseline`，确保快照落在 worktree 之外、实现 Agent 路径不写入
- [ ] 2.3 在 `core/deliverables.py` 新增 `check_declaration_shrinkage(baseline, effective, branch, project_root)`：对基线路径判「无声剔除」——生效声明不再含该路径、且该路径在实现分支 HEAD 不满足原有 kind 要求、且无重定位凭据/软化审计 → 返回 `{"path", "kind", "violation": "removed"}`；有合法豁免（重定位豁免 / 软化）不计入
- [ ] 2.4 基线不可用（未落盘 / 读取失败）时收缩防护降级为不产出违规并审计留痕「本轮未做收缩判定」（保守不误伤）
- [ ] 2.5 在 `_deliverable_gate_missing` 中并入收缩防护产出：违规条目以 `violation: "removed"` 混入既有结构化返回（`path`/`kind`/`violation`），下游按 kind 分化表述

## 3. 阶段 3：陈日声明前置分类与重定位协议

- [ ] 3.1 在 `core/deliverables.py` 新增陈日信号判定 `is_stale_declaration(entry, project_root)`：`kind ∈ {new, modify}` 且路径在**主树 HEAD 不存在** → True；`delete`/`reference` 恒 False；零语义推断（参考 `classify_unsatisfiable` 的排除形态处理）
- [ ] 3.2 新增 `relocate_declared_path(spec_dir, old_path, new_path)`：把生效声明中旧路径确定性替换为替代路径（kind 保持、同名去重），复用 `replace_declared_path` 的文本改写语义；改写失败抛出由调用方 fail-safe 处置
- [ ] 3.3 重定位凭据三要素校验：旧路径基线不存在 + 替代路径在实现分支 HEAD 存在（`file_exists_on_branch`）+ 来源标注；任一缺失 → MUST NOT 改写，转既有缺件处置
- [ ] 3.4 机械 basename 唯一命中作为无终审时的重定位来源（复用 `match_basename_in_tree`；仅唯一命中可用，多命中/零命中不自动重定位）
- [ ] 3.5 在守卫产生缺件清单后、进入终审前插入陈日前置分类（`branch_guard.py` 或调用方）：命中陈日信号的条目走重定位通道，MUST NOT 直接落入打回重派；分类为纯机械判定不触发 LLM

## 4. 阶段 4：双车道裁决流水线统一

- [ ] 4.1 把 `_adjudicate_deliverable_missing`（`adjudication.py`）泛化为车道无关入口：统一输入契约（spec 名 / 实现结果 / 缺件清单 / 声明上下文）与输出契约（`{"action": "proceed"|"handled"}`），陈日前置分类插在预分类之前
- [ ] 4.2 裁决执行目标改为**生效声明**（分支/worktree 版本），改写后同步持久化到分支（worktree 内直写；worktree 已清理时以 `git -C <root>` 原子落分支），保证 merge-back 后主树一致——消除「分支已改、主树仍旧」错层
- [ ] 4.3 重定位接入裁决：`typo` 裁决命中陈日信号时按重定位凭据三要素执行（复用 3.2/3.3）；重定位与软化（非重派归宿）MUST NOT 消耗重派预算，仅确认缺失的轮次计数
- [ ] 4.4 fast-track 车道接入：`fast_track.py` 缺件处置改为调用同源裁决流水线入口，MUST NOT 直接按缺件重派；终审进行期置 blocked、judge run 前缀与输出契约与 full 一致
- [ ] 4.5 门面委托表更新（`engine.py`）：新增/改名的裁决与解析入口按既有 `_delegate` 映射登记，保持 full 与 fast-track 经同一门面访问

## 5. 阶段 5：测试与回归

- [ ] 5.1 新增 `tests/test_declaration_resolution.py`：分层优先序（分支版本优先 / 分支读取失败回退主树 / 两处均无返回空）、结果与 `extract_declared` 同构、消费方经入口读取（断言行为而非调用某函数）
- [ ] 5.2 新增 `tests/test_declaration_relocation.py`：陈日信号判定（modify 路径基线缺失命中、`new` 正常语义不误判、delete/reference 不参与）、三要素凭据（缺替代路径拒绝 / 多命中不自动）、重定位改写与审计留痕、重定位后防洗白复检（通过放行 / 仍缺件打回）、失败安全
- [ ] 5.3 新增 `tests/test_dual_lane_adjudication.py`：full 与 fast-track 缺件走同源流水线（陈日走重定位 / 可软化走软化 / 判据不明转终审 / 确认缺失走重派）、重定位不消耗重派预算、fast-track 缺件 MUST NOT 直落重派
- [ ] 5.4 收缩防护用例：删声明行绕门判 `removed` 不放行；重定位豁免不判收缩；无基线保守降级不误伤
- [ ] 5.5 回归与基线比对：运行 `bin/run_full_suite.py`，确认不新增失败（重点 `test_deliverable_gate` / `test_tasksmd_relint_gate` / `test_recovery_legacy` / fast-track 相关）
- [ ] 5.6 端到端复现断言：以 `fix-relint-redispatch-legacy` 场景为夹具（主树声明陈旧指向已删路径、分支声明已对齐），断言守卫经生效声明放行、MUST NOT 重派
- [ ] 5.7 逐项勾选本 tasks.md 全部已完成任务
