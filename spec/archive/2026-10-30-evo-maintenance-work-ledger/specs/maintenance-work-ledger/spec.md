# specs/maintenance-work-ledger/spec.md

## 能力

维护型/延伸型工作的轻量登记台账：一行登记使框架外工作从产生即有主、告警可路由、记账可见。

## 需求

### R1 台账读写

- 项目级台账文件 .fenix/maintenance_log.jsonl，逐行 JSON；
- 登记字段：ts、scope（范围）、actor（执行者）、evidence（证据位置）、note、可选 run_id；
- 追加接口在文件不存在时创建；读取接口对坏行容错跳过。

### R2 登记型 run 前缀

- RUN_ID_AGENT_PREFIXES 前缀表新增 maintenance- 前缀及类型映射；
- admin_monitor 的 run 前缀消费表同步，使 maintenance- run 在归因/盘点视图识别为登记型。

### R3 关联

- 台账条目的 run_id 字段与 maintenance- run 关联，供告警归因与复盘引用。

## 验收

- R1 的追加/读取/空文件创建/坏行容错有测试钉住。
- R2 两处前缀表同步有测试钉住。
- R3 关联字段读写有测试钉住。