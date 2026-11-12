## Deliverables

```yaml
- path: core/admin_auto_exec.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_choice_exec.py
  kind: modify
- path: core/dashboard/data/admin_payload_drafts.py
  kind: new
- path: core/dashboard/data/admin_alerts.py
  kind: modify
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/routes/alert_routes.py
  kind: modify
- path: core/dashboard/static/src/hooks/useAlertAdjudication.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/verify_engine/engine.py
  kind: modify
- path: core/verify_engine/cli_runner.py
  kind: modify
- path: core/verify_engine/skip_semantics.py
  kind: new
- path: core/worktree_manager/lifecycle.py
  kind: modify
- path: core/worktree_manager/queries.py
  kind: modify
- path: tests/test_admin_auto_exec_policy.py
  kind: modify
- path: tests/test_dual_lane_adjudication.py
  kind: modify
- path: tests/test_admin_payload_drafting.py
  kind: new
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_verify_wip_isolation.py
  kind: new
- path: tests/test_verify_cli_runner.py
  kind: modify
```

## 1. 载荷门闩锁（G4 / D1，adjudication-auto-exec）

- [ ] 1.1 `core/admin_auto_exec.py` 载荷门（`_maybe_auto_exec` :403-408 附近）首跳写闩锁：告警 auto_exec 投影记 `skip_reason="requires_payload"` + 推荐 choice id + 首跳时间；INFO 日志仅首跳一次
- [ ] 1.2 tick 短路：投影已闩锁且无解除事件时直接 return，不重复四判据评估、不刷 INFO（DEBUG 痕可留）；解除事件=告警状态变化/草稿指针落位或移除/记录被编辑，解除后恢复正常评估
- [ ] 1.3 `core/dashboard/data/admin_alerts.py` 投影字段落位与读取（随告警记录持久化，无新状态文件）；人工处置通道可达性不受闩锁影响（alert-resolve 全程照常）
- [ ] 1.4 单测（`tests/test_admin_auto_exec_policy.py`）：首跳投影+一次 INFO、连续 3 tick 零重复 INFO 零重复评估、草稿落位解除重评（投影反映草稿待批）、闩锁期间 alert-resolve 正常执行

## 2. 载荷起草 run（G1 / D2-D3，admin-payload-drafting）

- [ ] 2.1 `core/admin_monitor.py` 派发 kind=`admin_payload_draft`：闩锁超 grace（复用 `get_auto_exec_config` 单源）触发；输入含 spec/signal_type/judge 归因引用/推荐 choice/预算余量；单飞（同告警 1 在跑）+ 连续上限 2；派发不改告警 pending、不触 spec 状态机
- [ ] 2.2 新建 `core/dashboard/data/admin_payload_drafts.py`：草稿落 `.fenix/admin_payload_drafts/<alert_id>.json`（gitignore），落位前强制同源预校验 `validate_scenario_dicts`（core/verify_engine/scenarios.py:1946）+ `validate_scenario_revision_paths`（adjudication_choices.py），不过不落盘；告警挂 draft 指针（落位时间+校验标记）；告警已处置/不存在则安全退出
- [ ] 2.3 `core/admin_choice_exec.py` 结果门：起草 run 产物只许草稿文件+指针；出现执行类痕迹（调执行器/写成对场景集/耗预算）判 run 失败留痕，fail-closed
- [ ] 2.4 harness spawn 失败/超限降级：告警保持 pending、投影可见、计数+1、日志留痕，不升级不阻塞他告警与他车道
- [ ] 2.5 单测（新建 `tests/test_admin_payload_drafting.py`；`tests/test_dual_lane_adjudication.py` 补幂等/上限用例）：合法落位挂指针、非法不落盘、越界拦截、单飞、上限转纯人工、spawn 失败降级、预算计数不变

## 3. 面板载荷交互（G2/G3 / D4，adjudication-ui）

