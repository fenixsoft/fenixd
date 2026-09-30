# stale-code-alert-window-dedup 规格

## ADDED Requirements

### Requirement: 跨生命周期窗口去重

stale_code 升级告警写入前，系统 SHALL 查询持久化告警存储中 60 分钟窗口内是否已有同信号记录，命中则跳过写入并降级为日志，使同一陈旧信号跨 daemon 重启不再重复成条。

### Requirement: 去重状态持久复用

去重判定 SHALL 直接复用 admin_alerts.json 持久化存储（latest_signal 窗口查询），SHALL NOT 新增状态文件；daemon 重启后窗口语义自然延续。

### Requirement: 超窗新周期照常成条

窗口去重 SHALL NOT 吞掉新周期首报：距上次 stale_code 告警超过窗口（60 分钟）后再次进入陈旧态时 SHALL 照常写入告警。

#### Scenario: 窗口内重启不重复成条

- WHEN 告警后 60 分钟内 daemon 因自愈重启、新进程再次检测到陈旧
- THEN 跳过写入仅记日志，admin_alerts.json 不新增同文条目

#### Scenario: 超窗新周期照常成条

- WHEN 距上次 stale_code 告警超过 60 分钟后再次进入陈旧态
- THEN 照常写入告警

#### Scenario: 首报不受影响

- WHEN 存储中无任何 stale_code 记录时首次检测到陈旧
- THEN 照常写入告警（既有首报断言保持通过）
