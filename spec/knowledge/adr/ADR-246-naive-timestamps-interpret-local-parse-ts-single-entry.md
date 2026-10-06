# ADR-246：naive 时间戳唯一解读为本地时区，解析单源 timelib.parse_ts

date: 2026-10-07
status: accepted

## Context

全仓约 398 处 timezone 引用中，存储层主流是 `now(timezone.utc)`，但 72 处裸 `datetime.now()`（naive 本地）混入写侧；读侧为消化歧义演化出 4 种互相矛盾的 naive 解读（regression naive→本地、timeline 与 code_review_routes naive→UTC、evolution naive→本地→UTC），转换轮子重复 ≥8 份。两个文件的注释各自引用相反的「项目约定」为自己背书——混乱已被制度化，日志分析与时间展示反复出现 8 小时偏差困惑。

## Decision

naive 时间戳的全框架唯一解读为系统本地时区：`timelib.parse_ts` 对无时区后缀输入按本地时区解读，任何模块不得实现第二种 naive 解读。机器时区固定 Asia/Shanghai 无 DST，无换算陷阱。依据是存量 naive 数据实测多数产自本地 `now()`（self_review 字段、外部/人工 marker），剥时区写入链（`astimezone().replace(tzinfo=None)`）产出 naive 本地而非 UTC——naive=本地与实际数据分布一致。备选「naive→UTC」与「全链 UTC」口号字面一致，但会把存量 naive 数据错读 8 小时、需随每批迁移修数据；备选「严格拒绝 naive」使外部人工文件无法自动改写——均否决。配套：全部时间产生/解析/序列化/渲染收拢进 `core/timelib.py` 六函数单源，`parse_ts` 失败返回 None（容错 house style），AST 守卫棘轮（白名单只许收缩、僵尸条目报失败）防止第二种解读回潮。后续全仓调用点迁移 SPEC 必须消费同一契约；发现 API 缺口以 ADDITIONAL requirement 扩展函数，不改已冻结签名。

## Consequences

- 同一 naive 串在全框架任何读侧得到同一时刻，8 小时偏差困惑失去根源；timeline 域部分 naive UTC 形态存量展示时刻平移 8 小时（已知差异，切换前验读留痕）。
- 迁移前与唯一策略并存的残留点（如 admin_store created/last_seen 的 naive→UTC 归一化）以守卫白名单显式登记、逐批收缩，并存期可审计而非隐性分叉。
- naive=本地与新解读天然一致，无需数据迁移；写侧最终收敛到 `to_storage`（Z 后缀 aware UTC）由后续迁移批次承接。
- 代价：「naive=本地」与「全链 UTC」口号的字面张力靠本 ADR 与 timelib 文档承载；机器时区若变更（脱离 Asia/Shanghai），存量 naive 数据解读整体平移。
