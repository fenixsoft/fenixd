# ADR-075：bug 修复方式配置化双模式，名称前缀分流退役

date: 2026-09-12
status: accepted

## Context

ADR-034 裁定 bug-found 一律原地打回、派生路径退役，但处置入口以 `fix-` 名称前缀分流 legacy 派生路径；人工立项的 fix-* 名字 SPEC 被误分类进派生通道（fix-fix-daemon-lifecycle-races 事故）。名称前缀是不可靠的模式判据——它表达的是命名惯例，不是处置意图。

## Decision

- 修复方式由 `admin.bug_repair_mode` 显式配置：字符串枚举 `inplace`（缺省）/ `derive`；分流判据从名称前缀改为显式配置，前缀豁免退役——inplace 模式对 fix-* 名字 SPEC 同样原地打回。
- derive 模式完整保留派生闭环：非终态子 fix 去重守卫、族谱收敛 governor（深度/宽度阈值 + waiver）、done→重验父；派生命名沿用逐级前缀（`fix-<name>` 失败 → `fix-fix-<name>`）。
- 配置在每次 bug-found 事件实时读取（走 `get_admin_config` 同源路径，享受 30s 热更新），不做实例级缓存：切换模式后下一次事件即生效。
- 模式切换不做在飞链迁移：derive→inplace 切换后在飞 fix-* 链自然终态，父 SPEC 重验再失败时按新配置原地打回。

## Consequences

- 推翻 ADR-034「一律原地打回、派生代码退役」的绝对口径：原地打回仍是缺省与主路径，派生降级为显式配置的可选策略；派生治理（族谱 governor、守卫）作为 derive 模式护栏长期存在，不再退役。
- 枚举而非布尔，为未来第三种修复策略留扩展位；修复方式的全部语义变化必须经配置表达，禁止回退到名称推断。
