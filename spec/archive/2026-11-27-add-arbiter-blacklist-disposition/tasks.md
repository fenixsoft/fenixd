# Tasks — Arbiter 处置黑名单化与场景副作用静态防线

## Deliverables

```yaml
- path: core/pm_engine/arbiter_blacklist.py
  kind: new
- path: core/verify_engine/scenario_semantics.py
  kind: new
- path: core/verify_engine/scenario_static_check.py
  kind: modify
- path: core/pm_engine/arbiter.py
  kind: modify
- path: core/pm_engine/escalation_chain.py
  kind: modify
- path: core/pm_engine/verification/escalation.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/arbiter.md
  kind: modify
- path: tests/test_arbiter_blacklist.py
  kind: new
- path: tests/test_scenario_semantics.py
  kind: new
- path: tests/test_scenario_static_check.py
  kind: modify
- path: tests/test_escalation_chain.py
  kind: modify
```

## 1. 黑名单单源（arbiter-blacklist-disposition）

- [x] 1.1 新建 `core/pm_engine/arbiter_blacklist.py`：禁项枚举 B1–B5 单源（编号/标题/机器可判定谓词/prompt 文案渲染）。B1 生产账本副作用谓词（生产存储写面单源：admin_alerts.json 状态写、批量清理端点族 `POST /api/alerts/clear`/mark_all_handled、告警裁决消费端点）；B2 人工裁决通道代行（裁决包消费/关闭面）；B3 框架自有产物破坏性直执（经证明器门获准的场景成对写为唯一白名单例外）；B4 验证契约放宽（消费证明器判定）；B5 越界写（STATE.md 本体、他 spec 分支、主树源码）。`enabled` 开关：false 时谓词全部直通放行（降级态与测试逃生门）；导出 prompt 禁项段与判定焦点反转段文案渲染函数（与谓词同源）；`enabled=false` 时 prompt 同步停用禁项段注入（回滚态 prompt 行为与合入前一致，避免门直通而模型仍自缚保守偏差）
- [x] 1.2 新建 `tests/test_arbiter_blacklist.py`：五禁项谓词正反例（事故形态样本：位置点击+`POST /api/alerts/clear` 守卫=B1R3、裁决包 id 消费=B2、删 `_scenarios_full.json` 无门=B3、经门场景成对写=放行、直写 STATE.md=B5）；`enabled=false` 直通锚点；prompt 文案导出与谓词同源一致性断言

## 2. 语义保持证明器（arbiter-blacklist-disposition）

- [x] 2.1 新建 `core/verify_engine/scenario_semantics.py`：`prove_scenario_fix(old_scenarios, new_scenarios, justifications) -> ProverVerdict` 纯函数——逐场景逐断言 diff 三分类（tighten/relax/neutral）：期望语义比较表（exact/contains→regex=relax 除非该断言附正当性码；regex 收窄=tighten；删除断言/删除场景=relax）；选择器作用域化（同步骤类型下锚定范围收紧）/等待时序调整/文案注记=neutral；正当性码白名单闭合（首码 `global-counter-nondeterministic`，码→知识锚 `spec/knowledge/domains/verify-pipeline/scenario-env-coupling.md`）；B1 合规化 carve-out：移除步骤命中位置点击改状态/批量破坏确认形态且无新增生产端点→整体中性；输出净判定（通过=无未获准 relax）与逐条判定摘要（供报告 `scenario_fixes` 字段与降级留痕）
- [x] 2.2 新建 `tests/test_scenario_semantics.py`：双向锚定——选择器作用域化收紧放行；徽标 exact `3`→regex `\d+` 带码放行；同改写无码拒绝；场景删除拒绝；破坏性确认路径改安全变体（移除确认点击+机械形态断言）carve-out 中性；成对落盘契约锚点（先 `_scenarios_full.json` 后 `test_scenarios.json`、同契约版本戳，与 judge 受理门同构）

## 3. 静态规则族 R1–R5 与回扫入口（scenario-static-defect-scan）

