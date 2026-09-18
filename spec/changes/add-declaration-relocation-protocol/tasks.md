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
- [ ] 1.4 读取侧切换：`_deliverable_gate_missing`（`branch_guard.py`，含其 path→kind 映射的 `extract_declared_entries` 取数）、预分类与裁决中的声明读取（`adjudication.py`）、晋升 lint（`deliverables.py` 的 `lint_declared` / `soften_unsatisfiable_declarations`）、提示词组装（`agent_runner/prompt_builder.py`）、fast-track 规模快照（`fast_track_result.py`）改为经统一入口取「生效声明」，删除各自拼接 `project_root/spec/changes/<spec>/` 的直读（无分支期由回退语义覆盖，行为同现状）
- [ ] 1.5 兼容性核对：无声明段的存量 spec、无分支场景（晋升 lint 期）回退主树后行为与现状逐字节一致（零迁移）

## 2. 阶段 2：可信基线快照与收缩防护

- [ ] 2.1 在 `core/deliverables.py` 新增 `snapshot_declaration_baseline(spec_name, run_id, project_root)`：把当前**主树**声明条目（path + kind）、快照时刻、触发 run id 原子写入 `.fenix/verify-progress/<spec>/declaration-baseline.json`；写入异常仅 WARNING 不阻塞派发
- [ ] 2.2 在实现 run 派发点（`queue.py` 的 full 车道、`fast_track.py` 的 fast-track 车道）调用 `snapshot_declaration_baseline`，确保快照落在 worktree 之外、实现 Agent 路径不写入
- [ ] 2.3 在 `core/deliverables.py` 新增 `check_declaration_shrinkage(baseline, effective, effective_entries, branch, project_root)`：对基线路径判「无声剔除」——生效声明对该路径**不再以原有 kind 硬校验**（条目被删除，或 kind 被改写为 `reference` 而移入软校验组，或改写为其他不满足原有语义的 kind）、且该路径在实现分支 HEAD 不满足原有 kind 要求、且无重定位凭据/软化审计 → 返回 `{"path", "kind", "violation": "removed"}`；有合法豁免（重定位改写 / 凭据登记 / 软化审计）不计入
- [ ] 2.4 基线不可用（未落盘 / 读取失败）时收缩防护降级为不产出违规并审计留痕「本轮未做收缩判定」（保守不误伤）
- [ ] 2.5 在 `_deliverable_gate_missing` 中并入收缩防护产出：违规条目以 `violation: "removed"` 混入既有结构化返回（`path`/`kind`/`violation`），下游按 kind 分化表述
- [ ] 2.6 收缩违规入流水线：`removed` 条目 MUST 与 `missing` 同源进入裁决流水线（4.1 的统一入口），MUST NOT 被排除、MUST NOT 静默放行、MUST NOT 无界重派；经凭据登记/合法软化后复检通过方放行

## 3. 阶段 3：陈日声明前置分类与重定位协议

- [ ] 3.1 在 `core/deliverables.py` 新增陈日信号判定 `is_stale_declaration(entry, project_root)`：**仅 `kind == "modify"`** 且路径在**主树 HEAD 不存在** → True；`new` 恒 False（`new` 的基线期望本就是不存在，未落地的 `new` 缺件走既有缺件处置与收缩防护，不得被强制转入重定位通道）；`delete`/`reference` 恒 False；零语义推断（参考 `classify_unsatisfiable` 的排除形态处理）
- [ ] 3.2 新增 `relocate_declared_path(effective_spec_dir, old_path, new_path)`：把生效声明中旧路径确定性替换为替代路径（kind 保持、同名去重），复用 `replace_declared_path` 的文本改写语义；`effective_spec_dir` MUST 为**生效声明所在位置**（worktree 内 spec 目录优先，其次分支版本落盘位置），MUST NOT 传主树 spec 目录；改写失败抛出由调用方 fail-safe 处置
- [ ] 3.3 重定位凭据三要素校验：旧路径基线不存在 + 替代路径在实现分支 HEAD 存在（`worktree_manager.file_exists_on_branch(branch, path)`，见 `core/worktree_manager/queries.py:60`）+ 来源标注；任一缺失 → MUST NOT 改写，转既有缺件处置
- [ ] 3.4 机械 basename 唯一命中作为无终审时的重定位来源（复用 `match_basename_in_tree`；仅唯一命中可用，多命中/零命中不自动重定位）
- [ ] 3.5 在守卫产生缺件清单后、进入终审前插入陈日前置分类（`branch_guard.py` 或调用方）：输入 MUST 为守卫结构化返回的全量条目（`violation ∈ {missing, undeleted, removed}`）；命中陈日信号的条目走重定位通道，MUST NOT 直接落入打回重派；分类为纯机械判定不触发 LLM
- [ ] 3.6 新增 `register_relocation_credential(spec_name, old_path, new_path, source, run_id, project_root)`：当生效声明已无该条目（实现方先行对齐）时，**不经文本替换**落册重定位凭据（旧路径 + 替代路径 + 来源 + run id + 时间戳）到 dispute 审计流，供收缩防护豁免匹配；替代路径在实现分支 HEAD 不存在或来源缺失 → MUST NOT 登记（转既有缺件处置）；MUST NOT 因「声明段无该条目」上抛卡死

