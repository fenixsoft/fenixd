# 场景修订重验出口

<!-- knowledge: capability=scenario-revision-reverify-exit rev=1
     sources=spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit -->

env 类失败被诊断为「场景定义不可行 / 夹具缺供给」时的人工修订通道：凭 admin 诊断结论改写场景定义与夹具供给层文件后重置重验，是 env 阻塞处置中「修环境」与「豁免放行」之外的第三出口，代替把不可行场景反复重验到冻结。

## 规则

- 注册与作用域：`revise_scenario_reverify`（修订场景·重验）注册在 `inconclusive_loop` 裁决桶，与 grant_env_exemption 同族（spec 作用域动作，消费通道为 ESCALATION 前端告警区下拉）。
- 载荷契约：修订以结构化 JSON 载荷为输入——`{"scenarios": [...], "reason": "...", "fixture_files": [{"path", "content"}]}`；`scenarios` 必填且为修订后的完整场景集（整体替换非增量）；裸文本载荷视为缺载荷拒绝——修订 MUST 以结构化场景集为输入，凭一句「改一下」执行会让修订内容无据可查。
- 修订预算：修订次数按 spec 生命周期累计（跨验证复位保持，验证链路计数复位不清此字段），上限 `SCENARIO_REVISION_MAX_COUNT`（默认 2）；达上限拒绝执行并结构化冻结转人工——修订出口耗尽后继续修订只是把「场景设计不可行」往预算里藏。
- 路径白名单：夹具供给层文件仅允许 `.fenix/fixtures`、`fixtures`、`tests/fixtures`、`test/fixtures` 目录与 `.fenix/verify.yaml` 单文件；绝对路径（含 `~` 展开与 Windows 盘符形态）、`..` 穿越越出被验项目根、白名单外落点（产品代码路径）一律拒绝，以被验项目 project_root 锚定解析并复核。白名单是允许表非黑名单：新增供给层目录须显式扩表。校验只做路径形态判定、不做磁盘存在性检查；白名单只承诺「字面路径不可越出供给层」，符号链接的写端语义不在本校验兜底。
- 落盘纪律：场景集经版本戳处理后**成对同覆盖** `test_scenarios.json` 与 `_scenarios_full.json`（防对账时回填旧定义）；夹具与场景逐文件写前快照，任一步失败按快照回滚本轮已写文件（不留半改状态与「新一个旧一个」成对撕裂对）；场景结构预校验非法即整体拒绝入盘。
- STATE 生命周期：执行序列为载荷解析 → 修订预算前置 → 白名单校验 → 结构预校验 → 落盘（快照+回滚）→ STATE 更新（修订计数 +1、置 `_scenario_revision_reverify_pending` 旗标、清 env 阻塞与 inconclusive 停车字段）→ 解冻 + implemented→testing 门禁转换 + 调度唤醒重派 verifier。
- 修订 re-entry 先于升级：修订后首轮重验仍失败、再度到达升级停车入口时，守卫消费 pending 旗标并追加一次重验（给修订后场景集一次收敛机会）；旗标单次消费——追加轮再失败则正常升级停车，修订不无限续命；verified 落定与人工复位同样清旗标。
- 与 env 豁免的联动：修订覆盖场景定义后，既有豁免随场景定义 hash 变化失效，后续失败重新走裁决（见 [verdict-env-exemption-handshake](verdict-env-exemption-handshake.md)）。

## 关键行为

场景不可行 → admin 诊断确认 → 选择「修订场景·重验」并提交完整场景集与夹具载荷 → 白名单校验 + 成对落盘 → 计数 + 旗标 + 清停车字段 → 解冻重派 verifier → 全绿则 verified；首轮再失败由 re-entry 旗标追加一次重验；修订次数达 2 次后修订请求被拒并冻结转人工。

## 溯源

- 2026-10-15 evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit（spec/archive/2026-10-15-evo-fix-env-exemption-gate-conflict-and-scenario-revision-exit） — 新建本页：revise_scenario_reverify 修订出口全链（JSON 载荷契约、修订上限默认 2、夹具供给层路径白名单、成对同覆盖+快照回滚、STATE 旗标与修订 re-entry 先于升级、超限冻结转人工）。
