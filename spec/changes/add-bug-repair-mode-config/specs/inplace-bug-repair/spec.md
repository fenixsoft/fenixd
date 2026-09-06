# inplace-bug-repair 能力增量（add-bug-repair-mode-config）

> bug-found 处置的修复方式分流依据由「SPEC 名称前缀」改为「`admin.bug_repair_mode` 配置」；原地打回行为语义不变；补充 derive 模式分支。

## MODIFIED Requirements

### Requirement: bug-found 修复方式分流

验证裁决采纳 `bug-found` 结论且失败被归为真实产品缺陷时，框架 MUST 按 `admin.bug_repair_mode` 配置分流处置（未配置缺省 `inplace`），分流依据 MUST NOT 依赖 SPEC 名称前缀（`fix-` 前缀判定退役）。

**inplace 模式（缺省）**——框架 MUST 对父 SPEC 原地打回：

1. 内部字段 `_verify_fail_rounds` 递增 1 并持久化。
2. 状态重置为 `implementing`（保留 branch/error 等既有字段语义）。
3. 在父 SPEC 的 `tasks.md` 末尾追加或更新「`## 验证修复`」任务段，MUST 引用 `spec/changes/<spec>/verification-report.md` 并指明修复对象为报告中的「真实产品 Bug」；段内 MUST 标注当前失败轮数。
4. 后续实现与重验由既有派发循环与验证链路接管，MUST NOT 创建 fix-* 子 SPEC。

追加任务段时 MUST NOT 改写父 SPEC 既有任务与勾选状态。原地打回对任何 SPEC 生效，包括名称带 `fix-` 前缀的 SPEC。

**derive 模式**——框架 MUST 按既有派生逻辑创建或复用 fix-* 子 SPEC：fix- 前缀逐级命名（`_resolve_fix_spec_name`）、非终态子 fix 去重守卫、族谱收敛 governor（深度/宽度限制与人工放行）均照常生效。fix-* 子 SPEC 完成（done）后框架 MUST 自动触发父 SPEC 重验（既有闭环）。

#### Scenario: 首次验证失败原地打回（默认）

- **WHEN** 某 SPEC 验证裁决返回 bug-found（真实产品缺陷），`admin.bug_repair_mode` 未配置，其 `_verify_fail_rounds` 为 0
- **THEN** 计数器变为 1，SPEC 状态变为 implementing，tasks.md 末尾出现引用 verification-report.md 的「验证修复」段（标注轮数 1），无任何新 fix-* SPEC 被创建

#### Scenario: fix-* 命名的 SPEC 失败也原地打回

- **WHEN** 名称带 `fix-` 前缀的 SPEC（如人工立项的 fix-daemon-lifecycle-races）验证失败，配置为 `inplace` 或未配置
- **THEN** 按原地打回处置（计数器递增 + implementing + 注入修复任务），MUST NOT 派生 fix-fix-* 子 SPEC

#### Scenario: 二次失败递增轮数而非新建链条

- **WHEN** 同一 SPEC 修复后重验再次 bug-found
- **THEN** 计数器变为 2，状态再次回到 implementing，「验证修复」段内轮数注记更新为 2，族谱深度保持 0

#### Scenario: derive 模式派生子 fix 并闭环重验

- **WHEN** 某 SPEC 验证失败，`admin.bug_repair_mode` 配置为 `derive`
- **THEN** 创建（或复用在飞）fix-* 子 SPEC 并派发实现；子 SPEC 完成后父 SPEC 自动进入重验

### Requirement: 失败轮数升级冻结闸门

同一 SPEC 的 `_verify_fail_rounds` 达到模块常量阈值（3）时，框架 MUST 停止原地打回：SPEC 状态置为 `blocked`，MUST 发送 human-escalation-alerts 告警，内容包含 SPEC 名、失败轮数与 verification-report.md 路径。人工介入调整状态后，计数器语义由人工裁决决定（人工重置即重新获得自动修复机会）。该闸门仅作用于 inplace 模式的原地打回计数。

#### Scenario: 连续三轮失败冻结升级

- **WHEN** 某 SPEC 第二轮修复后重验第三次 bug-found，计数器即将达到 3
- **THEN** 不再重置 implementing 也不追加任务段，SPEC 状态置为 blocked，产生含轮数与报告路径的人工升级告警

#### Scenario: 计数器跨重启持久

- **WHEN** SPEC 经历一次失败打回后 daemon 重启，随后重验再次失败
- **THEN** 计数器从持久化值继续递增，不因重启归零重置升级时机
