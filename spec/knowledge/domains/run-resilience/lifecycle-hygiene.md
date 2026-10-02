<!-- knowledge: capability=lifecycle-hygiene rev=1 sources=spec/archive/2026-09-10-run-lifecycle-hardening -->

# run 生命周期卫生

运行期的三类卫生规则：verifier 内部重试链尊重冻结、STATE 路径唯一化、预算对账偏差自动校正。

## 现行规则

- verifier/判定阶段内部的 failover 重试链（judge attempt 换网关重派、场景执行内部重试）在每次重试启动前检查所属 spec 的结构化 `frozen` 字段：为真时立即终止该链路（不再派发 attempt、不换 provider），run 以失败收场并保留既有错误记录；spec 未冻结时既有 failover 重试语义完全不变。
- STATE 路径唯一：框架内所有 STATE 读写只指向项目根 `STATE.md`；`.fenix/STATE.md` 历史遗留空文件不被读写，`.fenix/` 下不再生成新的 STATE.md。路径解析不依赖相对路径歧义——调用方显式传项目根路径或使用框架单源常量，既有自动化（重启恢复、admin 巡检）读到一致状态。
- 预算对账偏差自动校正：daemon 完成 run 收尾对账时，若 `used` 与 runs 目录正常收工 run 数存在偏差，以 runs 实际计数为准自动校正 `used`（INFO 日志含校正前后值与原因），不保留静默漂移的旧值；后续预算闸门按校正值生效。偏差源于既有豁免语义（runs 产物保留上限、链耗尽 run 不落产物等）时不触发校正，沿用 WARN 对账日志。

## 溯源

- 2026-09-10 run-lifecycle-hardening（spec/archive/2026-09-10-run-lifecycle-hardening） — 确立 verifier 重试链的冻结检查门、STATE 路径唯一化与预算对账偏差以 runs 实际计数为准的自动校正