- [x] 3.1 `core/verify_engine/scenario_static_check.py`：挂载 R1（改状态 click×位置选择器交叉判别，high——规则函数签名向后兼容扩展接收场景级上下文实现 click×expect_network 关联）、R2（网络守卫过宽，medium）、R3（批量破坏端点确认路径执行，critical）、R4（全局聚合量绝对值断言，medium）、R5（`<tag>:text-matches` 组件按钮锚定，medium）；新增回扫 CLI 入口 `python3 -m core.verify_engine.scenario_static_check --scan <dir>`（只读，逐场景×逐规则×严重度 findings 汇总输出）；既有 4 规则与 fail-open 语义零改动
- [x] 3.2 `tests/test_scenario_static_check.py`：内嵌事故形态 fixtures（python 字面量）双向锚定——位置点击 `button:has-text("标记已处理")`+`.first`+expect_network 命中 R1/R2、种子行作用域改写版+记录级守卫零命中、确认弹窗破坏主键+批量端点守卫命中 R3、`.ant-badge-count` exact `3` 命中 R4、regex `\d+` 形态零命中、`button:text-matches("取\s*消")` 命中 R5、裸 `:text-matches` 零命中；既有 4 规则既有用例全绿回归锚点

## 4. prompt 黑名单化与报告契约（arbiter-lane）

- [x] 4.1 重写 `agents/arbiter.md`（保骨架：铁律 5 类/许可清单/五段报告模板不变）：处置哲学反转段（默认可救+枚举禁项，禁项文案与 `arbiter_blacklist` 单源口径一致）、判定反例段废止换禁项判定段（判定焦点由"是否在白名单内"反转为"是否命中禁项"）、红线 2 修订（可写面=`{report_path}` ∪ 经证明器门获准的场景成对写）、救回工具箱段（T1 场景鲁棒性修复机械类白名单/T2 稳态复跑探针只读纪律与证据落报告）、报告契约补 `rescue_evidence`（scenario_fix|probe_transient|artifact_rescue|counter_reset|cleanup）与 `scenario_fixes`（文件+修复类+证明器判定摘要）字段说明
- [x] 4.2 `core/agent_runner/maintenance_runs.py` `run_arbiter`：信封/prompt 变量接线禁项文案；outcome 合法性既有硬门不变，新字段不做 run 级硬校验（向后兼容旧报告）

## 5. resolved 硬门与早期触发面注册（arbiter.py）

- [x] 5.1 `core/pm_engine/arbiter.py` `_apply_disposition_side_effects` 入口前置三级硬门：①黑名单谓词扫描报告动作面（actions_taken/scenario_fixes/cleanup_paths/budget_override）②scenario_fixes 逐条过证明器 ③rescue_evidence 至少一类有效；任一失败→复用 `_on_escalate` 降级路径（裁决包原位挂靠+台账降级留痕：原 outcome/命中禁项编号或证明器判定/终态），run 记合法终态不折算失败（不触发同签名重试计数）；`enabled=false` 硬门直通
- [x] 5.2 `in_trigger_surface` 加性注册 `verify_repeat_failure`（早期介入路由信号）；既有触发面行为零变化锚点

## 6. 早期介入路由与救回防抖（escalation-chain）

- [x] 6.1 `core/pm_engine/verification/escalation.py` 验证报告消费侧：连续 ≥2 轮同失败签名检测（指纹单源=失败场景 id 集+断言集哈希），发射 `verify_repeat_failure` 触发（载荷含签名+逐轮失败面对照+judge 归因摘要如有）；与预算耗尽冻结路径去重（同签名在飞/已派发合并，不双派）；发射前检查 `arbiter_blacklist.enabled`（false 不发射，D9 降级态断言）；既有冻结→链升级路径逐字节一致
- [x] 6.2 `core/pm_engine/escalation_chain.py`：signatures 条目扩展 `last_rescue_fingerprint`（条目级 fail-open 归一，脏值置空，`:113` 先例同构）；救回防抖（同指纹不重派——按既有配额/上升路径直达人工+台账防抖命中留痕；签名变化重获派发资格按新签名计数；复位窗/spec 状态迁移清零沿用）；`verify_repeat_failure` 路由跳过 Admin 直达 Arbiter 级
- [x] 6.3 `tests/test_escalation_chain.py`：两轮同签名触发/单轮不触发/签名逐轮变化不触发/与冻结路径去重不双派/冻结路径行为零变化锚点/防抖同指纹不重派/指纹变化重派/复位窗清零恢复

## 7. 全量回归与降级态审计

- [x] 7.1 全量测试面回归绿；`arbiter_blacklist.enabled=false` 降级态审计：硬门直通、早期触发不发射、judge 受理门/预算口径/ADR-318 行为零变化
- [x] 7.2 回扫 CLI 冒烟：对 tests 内嵌 fixtures 场景集跑 `--scan` 出 findings 汇总（只读断言不写盘），命中/零命中与守卫测试结论一致
