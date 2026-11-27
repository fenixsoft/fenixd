# Design — add-arbiter-blacklist-disposition

## Context

Arbiter 车道现行处置模型为「白名单 + 判定反例」（`agents/arbiter.md`，处置哲学"宁可升级人工"；机械面 `core/pm_engine/arbiter.py` `_apply_disposition_side_effects`:1320 只执行显式 status 解冻/cleanup_paths 白名单删除/budget_override clamp）。consolidate-alerts-to-ops-page 事故（2026-11-12）实锤两点：①「改断言=MUST escalate 反例」方向性错误——人工改 5 个断言后解冻即全绿；②E2E 机器人可对生产账本产生真实副作用且场景编写期无静态防线。近 3 天台账（`.fenix/arbiter_ledger.jsonl` 48 条，11-09 后 4 案）显示升级人工的 2 案均可救回，且救回动作全部落在机械可判域（场景鲁棒性修复、稳态复跑）。judge 修复写回受理门（`judge-repair-scenario-writeback-gate`）已确立成对落盘契约，但其拦截能力边界明确不含语义级错误（断言弱化/选择器失配）——本设计的证明器正是补这一层。

## Goals / Non-Goals

**Goals**：黑名单禁项单源（B1–B5）；语义保持证明器（B4 机械判别 + B1 合规化 carve-out）；救回工具箱 T1/T2；resolved 硬门与自动降级；早期介入路由与救回防抖；静态规则族 R1–R5 与回扫入口。

**Non-Goals**：不改 judge 写回受理门/预算口径/ADR-318 分化行为；不改 Admin 车道语义与人工裁决通道；R1–R5 不升级为阻断（fail-open 情报语义不变）；不做自然语言级"证明"（只做确定性断言集 diff 分类）；不做跨项目 dashboard 改动。

## Decisions

- **D1 黑名单单源 = python 模块**（`core/pm_engine/arbiter_blacklist.py`）：禁项谓词需要代码表达力（生产端点族清单、写路径判定、报告字段扫描），prompt 禁项文案由同模块导出注入。拒绝 yaml 配置（表达力不足）与 prompt/谓词双源（漂移风险——受理门知识页教训：机械门是唯一防线，prompt 只引导）。命名消歧：本模块为**处置动作面**禁项（对报告动作放行判定），与链级**触发面**黑名单 `chain.blacklist`（信号入链过滤 kill switch，`escalation_chain.py` 既有机制）不同层、互不冲突。
- **D2 证明器 = 确定性 diff 分类器**（`core/verify_engine/scenario_semantics.py` 纯函数）：机械门必须可复现、可测试、防模型漂移；拒绝 LLM 复核方案（不可复现即不可守卫）。分类规则表：期望语义比较（exact/contains→regex=relax 除非附正当性码；regex 收窄=tighten）、选择器作用域化/等待调整/文案注记=neutral、场景删除=relax；正当性码白名单闭合（首码 `global-counter-nondeterministic`，锚 `spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md`）；carve-out=移除步骤命中 R1/R3 形态且无新增生产端点→整体中性。
- **D3 硬门接线点 = `_apply_disposition_side_effects` 入口前置**：黑名单扫描→证明器→证据类校验三级；任一失败复用 `_on_escalate` 降级（裁决包+台账留痕），run 记合法终态。拒绝在 `maintenance_runs.run_arbiter` 层做硬门（折算 run 失败会烧同签名重试配额，且"降级是处置结论而非执行故障"语义错误）。
- **D4 报告契约扩展向后兼容**：新字段 `rescue_evidence`/`scenario_fixes` 不做 run 级硬校验（旧形态报告不炸），由 resolved 硬门消费（缺证据类=降级）。
- **D5 prompt 重写保骨架**：`agents/arbiter.md` 保持铁律 5 类/许可清单/五段报告模板不变，仅反转处置哲学段、废止判定反例段换禁项段（文案与谓词单源对齐）、修订红线 2 可写面（`{report_path}` ∪ 经门场景成对写）。
- **D6 早期触发 = 加性新信号 `verify_repeat_failure`**：发射点在验证报告消费侧（`core/pm_engine/verification/escalation.py` 归因后），连续 ≥2 轮同失败签名检测，指纹单源=失败场景 id 集+断言集哈希；去重靠既有 `chain_signature`+in-flight；Admin 跳过（验证域修复非 Admin 拍板面）；冻结路径零变化。
- **D7 防抖状态 = signatures 条目扩展 `last_rescue_fingerprint`**：条目级 fail-open 归一（脏值置空——`escalation_chain.py:113` 先例同构），复位窗语义沿用。
- **D8 R1 需场景级交叉视图**：既有规则为单步局部模式，R1 依赖 click×expect_network 同场景关联——规则函数签名向后兼容扩展（默认参数），既有 4 规则零改动；fixtures 以 python 字面量内嵌守卫测试（不落 fixture 文件，避免场景文件形态双源）。
- **D9 降级态开关**：`arbiter_blacklist.enabled=false` → 硬门直通+早期触发不发射，行为与合入前一致（对齐 escalation-chain 既有关闭态零侵扰 requirement），即回滚路径。

## Risks / Trade-offs

- [证明器误放行弱化修复] → relax 默认拒+正当性码白名单闭合+双向 fixtures 守卫测试
- [证明器误拒合法修复] → 降级保留人工兜底（多一次人工不损可用性）；carve-out 覆盖本日事故主形态
- [早期触发 run 量膨胀] → 同签名≥2 阈值+配额 3 次/签名（单源现值，2026-11-03 定调 2→3）+防抖三重闸，run 量上界=签名数×3
- [R1 交叉判别误报干扰 judge] → fail-open 情报定位不阻断+合规写法 fixtures 零命中锚定+severity 分层
- [prompt 重写后模型行为漂移] → 机械门为唯一防线，prompt 仅引导；守卫测试锁报告契约

## Migration Plan

纯加性合入，无存量数据迁移；`escalation_chain` signatures 条目新字段按 fail-open 归一。合入后运维动作（不属本 spec 验收）：对本仓与各项目存量场景集跑一次回扫 CLI 出审计报告。回滚：`arbiter_blacklist.enabled=false` 直通。

## Open Questions

无——处置模型反转与三条台账修订（探针工具化/合规化 carve-out/介入前移带工具箱）已由用户裁定与台账复盘闭合。