- [ ] 3.1 `core/dashboard/data/adjudication_choices.py` 注册表透出选项元数据（`requires_payload` 布尔 + `payload_schema` 摘要），经 alert-resolve choices 下发（单源不复制）
- [ ] 3.2 `core/dashboard/routes/alert_routes.py` 新增 `GET /api/alert-payload-draft` 只读取材端点（挂指针返草稿全文，无指针 404）
- [ ] 3.3 `core/dashboard/static/src/services/dashboard.ts`：草稿取读客户端 + 选项类型扩展；`resolveAlert` 函数签名不变
- [ ] 3.4 `core/dashboard/static/src/hooks/useAlertAdjudication.tsx`：选中 requires_payload 选项时渲染载荷编辑器（JSON 文本域+形态提示+客户端校验+空载荷拦截，执行按钮禁用逻辑）；草稿预填/等待起草/人工粘贴三态，人工编辑优先；普通选项零回归（回退原 note 交互）
- [ ] 3.5 前置清单：冻结态（一键解冻复用既有 unfreeze API，成功放行）+ 修订预算余量 + 载荷体积提示；「按草稿执行」快捷入口；视觉遵循仓库根 DESIGN.md；承载面 projects/detail.tsx、activities MobileAlertRow、指挥中心收件箱卡，桌面列表行不增删控件
- [ ] 3.6 单测（`tests/test_adjudication_choices.py` 补元数据透出；UI 层用例入 2.5 文件或同组新用例）：空/非法载荷禁用执行、冻结前置拦截+解冻放行、草稿预填按草稿执行、普通选项回退

## 4. 验证构建 WIP 隔离（G5 / D5-D6，verify-wip-isolation）

- [ ] 4.1 新建 `core/verify_engine/skip_semantics.py`：跳过原因枚举（`wip_overlap_isolation_unavailable` 等）、与失败轮计数互斥、info 留痕结构
- [ ] 4.2 `core/verify_engine/engine.py` 轮启动预检：dirty tracked 清单（单源 `core/worktree_manager/queries.py` porcelain 解析供给）与构建输入路径求交（排除 `spec/changes/**`，对齐 `_detect_wip_overlap` core/worktree_manager/mergeback.py:907 的 evo-merge-back-wip-overlap-gate D2 口径）；干净/无重叠走现状原路径（短路零新增开销）
- [ ] 4.3 `core/worktree_manager/lifecycle.py` 验证 worktree 供给（从 HEAD 创建/复用，不绑 spec 锁语义，绝不 stash/checkout 用户主树）；`core/verify_engine/cli_runner.py` verify_root 注入：隔离时 prepare/serve/场景命令全在 worktree 内执行，报告标注 verify_root + WIP info 标注
- [ ] 4.4 隔离不可行跳过：不计失败轮、不递增 `_env_block_rounds`、不推进 escalation.py 冻结阈值判定，info 留痕含重叠清单；不阻塞其他 SPEC 调度；WIP 消除后自动恢复
- [ ] 4.5 单测（新建 `tests/test_verify_wip_isolation.py`；`tests/test_verify_cli_runner.py` 补 verify_root 用例）：干净主树零回归（路径短路）、重叠触发隔离、主树 porcelain 前后一致、隔离失败跳过不计数不冻结、恢复后正常计数

## 5. 回归与验收

- [ ] 5.1 四 capability 全 Scenario 覆盖核对（adjudication-auto-exec 7 场景、admin-payload-drafting 8 场景、adjudication-ui 8 场景、verify-wip-isolation 7 场景）
- [ ] 5.2 既有回归全绿：`tests/test_admin_auto_exec_policy.py`、`test_dual_lane_adjudication.py`、`test_adjudication_choices*.py`、`test_verify_cli_runner.py`、`test_verify_dispatch_single_flight.py`（自动通道对 requires_payload 永不直接执行的保守语义零回归）
- [ ] 5.3 端到端演练：构造带 revise_scenario_reverify 推荐的 pending 告警 → 闩锁 → 起草 run 产草稿 → 面板预填 → 一键解冻+按草稿执行 → 预算计数+1 重派 verifier（ dry-run 形态，不落真实 spec）
