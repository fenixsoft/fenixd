## Context

cloud-phone 首跑（2026-11-08）三个告警治理缺陷实证：

1. **校验双轨漂移**：`core/dashboard/data/config_admin.py:2565-2579`（Dashboard 保存路径）对 `agents.models.*.provider` 引用做注册表校验并拒绝保存；`core/config.py:1700`（daemon 加载/热加载路径）对同样引用仅记 ERROR「已跳过，不阻塞加载」。用户经文件编辑把全局链复制进项目（provider 名 `bigmodel.cn` vs 项目注册 `bigmodel-cn`），48 条 ERROR 静默跳过、全链失效、agent 继续派发失败——错误信号（spawn 失败）与原因（配置名字错）之间无任何可循迹的桥。
2. **实现期契约预检噪音**：`core/admin_monitor.py` 巡检周期（`admin.interval_minutes` 缺省 5 分钟）对实现中 spec 的 `verify_contract_missing` 以 major 召唤 Administrator；首跑 6 条 major 告警，而此时契约按流程本就尚未起草（预检文案自认「起草落位即可，勿复位」）。
3. **修复后告警滞留**：模型配置 08:32 修复生效，但同根因旧告警（评审连挂/秒挂/daemon_errors 衍生）无失效机制，28 条永久滞留面板，「已修复」与「待处理」不可分辨。

## Goals

- 配错一眼看出来：未注册 provider 在加载侧即产生带相似名建议的 actionable 告警
- 首个 SPEC 期间契约预检静默，进入验证期才恢复 major 语义
- 修复生效后同根因告警自动失效，面板「未处理」计数回归真实

## Non-Goals

- 不改变 Dashboard 保存路径既有拒绝语义（只做规则单源化抽取，行为不变）
- 不做告警自动修复（git add 等动作仍走既有裁决执行器/人工）
- 不重写告警存储结构（`cause` 为增量字段，兼容既有账本）

## Decisions

### D1 校验规则单源化：抽公共实现，两路径共用

把 `config_admin.py` 的引用校验抽为可复用函数（含角色遍历、字符串/对象数组两形态、坏名收集），daemon 加载路径（`core/config.py`）与 Dashboard 保存路径共用。行为差异保持在**处置层**：保存路径继续 ValueError 拒绝（用户当场看到），加载路径转配置告警（daemon 不能因配置坏拒绝启动——既有「不阻塞加载」的可用性纪律保留，但「跳过」必须可观测）。

### D2 相似名建议：规范化比对 + 编辑距离

候选建议算法：对未注册名与注册表名做规范化（小写、`.-_` 归一）后比对，完全相等或编辑距离 ≤2 视为相似建议（`bigmodel.cn`→`bigmodel-cn` 命中）；无候选时输出注册表清单。实现放校验公共函数内，两路径同样受益（Dashboard 保存报错文案也带建议）。

### D3 分配失效与回落划界：以「有无分配条目」为唯一判据

与 `harness-default-fallback` 的回落判定（env 链键存在性）同源对齐：角色有 `models` 条目 → 即使校验后链空也是「分配失效」态（告警 + `[model-chain-unavailable]` 归因，不回落、不打 harness-default WARN）；角色无条目 → 「无分配」回落态（既有语义不变）。判定单源：加载侧产出每角色的链解析结果（有效条目集 + 失效原因），runner 侧消费同一结果，禁另立口径。

### D4 契约预检分级：状态驱动 + 一次性去重

`admin_monitor` 巡检对 `verify_contract_missing` 的分级按 spec 状态驱动：implementing 等实现中状态 → info + 同 spec 一次性（去重键 `signal_type:spec`，spec 状态迁移离开实现流程时去重态复位，验证期按既有 major 语义重新发信号）；其他状态 → 既有 major 语义。去重态持久化跟随告警账本（重启不重发）。

### D5 supersede 触发观测点：每根因一个可判定判据

根因封闭枚举 + 每根因一个修复观测点：
- `model-chain`：校验后加载成功（无未注册引用告警再产生）且其后首个派发成功
- `harness-cli`：启动自检可达（对接 SPEC ① 自检态）
- `init-stray`/`contract` 等其余根因：首版不自动失效（保留人工处置），枚举可扩展

触发时同根因未处理告警**单事务批量**标记 superseded（原子写 + 失效时间 + 触发观测点记录），面板折叠「已失效」组、未处理计数扣除、升级链引用解除。

## Risks

- 加载路径告警的噪音控制：校验告警按「指纹（角色+坏名集合）」一次性去重（同指纹不重复发），修复后指纹消失自动复位——复用既有 daemon_errors 指纹冷却机制形态
- supersede 误失效：观测点要求「派发成功」实测证据，不以「配置加载成功」单条件触发；误触发可人工把告警恢复未处理（面板操作，语义为撤销 supersede）
- Dashboard 保存路径报错文案变化（加相似名建议）：既有测试断言可能需同步，属预期修正

## Migration Plan

- 既有合法配置零变化；既有账本告警无 `cause` 字段按「未知」根因呈现（不参与 supersede），新信号起强制带标签
- 存量滞留告警（cloud-phone 28 条）：SPEC ① 自愈修复 CLI 根因后，`harness-cli` 根因告警由观测点自动 supersede；模型链根因同理；无法自动归因的由人工处置

## Revert Plan

校验/supersede/分级均为增量路径；`cause` 字段读侧容错缺席，revert 无账本迁移。
