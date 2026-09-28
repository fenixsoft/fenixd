# alert-noise-governance 增量规格

## ADDED Requirements

### Requirement: 终态 spec 豁免内容闸门

内容完整性闸门（check_spec_content_missing）在 SPEC 状态为终态（done/archived）时 MUST 短路：不冻结、不产生 spec_content_missing 告警。状态以 STATE.md 当前值为准；MUST NOT 因目录内容缺失把终态 spec 改写回 blocked。

#### Scenario: done 态 spec 目录为空不冻结

- **WHEN** SPEC status=done 且 spec/changes/<名>/ 目录无任何认可内容文件
- **THEN** 闸门直接放行该次检查（不冻结、不告警），SPEC 状态保持 done

#### Scenario: 已交付 spec 被外部重置后不被二次反向冻结

- **WHEN** 已交付 spec 被外部重置回 ready、目录仅存 verification-report.md
- **THEN** 走「已交付未落盘」分类（见下），MUST NOT 按「空 spec」冻结

### Requirement: 已交付未落盘的独立分类

目录无认可内容（proposal.md/design.md/tasks.md/specs/**/*.md 四类）但存在 verification-report.md 时，闸门 MUST 产出独立信号 spec_delivered_no_content 而非 spec_content_missing：不冻结 SPEC，文案引导人工裁决（补 tasks.md 归档凭据或明确废弃）。派发拦截语义 MUST 保持不变：spec_has_content 对该目录仍判无内容，命中即回滚派发槽，MUST NOT 派出实现 run。该分类 MUST 自带幂等短路：既有 spec_content_missing 的幂等完全依赖「冻结改 blocked → 下次 status==blocked 短路」，本分支放弃冻结即失去该保护，而 SPEC 状态不变会使闸门随恢复精触发（60 秒）与 full_scan 反复命中——重复命中时若已存在同 spec 同 signal_type 的未处理告警，MUST NOT 追加新告警记录（对齐 admin_monitor._throttled 的「已存在未处理升级告警」判据）。

#### Scenario: 重复命中不重复告警

- **WHEN** 仅含 verification-report.md 的 ready spec 在恢复精触发与 full_scan 中被闸门反复命中
- **THEN** 已有未处理的 spec_delivered_no_content 告警时不追加新告警记录，且派发仍被拦截

#### Scenario: 仅含验证报告的目录出分类信号

- **WHEN** spec/changes/<名>/ 仅含 verification-report.md 且状态非终态
- **THEN** 信号为 spec_delivered_no_content，SPEC 状态不被改写为 blocked+frozen

#### Scenario: 派发拦截语义不变

- **WHEN** 该 spec 进入派发且目录仍无认可内容
- **THEN** spec_has_content 判定结果与现状一致，派发槽回滚

### Requirement: 新信号接入生命周期闭环

spec_delivered_no_content MUST 接入 core/alert_lifecycle.py 的闭环条件映射，且 MUST NOT 复用 spec_terminal_or_unblocked 条件——该条件在 evaluate_alert 中仅以 blocked 为未解除出口，对非 blocked 的 spec 一律判「已解除」，而本信号产生时 SPEC 恰恰停在 ready 等待裁决，复用会使告警在下一轮 auto_resolve 立即自动闭环、人工无从看见。MUST 注册独立条件 spec_delivered_adjudicated：仅当关联 SPEC 到达终态（done/archived）时自动闭环，非终态（含 ready/blocked）一律保持原状；evaluate_alert 为该条件新增判定分支。「补 tasks.md 归档凭据」裁决路径的告警收口为人工 handled 或置终态——evaluate_alert 只读状态表、不读目录，MUST NOT 承诺纯 status 判定无法达成的「补内容即自动闭环」。

#### Scenario: 待裁决期间告警保持可见

- **WHEN** spec_delivered_no_content 告警产生且关联 SPEC 仍处于 ready
- **THEN** auto_resolve 不闭环该告警，人工待处理队列持续可见

#### Scenario: 裁决后告警闭环

- **WHEN** 人工明确将 SPEC 置终态，或以 handled 记录裁决结论
- **THEN** 置终态路径由 spec_delivered_adjudicated 条件自动闭环，handled 路径按既有人工闭环语义收口，均无需再人工清除

### Requirement: 恢复路径复核 frozen

孤儿 ready 恢复（core/event_bus.py _recover_ready 及其入口 recover_orphan_ready）MUST 在清 error/重派之前复核 STATE 条目 frozen：为 True 时跳过恢复并记 INFO（含 spec 名与跳过原因）；早退清单的 docstring MUST 同步登记该条件。复核 MUST 先于任何 STATE 写入（该函数仅在 error 非空时写 STATE，早退天然零写入）。

