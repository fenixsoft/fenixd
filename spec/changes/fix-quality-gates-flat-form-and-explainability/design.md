## Context

add-quality-gates-visibility 建立了六道质量门禁的落盘/读侧合成契约：run 内 3 项自查渐进写
`.fenix/verify-progress/<spec>/quality-gates.json`（嵌套形态 `{"gates": {...}}`），读侧
`core/dashboard/data/quality_gates.py::parse_quality_gates` 与框架守卫 2 项、ocr 车道产物合成
统一 6 道。落盘是 prompt 软约束，`result_gate._check_quality_gates_soft` 宽松对账只记 WARNING。

2026-09-24 事故（add-code-review-concurrency-and-429-resilience）：implementer 写出顶层平铺
形态（缺 gates 包裹层），对账 WARNING 后放行，读侧取 `file_data.get("gates")` 落空把两项已
通过的 run 自查门判 pending（detail 空串），UI 呈现「只过 4/6 且未过项零解释」，人工全程无感
（告警只在 daemon 日志）。数据修复已人工完成，本变更治理机制面。

## Goals / Non-Goals

**Goals:**

- 读侧平铺形态容错：写侧漏包裹层时结论不丢失（结果可恢复，而非全部 pending）。
- pending/unknown 空详情的门项有固定归因文案，UI 无「零解释未过项」。
- 形态违规接 admin_alerts 人工告警面，脱离「只有 daemon 日志」的盲区。

**Non-Goals:**

- 不改变落盘契约（嵌套形态仍是唯一合法写法）、不改 implementer 提示词强度。
- 不改变宽松对账「MUST NOT 打回/失败终态/预算消耗」的软约束边界。
- 不做前端改动（文案由读侧填充，经既有 `gateDetailText` 透传）。
- 不处理 STATE.md 侧的门禁语义（框架守卫 2 项、ocr 车道三态）。

## Decisions

1. **平铺判定实现为 `quality_gates.py` 内部纯函数 `_adopt_flat_form(file_data) -> dict`**，
   在 `parse_quality_gates` 既有 `parsed` 判定之后调用：仅当 `gates` 键缺失或非 dict 时尝试。
   判定规则按 specs/quality-gates-form-tolerance 固化（候选门集非空 + 无枚举外 dict 值才采信；
   契约外 gate-id 交由既有 RUN_GATE_IDS 遍历面自然忽略，不在判定层拦截）。采信产物直接作为
   `file_gates`，下游零改动——保证与嵌套路径行为逐字节一致。

2. **兜底文案收口在 `parse_quality_gates` 返回前的单点后处理**（组装 items 后统一扫描一遍），
   不在各合成函数散落——六道门来源不同（落盘/ocr 车道/框架守卫），单点后处理保证
   「只填空、不覆盖」的语义一目了然，且新增门来源时自动获得兜底。文案常量与既有
   `GATE_DESCS` 同区放置并注释契约来源。

3. **告警经 `AdminStore.append_if_absent` 写入**（core/admin_store.py 的
   `append_if_absent(entry, is_inflight)`：is_inflight 在途谓词由调用方提供、
   单锁内查重+追加，满足「未处理期间不重复刷屏」）。`_check_quality_gates_soft`
   内已有 AdminStore 使用先例（result_gate.py:1473）可直接参照。signal_type 取
   `quality-gates-form-drift`，severity `info`，不注册 choices（落入不可裁决信号桶，
   人工确认处理即可，对齐 alert_routes 既有分派语义）。告警 entry 携带 spec 名、
   文件相对路径、违规描述。写入整体 try/except fail-open（仅记日志）。

   entry 字段两点固化约定（spec-review 评审修补，防消费面踩空）：

   - **`kind` 必须显式写 `SIGNAL`**：`_normalize_entry` 无 kind 默认值，而
     admin_alerts 消费面按 kind 分派——`unhandled()` / `mark_handled` 只认
     ESCALATION、`mark_signal_handled` 只认 SIGNAL，漏写 kind 的告警两个闭环
     端点都不匹配（处置 404 死胡同）。kind=SIGNAL 时面板可见性成立（activities
     未处理列表读 `read_all()` 不分 kind，前端 visible 过滤器只剔乐观移除），
     闭环走 `mark_alert_handled` → `mark_signal_handled`。
   - **携带机器可读类别字段 `violation_class`**（`missing-gates` / `bad-json` /
     `out-of-contract-gate-id` / `out-of-enum-status` 四值，与四类违规一一对应）：
     signal_type 单值固定，is_inflight 谓词按 `(spec, signal_type, violation_class)`
     判在途——否则四类违规无法按类别判重，一类未处理会抑制其余三类（比 spec
     「按 (spec, 文件, 违规类别) 不刷屏」的粒度更粗）。

   signal_type 不在 `STORED_SIGNAL_TYPES`（admin_monitor.py:384 封闭白名单）内，
   monitor 摄取循环跳过；`unhandled_for` 既有调用方均按具体 signal_type 精确匹配、
   与新值无碰撞——新告警不触发任何自动唤起/派发，「只加可见性不加强度」在
   消费面成立。

4. **平铺形态也发告警**（spec 已固化）：读侧容错是兜底而非豁免，写侧偏离契约的事实
   仍要让人工可见，否则平铺会成为「静默容忍的坏写法」。

## Risks / Trade-offs

- 平铺容错可能让坏写法固化 → 以告警（Decision 4）+ 契约注释「平铺为读侧兼容非合法写法」
  对冲；落盘契约文本不变。
- 判定规则与「损坏文件 unknown」的边界：枚举外 dict 值整体不采信（宁可 pending 不误读），
  已在 spec Scenario 固化分支。
- 兜底文案可能掩盖真实成因多样性（pending 成因不止一种）→ 文案措辞中性
  （「run 在飞或自查结果未落盘」枚举两种主要成因），且已有具体归因的门项不覆盖。
- admin_alerts 为环形裁剪（MAX_RECORDS=150），告警风暴会挤掉重要条目 → append_if_absent
  去重天然限制同源条数，风险可控。

## 迁移与兼容

- 零迁移：读侧容错对既有嵌套形态文件行为逐字节不变（Scenario「嵌套形态优先零回归」）；
  历史平铺文件（若有）读侧自动恢复结论，无需数据修复。
- 测试：`tests/test_quality_gates_progress.py` 扩展平铺判定与兜底文案分支；
  对账告警新增 `tests/test_quality_gates_soft_alert.py`（AdminStore.append_if_absent
  断言 + 软边界零回归断言）；前端 `qualityGates.test.mjs` 既有断言零变化（纯透传）。
