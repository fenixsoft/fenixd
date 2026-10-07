# code-fix-lane 变更

## MODIFIED Requirements

### Requirement: 失败批自动重派预算按回归终局形态分档

失败批（现场即弃入档）的自动重派预算必须区分回归终局形态：有真实失败面（mapped，回归 fail_items 非空）的保持既有 FAIL_RETRY_MAX 预算；零失败面（anomaly，parse_error 或 failed 无明细）的预算降为 1，耗尽后走既有触顶「登记待人工排查+跳过条目」路径。

#### Scenario: anomaly 形态失败批不再被整批重派满 3 次

- **When** 一个 code-fix 批以回归 parse_error（junit 缺失/不可解析、fail_items 为空）或 failed 无明细终局、被现场即弃入档
- **Then** 该失败记录标注 reg_form=anomaly，自动重派预算为 1；预算耗尽后按既有机制登记「待人工排查」并跳过条目

#### Scenario: mapped 形态失败批保持既有预算

- **When** 一个批以真实测试失败（回归 fail_items 非空、可定位失败面）终局入档
- **Then** reg_form=mapped，自动重派预算保持 FAIL_RETRY_MAX=3

#### Scenario: 旧失败记录向后兼容

- **When** fix-failed.json 中存在无 reg_form 键的历史失败记录
- **Then** 按 mapped 处理（沿用既有预算），不因缺键报错

#### Scenario: 复燃合档以最近失败形态为准

- **When** 同一条目集合再次失败、并入既有失败记录
- **Then** 沿用既有合档语义，reg_form 与重派计数以最近一次失败为准

#### Scenario: 异常形态降档/停派发一次性告警

- **When** anomaly 形态触发预算降档或停派
- **Then** 经既有 write_regression_failed_alert 通道发出一次告警（登记 branch、reg_form 与被跳过条目），同一失败记录生命周期内只发一次，不新增告警类型