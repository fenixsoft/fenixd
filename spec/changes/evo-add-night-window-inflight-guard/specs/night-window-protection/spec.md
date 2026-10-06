# night-window-protection Specification

## Purpose

夜间断网窗期间，仓内各派发车道不再把 run 送进窗口里烧：code-fix 夜间批对「预计跨窗」的批次顺延投递，admin 处置会话在瞬断冻结/断窗期避让。

## Requirements

### Requirement: 预计跨窗批次顺延

code-fix 夜间批投递守卫 MUST 覆盖「窗前派出、窗中在飞」形态：批次预计结束时刻（派出时刻 + 同链近批实测时长的估计值）与静默窗区间相交时，MUST 把可投递时刻顺延到窗末。

#### Scenario: 窗前派出但预计跨窗

- **WHEN** 当前时刻在静默窗前、近批均时长使预计结束时刻落入 04:15-04:45 窗内
- **THEN** 投递顺延到窗末之后

#### Scenario: 预计不跨窗

- **WHEN** 预计结束时刻早于窗起点
- **THEN** 按原时刻投递，不引入额外延迟

#### Scenario: 窗内派出的既有行为不回归

- **WHEN** 当前时刻已落静默窗内
- **THEN** 维持既有顺延到窗末的行为

### Requirement: admin 派发断窗避让

admin 会话唤起闸门 MUST 在 provider 瞬断冻结态或夜间断窗期跳过唤起，留待下一轮盘点重试；窗外正常信号 MUST 不受影响。

#### Scenario: 冻结期不唤起

- **WHEN** provider 处于瞬断冻结态且到达 admin 唤起时机
- **THEN** 本轮跳过唤起、记录跳过原因，下轮重新评估

#### Scenario: 窗外正常唤起

- **WHEN** 非冻结态且不在静默窗内
- **THEN** 唤起行为与现状一致