<!-- knowledge: capability=daemon-error-escalation rev=2 sources=spec/archive/2026-09-11-improve-hot-reload-robustness,spec/archive/2026-09-29-evo-alert-noise-governance -->

# daemon 错误升级上报

AdminMonitor 巡检 `fenixd.log`，把「同指纹 ERROR 短窗复现」升级为召唤 Administrator 处置的 critical 信号。

## 现行规则

- 升级口径：最近 10 分钟窗口内同指纹 ERROR 复现 ≥2 次，且最近两次同指纹条目间隔 ≤5 分钟，产生 `daemon_errors` critical signal；中间被 INFO/WARNING 或其他错误打断不影响同指纹复现计数。
- 错误指纹为 component 与归一化 message 的组合 hash。归一化采用保守集：ISO-8601 时间戳、UUID、≥16 位 hex 串、纯数字序列替换为占位符；路径与文字骨架不归一化。非 JSON 格式日志行回退为 raw 行归一化 hash，解析失败不崩溃。
- 防抖边界：单次错误不升级；同指纹两次出现间隔 >5 分钟不升级（视为孤立抖动）；较早一次超出 10 分钟窗口不升级——恢复靠窗口滑动自然过期，无需显式清零。
- timestamp 缺失或解析失败的 ERROR 行仍计入指纹桶（间隔约束按满足处理），方向为宁可多告警不漏告警。
- 升级命中继续经过既有同 (spec, signal_type) 冷却节流，冷却期内再次满足升级条件仅记录、不重复唤起 administrator。
- 指纹级重启冷却：daemon 启动后冷却窗（30 分钟，模块常量）内的「已知指纹」不计满升级阈值、不产信号、不召唤 Administrator，冷却决策记 INFO 留痕；窗后同指纹复现或全新指纹照常升级——冷却仅约束重启后首扫回放窗口（重启不清日志，首扫即命中与停机前相同指纹；重启前已召唤过一次，同批指纹短期重复召唤收益趋零）。
- 「已知指纹」= 本生命周期内已产生过升级信号（内存时间戳在案），或告警库存有携带该指纹的 daemon_errors 记录（跨重启对账：store 无结构化指纹字段，以信号 description 的「指纹 <前 8 位>」稳定文案对账，同轮合并信号对每个指纹保留该文案）。store 读取失败按未知指纹处理（fail-open：冷却缺失的最坏后果是重启后多召唤一次，不掩盖真实新故障）。已知指纹对账仅服务冷却窗分支，冷却窗关闭后不为每个达阈指纹做全库扫描。
- 同轮孪生指纹合并：同一轮扫描中多个指纹同时达升级阈值时按指纹聚合为一条召唤信号、一次 Administrator run，而非每指纹各产一条召唤；合并信号的沉淀状态哈希取全部指纹排序后的稳定拼接（与日志首现顺序无关）。指纹级冷却是既有 (spec, signal_type) 信号级节流的补口而非替代——孪生指纹各算各的时会绕开单条信号记录的锚定，两道判定并存、信号级节流语义不变。
- 窗口（10 分钟）、间隔上限（5 分钟）、复现次数（2 次）、重启冷却窗（30 分钟）保持模块常量，不新增配置键（规避「新增配置项须带 Dashboard 界面」约束）；调整灵敏度通过修改模块常量实现。

## 溯源

- [2026-09-11 improve-hot-reload-robustness](spec/archive/2026-09-11-improve-hot-reload-robustness/) — 错误升级改为指纹复现口径，固化指纹归一化、防抖边界、缺 timestamp fail-closed 与阈值不配置化
- [2026-09-29 2026-09-29-evo-alert-noise-governance](spec/archive/2026-09-29-evo-alert-noise-governance/) — 新增指纹级重启冷却（重启后首扫回放的已知指纹 30 分钟窗内不升级不召唤，窗后/全新指纹照常）与同轮孪生指纹合并召唤（多指纹一轮只产一条信号一次 run）
