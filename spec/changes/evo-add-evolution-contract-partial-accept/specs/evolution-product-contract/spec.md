# evolution-product-contract Specification

## Purpose

自进化产物校验把「个别条目非法」与「整份产物非法」区分开：单条契约错误只牺牲该条，合法条目照常登记，消除整批陪葬式全量重跑浪费；同时保留全部非法时的 fail-closed 与失败现场留档。

## Requirements

### Requirement: 单条非法跳过、合法条目照常返回

产物契约校验遇到单条目契约错误（如 section 不在三值枚举）MUST 收集该条错误并跳过，合法条目照常通过校验；全部条目非法时 MUST 仍整体拒绝。

#### Scenario: 混合产物部分接受

- **WHEN** 产物含 9 条、其中 1 条 section 为「流程」越界
- **THEN** 校验返回 8 条合法条目与 1 条错误记录，不抛整份拒绝

#### Scenario: 全部非法仍拒绝

- **WHEN** 产物所有条目均契约非法
- **THEN** 整体拒绝、contract 为空，行为与现状一致

### Requirement: 校验拒绝接入部分恢复语义

落库侧对「有合法条目的校验拒绝」MUST 走与「条目不足」一致的 partial 语义：合法条目落库、run 记失败、水位不推进（下检查点幂等补齐）；失败现场产物文件 MUST 留档不被清理。

#### Scenario: 校验拒绝后合法条目落库

- **WHEN** 校验返回部分合法条目
- **THEN** 合法条目写入 items 存储，水位不推进，产物文件留档供归因