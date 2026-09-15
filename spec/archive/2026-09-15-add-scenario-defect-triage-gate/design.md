# Design: add-scenario-defect-triage-gate

## Context

add-spec-status-modal-budget 事故（2026-09-09/10）完整因果链：跨轮 replan 原样写回已裁决场景（含 seed cli-seed-status-modal-fixtures），seed 内嵌上一轮 worktree 字面端口 :57905 → 新一轮 serving 端口不同 → seed 夹具实际未建成 → 19 个下游 web/api 场景「项目列表空/行选择器未匹配」连锁失败。judge 将 19 个全部归 test-defect 却申报 bug-found（已有 scenario-repaired 通道未走，prompt 明文「场景文件问题派 implementer 是错误路由」但无兜底），框架 bug-found 分支（verification.py:1790→1818→family.py:441 inplace 打回）全程不读 classification——两个实现轮（$88+）整轮消耗在修场景文件上。

现状机制盘点：
- judge-scenario-repair 通道已存在（1c8f7820，预算 `_SCENARIO_REPAIR_MAX_ROUNDS`=2，serving 缓存重执行秒级）——本次未被 judge 采用；
- 写端 schema 门 / replan 消费硬门（fix-frozen-scenario-orphan-reservoir）只管结构合法与错误清单消费，不管内容语义（端口硬编码、seed 覆盖不足）；
- judge prompt 动态段挂载点在 prompt_builder.py `planner-judge` 分支（`_scenario_freeze_section` → … → `_result_gate_section`）；
- web_runner 执行时以契约 base_url 为准（navigate 字面端口为回退考古），cli_runner 注入 FENIX_VERIFY_PORT/FENIX_VERIFY_BASE_URL 环境变量——字面端口在 cli/api stdin/command 中是硬缺陷，在 navigate 中是误导性情报。

## Goals / Non-Goals

**Goals:**
- 纯场景缺陷清单（product-bug=0）不再消耗实现轮预算——结构性根治本次事故形态；
- 已知机械可查缺陷模式（跨轮端口残留、双汉字选择器）在 judge 裁决前即有定向情报，提高 judge 一次走对 scenario-repaired 路由的概率；
- judge prompt 的场景修复路由约定与框架改道门形成双保险（prompt 引导 + 框架兜底）。

**Non-Goals:**
- 不做语义级「seed 自建夹具完整性」静态验证（拓扑/内容语义不可静态判定，本次事故 depends_on 拓扑健康即为反例）；
- 不做行选择器运行时存在性静态检查（取决于渲染结果，不可静态判定）；
- 不自动改写场景文件（stdin 代码形态各异，机械改写易碎）——静态扫描只产情报，修复主体是 judge；
- 不改 scenario-repaired 既有预算语义、不改场景 schema 门与 replan 消费硬门。

## Decisions

**D1：改道门挂点在框架 bug-found 分支，判定依据为 report.json 的 classification 分布**
插桩于 `_run_three_stage_verification` bug-found 分支（`_on_spec_bug_found` 调用前）。备选：在 family.py `_do_spec_bug_found` 入口插桩——弃之，因为 verification 分支已持有 report/verdict 上下文，且改道语义（重派 judge）与打回语义（重派 implementer）在分支级分叉更清晰。判定保守取向：failed 全部**显式** test-defect/flaky 且 product-bug=0 才改道；None/未知值一律不改道——与 add-verdict-credibility-gate「推测级归因不得打回」同源哲学：改道门漏掉真 product-bug 有恢复路径（改道后重验仍失败 → 二次裁决正常放行），误拦真 bug 无路径。

**D2：改道动作 = 定向重派 judge 一次，复用既有 scenario-repaired 通道收口**
不新增「场景修复 agent」：judge 已具备「与出题同源知识 + 本轮执行证据」（既有 prompt 定位），重派成本为一次 judge run（效率治理后常态 8-15min），远低于实现轮（$24-64/轮）。定向指令段经 prompt_builder 新增 `_scenario_reroute_directive_section` 注入。改道重派计入 `_SCENARIO_REPAIR_MAX_ROUNDS` 预算（与 scenario-repaired 重入共用计数，防两通道叠加无限重入）。预算耗尽 → 人工升级（告警附失败清单/classification 分布/judge 各轮申报记录），spec 保持 testing——复用既有 `_send_human_escalation_alert` 通道。

