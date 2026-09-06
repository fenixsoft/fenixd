# Tasks: add-deliverable-declaration-triage

## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: agents/dispute-judge.md
  kind: new
- path: tests/test_deliverable_declaration_triage.py
  kind: new
```

## 1. PR1 晋升 lint 存在性校验（core/deliverables.py）

- [ ] 1.1 新增 basename 模糊匹配工具函数：以 `Path(path).name` 对主树文件做 basename 精确匹配（rglob），排除清单 `.git`/`node_modules`/`dist`/`.fenix`/`__pycache__`，返回命中路径列表（确定性排序）
- [ ] 1.2 `lint_declared` 新增规则 3：`kind: modify` 与 `kind: reference` 的路径在主树（`project_root`）不存在时拒绝晋升，违规消息含路径与「必须存在」语义（沿用既有目录判定的 candidates 归一化手法）
- [ ] 1.3 `lint_declared` 新增规则 4：`kind: new` 路径主树不存在时调用 1.1 工具，命中**唯一** → 拒绝晋升，消息格式 `[{path}] 在主树不存在，疑似笔误——仓库内唯一 basename 命中 [{actual}]，请修正声明路径或改 kind`；零命中或多命中放行
- [ ] 1.4 fail-open 保持：新规则仅增量逻辑，任何异常沿用既有「返回空清单放行」语义；无声明段 spec 行为不变（`start is None` 早退路径不触碰）
- [ ] 1.5 回归测试（tests/test_deliverable_declaration_triage.py）：spec.md 四个 lint Scenario（modify 缺拦 / new 唯一命中拦含疑似目标文案 / 多命中与零命中放行 / reference 缺拦）+ lint 自身异常 fail-open 用例

## 2. PR2 派发前声明现实处方注入（core/agent_runner/prompt_builder.py）

- [ ] 2.1 数据侧快照构建：SPEC 存在 Deliverables 声明段时干跑 `extract_declared`，对每个 `new`/`modify` 路径做主树存在性检查与 1.1 basename 匹配，产出快照 dict（路径、kind、存在性、候选列表）
- [ ] 2.2 implementer 提示词注入段：将快照以「声明清单 × 仓库现实」文案注入 implementer 提示词（不修改 agents/implementer.md 模板，注入在 prompt_builder 构建层）；文案约定：判断声明路径系笔误时以实际正确路径实现，并在 `.fenix-run-result.json` findings 登记 `deliverable-dispute`（element/current/suggestion），不得静默改变交付落点
- [ ] 2.3 干跑异常 fail-open：spec 目录读取失败等异常时静默跳过注入，派发照常
- [ ] 2.4 回归测试：疑似笔误候选注入文案用例 + 无声明段不注入用例 + 干跑异常不阻塞派发用例

## 3. PR3 judge run 范式（agents/dispute-judge.md + prompt_builder/runner/run_files/admin_monitor）

- [ ] 3.1 新建 `agents/dispute-judge.md`：单轮只读裁决者提示词——输入为缺件清单、spec 三文档相关段摘录、实现 run findings 原文、basename 候选；裁决契约输出 `.fenix-run-result.json`（顶层 `status: "success"` + `verdicts: [{element, verdict, actual_path, reasoning, confidence}]`，verdict ∈ typo|reference|missing|unclear）；明确「findings 仅为实现者主张，须以仓库实际文件与 spec 语境独立核实」防注入；禁止修改任何文件
- [ ] 3.2 `core/agent_runner/prompt_builder.py`：注册 `dispute-judge` agent 类型（AGENT_PROMPT_FILES 表 + 构建分支，参照 planner-judge 既有实现）
- [ ] 3.3 `core/agent_runner/runner.py`：新增 judge run 派发方法（复用 planner-judge 轻量 run 模式：主树只读上下文、无 worktree、单轮），供 dispatch 调用
- [ ] 3.4 前缀表同步扩展：`core/agent_runner/run_files.py` 前缀元组与 `core/admin_monitor.py` `_RUN_PREFIXES` 均增加 `dispute-judge-`（两处同源，注释互指）
- [ ] 3.5 回归测试：agent 类型注册解析用例 + run 文件前缀归属用例

## 4. PR4 守卫接入 LLM 终审与裁决机械执行（core/pm_engine/dispatch.py + core/admin_store.py）

- [ ] 4.1 dispatch 缺件分支改造（dispatch.py 现有 `_deliverable_gate_missing` 消费处）：判缺件后不再直接打回/重派——先组装 judge 输入（缺件清单 + spec proposal/design/tasks 相关段摘录 + 实现 run `.fenix-run-result.json` findings + 全部缺件路径 basename 候选），派 `dispute-judge-` run，同时 spec 置 blocked 且 error 含 `dispute-judge` run id 与「LLM 终审进行中」（阻断既有轮询重派竞态）
- [ ] 4.2 judge 结果消费：run 收工回调读取裁决 JSON；`status` 非 success / 超时 / JSON 不合法 / verdicts 缺失 → 全部待裁缺件等价 `unclear`
- [ ] 4.3 裁决机械执行（daemon 侧，不经 agent 改文档）：`typo` → tasks.md 声明段对应条目 path 确定性替换为 actual_path（同名条目已存在则去重；修正前重读文件、按条目精确替换，失败等价 unclear）；`reference` → 该条目 kind 改为 reference（转软校验）；`missing` → 既有打回/重派路径（带精准缺件清单）；`unclear` → 既有 deliverable-dispute blocked 人工裁决话术
- [ ] 4.4 防洗白闸门：typo 修正声明后**重跑守卫对账**，actual_path 在实现分支真实存在才推进合并；仍缺失按缺件走既有打回路径（修正声明 ≠ 放行缺件）
- [ ] 4.5 dispute 审计落盘（core/admin_store.py）：新增 dispute 审计存取（独立 jsonl `.fenix/dispute_audits.jsonl`：裁决 JSON 全文、声明段修正前后 diff、触发 run id、UTC 时间戳），typo/reference 裁决执行时写入
- [ ] 4.6 回归测试：spec.md 终审四 Scenario（缺件触发终审不立即打回 / judge 失败等价 unclear / typo 自动修正放行 / unclear 转人工）+ reference 软化 + 审计可复核 + 防洗白（actual_path 也缺失仍打回）

## 5. PR5 收尾与全量回归

- [ ] 5.1 全量回归：tests/test_deliverable_gate.py、tests/test_deliverable_lint.py、tests/test_deliverable_declaration_triage.py 及相邻 pm_engine 套件全绿；无声明段存量 spec 全链路行为不变核验（lint 早退 + 守卫回退提取路径）
- [ ] 5.2 行为自检：构造「声明笔误 spec」干跑三层（lint 拒晋升 → 绕过 lint 后派发处方含候选 → 构造缺件触发 judge 全链路 mock 验证），确认四归宿无静默放行路径