## 4. 阶段 4：双车道裁决流水线统一

- [ ] 4.1 把 `_adjudicate_deliverable_missing`（`adjudication.py`）泛化为车道无关入口：统一输入契约（spec 名 / 实现结果 / 缺件清单 / 声明上下文）与输出契约（`{"action": "proceed"|"handled"}`），陈日前置分类插在预分类之前
- [ ] 4.2 裁决执行目标改为**生效声明所在位置**（worktree → 分支 → 主树回退），改写后 MUST 在实现分支上**提交**固化（worktree 内 `git -C <worktree> commit`；worktree 已清理时经 `worktree_manager` 重挂该分支 worktree、提交后移除），MUST NOT 仅写文件不提交、MUST NOT 用 `git -C <project_root> commit`（只作用于主树当前分支）；主树对齐由 merge-back 携带分支提交完成——消除「分支已改、主树仍旧」错层
- [ ] 4.3 重定位接入裁决：`typo` 裁决命中陈日信号时按重定位凭据三要素执行——生效声明仍有该条目则走 3.2/3.3 文本改写，已无该条目（实现方先行对齐）则走 3.6 凭据登记，MUST NOT 因条目缺失判 unclear 卡死；重定位与软化（非重派归宿）MUST NOT 消耗重派预算，仅确认缺失的轮次计数
- [ ] 4.4 fast-track 车道接入：`fast_track.py` 缺件处置改为调用同源裁决流水线入口，MUST NOT 直接按缺件重派；终审进行期置 blocked、judge run 前缀与输出契约与 full 一致
- [ ] 4.5 门面委托表更新（`engine.py`）：新增/改名的裁决与解析入口按既有 `_delegate` 映射登记，保持 full 与 fast-track 经同一门面访问

## 5. 阶段 5：测试与回归

- [ ] 5.1 新增 `tests/test_declaration_resolution.py`：分层优先序（分支版本优先 / 分支读取失败回退主树 / 两处均无返回空）、结果与 `extract_declared` 同构、消费方经入口读取（断言行为而非调用某函数）
- [ ] 5.2 新增 `tests/test_declaration_relocation.py`：陈日信号判定（modify 路径基线缺失命中、`new` 正常语义不误判且**不被强制转入重定位通道**、delete/reference 不参与）、三要素凭据（缺替代路径拒绝 / 多命中不自动）、重定位改写与审计留痕、**生效声明已无该条目时的凭据登记**（齐备登记放行 / 替代路径不存在不登记）、重定位后防洗白复检（通过放行 / 仍缺件打回）、失败安全
- [ ] 5.3 新增 `tests/test_dual_lane_adjudication.py`：full 与 fast-track 缺件走同源流水线（陈日走重定位 / 可软化走软化 / 判据不明转终审 / 确认缺失走重派）、重定位不消耗重派预算、fast-track 缺件 MUST NOT 直落重派
- [ ] 5.4 收缩防护用例：删声明行绕门判 `removed` 不放行；**kind 改写为 reference 绕门同样判 `removed`**；重定位豁免/凭据登记不判收缩；`removed` 条目经流水线处置（凭据登记后复检放行 / 无凭据转人工）；无基线保守降级不误伤
- [ ] 5.5 回归与基线比对：运行 `bin/run_full_suite.py`，确认不新增失败（重点 `test_deliverable_gate` / `test_tasksmd_relint_gate` / `test_recovery_legacy` / fast-track 相关）
- [ ] 5.6 端到端复现断言：以 `fix-relint-redispatch-legacy` 场景为夹具（主树声明陈旧指向已删路径 `core/pm_engine/dispatch.py`（kind: modify，该路径在主树 HEAD 已不存在）、分支声明已对齐为真实路径），断言两条路径均不重派——（a）实现方未改声明：守卫判缺件 → 陈日前置分类命中 → 重定位改写 → 复检放行；（b）实现方已对齐声明（本条为事故原形）：收缩防护产出 `removed` → 入流水线 → 终审 `actual_path` 凭据登记 → 复检豁免放行；两分支均断言 MUST NOT 重派、MUST NOT 陷入 `missing`↔重派死循环
- [ ] 5.7 逐项勾选本 tasks.md 全部已完成任务