**D3：静态扫描只产情报不拦截执行**
拦截执行的备选被否：检出即拦会让验证空转（重跑不修场景必然复发），且执行证据（report/截图）恰是 judge 修复的依据。扫描挂点在 `_apply_scenario_freeze` 完成后、阶段2 执行前；findings 落盘 `scenario_static_findings.json`（每轮覆盖写）+ judge prompt 情报段注入。fail-open：扫描任何异常记 WARNING 跳过，不产生 error 终态——与既有「验证快照 gate 只看进度 fail-open」同风格。

**D4：模式表数据驱动，初始三模式**
扫描器主体与模式定义分离（模式表 = 模块级数据结构：rule_id、适用 kind、匹配函数）。初始模式钉死三条：①cli/api command/stdin 字面端口 ≠ serving 端口（本次事故根因，纯正则）；②web navigate URL 字面端口 ≠ serving 端口（误导性情报级）；③双汉字文本选择器（antd autoInsertSpace 已知坑，历史 touch-expand/antd 系列事故积累）。serving 端口未知的轮次端口类模式整体跳过（纯文本模式仍执行）。新增模式 = 增加表项，不动扫描器主体。

**D5：prompt 路由指引前移 + 已裁决场景修复合法性显式声明**
judge 未走 scenario-repaired 的疑因之一是文末协议段远离分类判定现场，且冻结语义可能让 judge 对修改已裁决场景有顾虑。修订 agents/planner-judge.md：test-defect 分类定义处（:64 附近）内联路由指引（根因在场景文件 → MUST scenario-repaired），显式声明「修复已裁决场景合法、冻结 diff 记账保护（无理由移除才确定性补齐）、不视为冻结违规」；文末协议段保留细节。静态情报段注入位置在 `_verdict_cache_section` 之后、`_result_gate_section` 之前（先给情报后给硬门契约）。

## Risks / Trade-offs

- [judge 将真 product-bug 误标 test-defect → 改道延迟真 bug 修复一轮] → 恢复路径完整（改道 → 修场景重验 → 仍失败二次裁决正常放行）；D1 保守判定 + verdict-credibility-gate 归因证据门降低误标率；宁可多一轮重验不可烧实现轮修场景（本次事故直接教训）。
- [改道重派 = judge 两轮都拒绝原地修复（能力上限）] → 预算耗尽升级人工收口，失败可见（告警附 judge 行为记录），不再静默烧实现轮；judge 修不动的复杂场景修复（如 seed 端口改造+轮询）由人工裁决走 admin 场景修复通道（schema 门内）。
- [静态模式误报磨掉 judge 信任] → 初始模式只收确定性规则（端口不等、恰 2 汉字）；端口一致不报；情报段措辞为「定向情报 + 修复职责」，非强制结论；模式表可随时摘除误报项。
- [改道门与 scenario-repaired 重入叠加导致循环] → 共用 `_SCENARIO_REPAIR_MAX_ROUNDS`=2 预算（D2），总量有界；耗尽即升级人工。
- [prompt 情报段与 checkpoint 恢复/硬门段的注入顺序冲突] → 固定挂载序（D5），新增段不影响既有段语义。

## Migration Plan

纯增量：新模块 + 分支内插桩 + prompt 段追加。无数据迁移、无配置迁移（模式表暂不外置配置——加 Dashboard 配置需求出现时再议，符合「新增配置项必须带 Dashboard 界面」约束的规避形态）。回滚 = revert 提交，无残留状态（findings 文件为轮级临时产物，不参与任何门禁判定）。

## Open Questions

（无——模式表初始集、改道判定口径、预算共用、注入位置均已钉死。）
