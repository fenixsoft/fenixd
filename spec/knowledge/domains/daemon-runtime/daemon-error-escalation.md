<!-- knowledge: capability=daemon-error-escalation rev=1 sources=spec/archive/2026-09-11-improve-hot-reload-robustness -->

# daemon 错误升级上报

AdminMonitor 巡检 `fenixd.log`，把「同指纹 ERROR 短窗复现」升级为召唤 Administrator 处置的 critical 信号。

## 现行规则

- 升级口径：最近 10 分钟窗口内同指纹 ERROR 复现 ≥2 次，且最近两次同指纹条目间隔 ≤5 分钟，产生 `daemon_errors` critical signal；中间被 INFO/WARNING 或其他错误打断不影响同指纹复现计数。
- 错误指纹为 component 与归一化 message 的组合 hash。归一化采用保守集：ISO-8601 时间戳、UUID、≥16 位 hex 串、纯数字序列替换为占位符；路径与文字骨架不归一化。非 JSON 格式日志行回退为 raw 行归一化 hash，解析失败不崩溃。
- 防抖边界：单次错误不升级；同指纹两次出现间隔 >5 分钟不升级（视为孤立抖动）；较早一次超出 10 分钟窗口不升级——恢复靠窗口滑动自然过期，无需显式清零。
- timestamp 缺失或解析失败的 ERROR 行仍计入指纹桶（间隔约束按满足处理），方向为宁可多告警不漏告警。
- 升级命中继续经过既有同 (spec, signal_type) 冷却节流，冷却期内再次满足升级条件仅记录、不重复唤起 administrator。
- 窗口（10 分钟）、间隔上限（5 分钟）、复现次数（2 次）保持模块常量，不新增配置键（规避「新增配置项须带 Dashboard 界面」约束）；调整灵敏度通过修改模块常量实现。

## 溯源

- 2026-09-11 improve-hot-reload-robustness — 错误升级改为指纹复现口径，固化指纹归一化、防抖边界、缺 timestamp fail-closed 与阈值不配置化