#### Scenario: 冻结 spec 不被孤儿恢复重派

- **WHEN** 周期扫描发现 status=ready 且无进程驱动的 SPEC，且其 frozen=True
- **THEN** 跳过恢复与重派，记 INFO，STATE 不被改写

#### Scenario: 非冻结 spec 恢复行为不变

- **WHEN** 孤儿 ready SPEC 的 frozen 非 True
- **THEN** 既有恢复流程（清 error、重派）保持不变

### Requirement: 派发链复核 frozen

spec_ready 消费与派发准备（core/pm_engine/engine.py _on_spec_ready）MUST 在既有守卫链（shutting_down/冷却/单飞/worktree 锁/退避/start_after/依赖/在飞评审）中加入 frozen 检查：frozen=True 时跳过派发并记 INFO。该检查 MUST 位于闸门内容校验之前，使冻结 spec 不再重放「派发→拦截→冻结」流程。

#### Scenario: 重启回放不重放拦截流程

- **WHEN** daemon 重启后 _diff_specs 空快照把 frozen=True 的 ready spec 整批回放 spec_ready
- **THEN** _on_spec_ready 跳过派发（INFO 留痕），闸门 ERROR 不再产生

#### Scenario: 冻结字段被外部抹除时由升级冷却兜底

- **WHEN** 外部整文件重置把 frozen 字段抹为缺省且重启回放放行了该 spec
- **THEN** 闸门照常拦截（语义不变），但升级侧受下一 Requirement 冷却约束，不触发 Administrator 召唤

### Requirement: daemon_errors 升级冷却与孪生指纹合并

admin_monitor 的 daemon_errors 升级路径（_detect_daemon_errors）MUST 对「daemon 启动后首次扫描回放的已知指纹」实施指纹级冷却：重启后冷却窗内同一指纹不计满升级阈值、不召唤 Administrator（INFO 留痕）；同一次扫描发现的孪生/成对指纹 MUST 合并为一条召唤信号。冷却参数为模块常量（与既有 DAEMON_ERROR_THRESHOLD 同层，MUST NOT 新增配置键）。

#### Scenario: 重启回放噪音不召唤巡检

- **WHEN** daemon 启动后首次扫描即命中与停机前相同指纹的 ERROR（≥阈值）
- **THEN** 冷却窗内不召唤 Administrator，日志记录冷却决策

#### Scenario: 成对指纹合并召唤

- **WHEN** 同一轮扫描中同源孪生指纹（同一闸门对两个 spec）同时达阈值
- **THEN** 仅创建一条召唤信号（一次 Administrator run），不再各指纹各召唤一次

#### Scenario: 真实新故障不受冷却压制

- **WHEN** 冷却窗后出现新的同指纹复现或全新指纹达阈值
- **THEN** 照常升级召唤（冷却仅约束重启后首扫窗口）

### Requirement: 日审摘要过滤夹具项目告警

日审数据摘要装配（core/self_review.py _collect_admin_summary）MUST 识别项目 fixture 标记（dashboard.yaml 项目条目，经 core/dashboard/registry.py 既有读取入口）：标记项目的告警 MUST NOT 计入未处理告警计数；摘要中 MUST 以显式 fixture 标注单独呈现或整体省略，MUST NOT 与真实项目告警混排。MUST NOT 静默删除或改写告警记录本身。

#### Scenario: 夹具告警不占日审摘要

- **WHEN** fixture:true 项目存在未处理 major 升级告警且日审运行
- **THEN** 数据摘要的未处理告警计数不含这些告警，且以 fixture 标注呈现（或省略）

#### Scenario: 非夹具项目行为不变

- **WHEN** 项目无 fixture 标记
- **THEN** 日审摘要装配行为与现状一致（计数口径与结构不变）

### Requirement: 夹具项目的自动召唤抑制

admin_monitor 的 distress 升级路径在 fixture 标记项目内 MUST 抑制自动召唤 Administrator（含全局巡检类 admin-global run），抑制决策 MUST 记 INFO 日志留痕（含错误指纹与抑制原因）；人工显式触发的管理员 run MUST NOT 受限。抑制 MUST NOT 修改或删除告警记录。

#### Scenario: 夹具噪音不召唤巡检

- **WHEN** fixture:true 项目内同源 ERROR 达 daemon_errors 升级条件
- **THEN** 不创建 admin-global run，日志记录抑制决策

#### Scenario: 人工触发不受限

- **WHEN** 人工在夹具项目显式发起管理员处置
- **THEN** 照常执行，不受抑制影响

#### Scenario: 告警记录保持可见

- **WHEN** 召唤被抑制
- **THEN** 对应告警记录仍按原样入库与展示（看板可查），仅召唤动作被阻断
