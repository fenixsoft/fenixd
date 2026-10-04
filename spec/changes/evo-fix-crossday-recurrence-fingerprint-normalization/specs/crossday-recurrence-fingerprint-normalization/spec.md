# crossday-recurrence-fingerprint-normalization 规格

## ADDED Requirements

### Requirement: 同形错误行的指纹一致性
错误指纹归一化 SHALL 把「数字.数字+单位字母」形态（如 23.4s / 5.3s 的延迟数值）归一为占位符，使仅延迟数值不同的同形错误行产出相同指纹；api_timeout 类失败终态 SHALL 可基于归一化后指纹做跨日同刻比对。

#### Scenario: 两夜同刻死亡判为同签名
- **WHEN** 两夜 04:31 前后的死亡 ERROR 行除延迟数值（如 23.4s 与 5.3s）外文本同形
- **THEN** 二者归一化后指纹相等，进入跨日差 24h±5 分钟的连发判定

#### Scenario: 数值外的真实差异仍区分
- **WHEN** 两条错误行的非延迟数值部分不同（不同根因）
- **THEN** 归一化后指纹不同，不误聚

### Requirement: 跨日指纹记忆跨重启存活
_detect_crossday_recurrence 的「签名→上次失败时刻」记忆 SHALL 持久化到磁盘状态文件，daemon 重启后 SHALL 可加载续用；无持久化记忆时，回退对账 SHALL 能检索到至少 24 小时前的同签名日志（SHALL NOT 受 256KB 尾读窗限制）。

#### Scenario: 重启后同刻连发仍可检出
- **WHEN** daemon 在两次夜间窗口之间重启，次夜出现同签名死亡
- **THEN** 聚合观测仍比对到前夜记忆（持久化加载或全窗回退检索）并触发跨日升级告警

#### Scenario: 记忆损坏时降级安全
- **WHEN** 持久化记忆文件缺失或不可解析
- **THEN** 回退到日志检索路径，观测功能不中断、不抛错影响主扫描

### Requirement: 观测保持只读
本能力 SHALL 仅产出聚合告警与留痕，SHALL NOT 触发重派、熔断、冷却等任何自动干预，SHALL NOT 改变 daemon_errors 既有维度（10 分钟窗计数）的判定行为。

#### Scenario: 聚合告警不驱动动作
- **WHEN** 跨日同刻连发告警触发
- **THEN** 仅升级 escalation 供人工/复核消费，派发系统行为与不触发时完全一致