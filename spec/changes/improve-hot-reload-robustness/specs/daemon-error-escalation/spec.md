# daemon-error-escalation 增量规格

## ADDED Requirements

### Requirement: 指纹复现升级口径

daemon_errors 告警检测 MUST 以「最近 10 分钟窗口内同指纹 ERROR 复现 ≥2 次，
且最近两次同指纹条目间隔 ≤5 分钟」为升级条件，替代现行「日志尾部物理连续
ERROR ≥3」口径。中间被 INFO/WARNING 或其他错误打断 MUST NOT 影响同指纹
复现计数。

#### Scenario: 中间夹 INFO 的复现触发（事故回归）
- **WHEN** 两条 message 全等的 ERROR 相隔 30 秒，中间夹有 INFO 行
- **THEN** 下一次巡检命中升级条件，产生 daemon_errors critical signal

#### Scenario: 物理连续口径退役
- **WHEN** 两条同指纹 ERROR 被多条 INFO 分隔、尾部物理连续段长度为 1
- **THEN** 仍按复现口径触发升级（旧口径下此场景不触发）

### Requirement: 错误指纹归一化

错误指纹 MUST 为 component 与归一化 message 的组合 hash。归一化采用保守集：
ISO-8601 时间戳、UUID、≥16 位 hex 串、纯数字序列替换为占位符；MUST NOT
归一化路径与文字骨架。非 JSON 格式日志行 MUST 回退为 raw 行归一化 hash，
解析失败 MUST NOT 崩溃。

#### Scenario: 内嵌变量归一
- **WHEN** 两条 ERROR 的 message 仅内嵌数字/时间戳/UUID 不同
- **THEN** 归一化后指纹相同，复现计数成立

#### Scenario: 异类错误不聚合
- **WHEN** 两条不同错误各出现 1 次（message 骨架不同）
- **THEN** 指纹不同，均不满足复现条件，不触发升级

#### Scenario: 非 JSON 行容错
- **WHEN** 日志含 traceback 原文等非 JSON 行
- **THEN** 检测不崩溃，该行按 raw 归一化回退参与指纹统计

### Requirement: 防抖边界

单次错误 MUST NOT 触发升级；同指纹两次出现间隔 >5 分钟 MUST NOT 触发；
同指纹两次出现中较早者超出 10 分钟窗口 MUST NOT 触发。

#### Scenario: 单条不触发
- **WHEN** 窗口内某指纹仅出现 1 次
- **THEN** 不产生升级 signal

#### Scenario: 间隔超限不触发
- **WHEN** 同指纹两次出现相隔 8 分钟
- **THEN** 不触发升级（视为孤立抖动）

#### Scenario: 窗口过期不触发
- **WHEN** 同指纹第 1 次出现在 11 分钟前、第 2 次在当前
- **THEN** 不触发升级（窗口滑动自然过期，恢复无需显式清零）

### Requirement: 缺 timestamp 行 fail-closed

timestamp 缺失或解析失败的 ERROR 行 MUST 仍计入指纹桶（间隔约束按满足
处理）——方向为宁可多告警不漏告警。

#### Scenario: 缺 timestamp 的重复 ERROR 触发
- **WHEN** 两条同 message ERROR 行均无可用 timestamp
- **THEN** 计为同指纹复现 2 次，触发升级

### Requirement: 冷却节流兼容

升级命中 MUST 继续经过既有 15 分钟同 (spec, signal_type) 冷却节流；
冷却期内再次满足升级条件 MUST 仅记录、不重复唤起 administrator。
第 2 次即升级的新口径 MUST NOT 放大重复告警量。

#### Scenario: 冷却期内不重复唤起
- **WHEN** 升级触发后 15 分钟内同一 signal_type 再次满足升级条件
- **THEN** 仅记录 signal 不重复唤起 administrator（既有 throttle 语义不变）

### Requirement: 阈值不配置化

窗口（10 分钟）、间隔上限（5 分钟）、复现次数（2 次）MUST 保持模块常量，
MUST NOT 新增配置键（规避新增配置项须带 Dashboard UI 的项目约束）。
现阈值常量 `DAEMON_ERROR_THRESHOLD = 3` 的"物理连续"语义随之退役。

#### Scenario: 阈值来源固定
- **WHEN** 需要调整升级灵敏度
- **THEN** 通过修改模块常量实现，config.yaml 与 Dashboard 设置页不出现对应键
