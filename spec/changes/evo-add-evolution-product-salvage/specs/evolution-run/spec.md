# evolution-run：产物抢救与失败分级

## ADDED Requirements

### Requirement: run 失败也先抢救产物再清理
run_evolution 在 CLI 非零退出（run_ok=False）时不得先删产物：先尝试读取 out-<run_id>.json；文件缺失时若 <out>.parts/ 下存在分片则按既有合并配方（sorted(glob) 拼接 items）恢复产物后再读；恢复出可解析契约的按成功落地处理并落 INFO 说明 CLI 退出异常；确无产物可救才执行清理，清理范围包含 .parts 残片目录。

#### Scenario: 写完产物但 CLI 非零退出
- WHEN 子代理已写出可解析产物、CLI 以非零码退出
- THEN 框架读出产物按成功落地，产物不被静默删除

#### Scenario: 已写分片未及合并
- WHEN 产物缺失但 .parts 目录有分片
- THEN 框架合并分片恢复产物后读取；合并条目数与待分析条目数不一致时在告警中标注缺失数

#### Scenario: 无产物可救
- WHEN 产物缺失且 .parts 目录为空
- THEN 按失败处理，错误文案为「产物文件未写出」，清理含残片目录

### Requirement: 失败归因分级
read_contract 对「文件不存在」与「JSON 不可解析」给出不同的 ContractError 文案。

#### Scenario: 归因可分辨
- WHEN run 失败且读产物报错
- THEN 错误文案区分产物未写出与 JSON 非法两种，告警与日志可直接判别

### Requirement: 分片增量合并契约
agents/evolution.md 的分片写入契约改为增量合并：每完成一条分片即并入最终产物文件，使任意中断点的最大损失为单条分片；结尾保留全量校验步。

#### Scenario: 中断点损失有界
- WHEN run 中途死亡
- THEN 产物文件已含已完成条目，抢救路径可恢复已完成部分