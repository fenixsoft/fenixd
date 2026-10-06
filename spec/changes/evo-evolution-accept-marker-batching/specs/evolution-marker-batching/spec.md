# evolution-marker-batching Specification

## Purpose

自进化接受循环的标记回写从「逐条一提交」改为「批末单次提交」，消除按条目数放大的提交噪声；不引入跨生产者的合并窗口风险。

## Requirements

### Requirement: 接受循环批末合并提交

auto_accept_pending 批处理 MUST 在收集完本批全部标记变更后对本项目执行恰好一次合并提交，提交消息 MUST 附本批条目 id 明细；批内逐条写 MUST NOT 各自触发 git 提交。dashboard 手动单条接受路径 MUST 维持写后即时提交不变。

#### Scenario: 批次恰一枚提交

- **WHEN** auto_accept_pending 一批接受 N（≥2）条条目
- **THEN** .fenix/todo.md 的标记翻转只产生一枚提交且消息含 N 条条目 id 明细

#### Scenario: 手动单条路径不回归

- **WHEN** 通过 dashboard 手动接受单条条目
- **THEN** 维持既有写后即时提交行为