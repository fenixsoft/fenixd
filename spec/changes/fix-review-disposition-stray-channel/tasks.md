# tasks — 评审处置留痕落点治理与散件 gitignore 草案误伤交付物目录

## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: tests/test_stray_first_sight_deliverable_guard.py
  kind: new
```

设计真相源：本 SPEC design.md。依赖：无（两改动面相互独立，可分别实现与验证）。

## 1. 面 B：散件首现草案交付物豁免

- [ ] 1.1 core/worktree_manager/stray_wip.py `_write_first_sight_alert`：新增交付物形态分支——`dir_path` 为 `spec` 或 `spec/` 前缀时，evidence 不生成 `gitignore草案:` 字段，改为 `交付物注记: spec/ 交付物目录不应 ignore，应提交入库`；description 与 recommended_action 条件化（交付物形态建议「核对归属后提交入库，或按产物真实落点迁出 spec/」，不提追加 .gitignore）；非 spec 形态文案与结构逐字不变

## 2. 面 A：spec-review 车道收尾提交钩子

- [ ] 2.1 core/agent_runner/result_gate.py（spec-review 落盘分派点附近）：结果文件成功落盘后对主树 `spec/changes/<spec>/` 执行 `git status --porcelain` 检查，有条目才 `git add` 该目录并单目录 commit（提交信息注明评审成文，形态对齐 arbiter `_materialize_proposal` 先例）；porcelain 为空跳过（幂等不产空提交）；任何 git 失败仅 WARNING，不影响结果文件交付与退出码；approved/repaired/rejected 三态统一走此收尾

## 3. 测试

- [ ] 3.1 tests/test_stray_first_sight_deliverable_guard.py：豁免面——`spec/changes/<name>/` untracked 首现断言 evidence 无 `gitignore草案:` 且含交付物注记、recommended_action 不含 .gitignore 追加指引；回归锚——普通运行时产物目录（如 `build-foo/`）首现草案行为与现行逐字一致；收尾面——三态断言（有变更提交且 `git status` 复查为净 / 无变更不产提交 / git 抛错时 WARNING 且结果文件路径照常返回）

## 4. 收尾验证

- [ ] 4.1 全量回归：`python3 -m pytest tests/test_stray_first_sight_deliverable_guard.py tests/test_worktree_stray_wip.py -q`（如存量散件测试文件名不同，以 `grep -rl "_write_first_sight_alert" tests/` 实际命中为准）；手册核查：`.fenix/admin_alerts.json` 新增首现告警（如有）对 spec/ 路径不再携带草案行
