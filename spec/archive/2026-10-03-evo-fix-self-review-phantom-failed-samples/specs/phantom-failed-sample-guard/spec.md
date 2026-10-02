## ADDED Requirements

### Requirement: 失败信号证据排除终态邻近 assistant 事件行

自我评审分类器（core/self_review.py _classify_run）在 marker 未命中后扫描信号证据时，SHALL 排除 run 产物终态邻近窗口（尾三行 [assistant, run_metrics, result] 结构）中的 assistant 事件行——该行承载与 result 终态摘要同源的收工叙事回声（实测不逐字等于 result 全文，排除按行结构识别、不做逐字副本匹配），使仅存在于 result 正文及其回声行中的业务失败词不构成 failed 证据。

#### Scenario: 信号词仅出现在 result 正文及其回声行

- **WHEN** 某成功 run 的 result 正文或其 assistant 回声行提及业务失败词（如收工摘要描述回归测试中的「预算耗尽」场景），且声明区（前 100 字符）无失败词
- **THEN** 分类为 succeeded，不入失败样本

#### Scenario: 终态之外的独立失败证据仍可检出

- **WHEN** 失败信号词出现在 run 过程的独立事件行中（非 result 文本及其副本行）
- **THEN** 信号证据路径仍可命中并计 failed

### Requirement: 信号路径失败样本与 daemon 终态双源交叉守卫

聚合侧 SHALL 仅在样本因信号路径命中分类为 failed（detail 前缀 signal=）时比对 daemon 侧 run_metrics 的 terminal 字段（数据源为 .fenix/logs/fenixd.log 的 run_metrics 日志行，读侧复用现成 metric 索引并含轮转回退）：terminal 为 success 而分类为 failed 时，SHALL 不计入失败统计与失败样本，改写一条 signal_type=self_review_phantom_failure、severity=warning 的告警且不自动 mark_handled；marker= 命中（假成功抓取：daemon 对正常 result 收尾本就记 terminal=success，与 result 文本内容无关）MUST NOT 纳入守卫；metric 索引中查不到该 run 终态时 SHALL 维持现状计入，不因缺数据改判。

#### Scenario: 信号路径分类 failed 但 daemon 终态 success

- **WHEN** 某样本因信号路径命中分类 failed（detail 前缀 signal=）而其 run_metrics terminal 为 success
- **THEN** 该样本不计入失败数与失败样本列表
- **AND** admin_alerts 出现 self_review_phantom_failure 告警且保持未处理，供人工知悉分类器仍有漏网

#### Scenario: marker 命中不受交叉守卫影响

- **WHEN** 某样本因 result 声明区命中失败标记分类 failed（detail 前缀 marker=）而其 run_metrics terminal 为 success（假成功抓取的常态：进程正常收尾但业务声明失败）
- **THEN** 仍计入失败数与失败样本列表（D1 假成功抓取语义保持）
- **AND** 不产生 self_review_phantom_failure 告警

#### Scenario: 索引缺失不改判

- **WHEN** metric 索引中查不到该 run 的终态记录（如日志已轮转出窗）
- **THEN** 维持现状计入失败，行为与现状一致