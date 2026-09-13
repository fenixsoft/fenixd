# 验证契约自主起草（verify-contract-autodraft）

## ADDED Requirements

### Requirement: 契约缺失路由信号化
当最终用户验证因「验证契约缺失或无效」而无法获得被测实例时（含：`.fenix/verify.yaml` 不存在、config `commands.start` 为已知占位符、契约 YAML 解析失败被按无契约回退），框架 MUST 产生结构化信号 `verify_contract_missing` 并派发 Administrator 起草契约，MUST NOT 将该情形作为打回 plan 的反馈文本（plan 无法修复项目基建缺口）。

#### Scenario: 契约不存在时产生 admin 信号
- **WHEN** 项目场景集含 web/api 场景、`.fenix/verify.yaml` 不存在且 `commands.start` 为占位符 echo
- **THEN** 框架产生 `verify_contract_missing` 信号（携带 spec 名、项目根、场景 kind 集）并派发 Administrator，该 spec 不因该错误被写入「退回 plan 修复」反馈

#### Scenario: 契约解析失败同样路由 admin
- **WHEN** `.fenix/verify.yaml` 存在但 YAML 解析失败（按无契约回退）
- **THEN** 框架产生 `verify_contract_missing` 信号（标注 `parse_error`），派发 Administrator 修正而非打回 plan

#### Scenario: 确定性死局不等失败计数与升级冷却
- **WHEN** 验证首次撞上「无 serve 配置」判定
- **THEN** 信号立即派发（不走 4 次失败计数或 60 分钟升级冷却等待）；同一 spec 的重复信号仍受信号节流约束（冷却窗口内不重复唤起 Administrator）

### Requirement: prepare 失败保持打回 plan
验证契约存在且 `prepare` 构建步骤失败时（构建被实现破坏），框架 MUST 维持既有行为：作为验证环境错误打回 plan 侧修复，MUST NOT 派发 `verify_contract_missing` 信号。

#### Scenario: 构建失败不派 admin 起草
- **WHEN** 契约 `prepare: npm run build` 因实现引入的编译错误而退出码非 0
- **THEN** 返回 prepare 失败错误（打回 plan 路径），不产生 `verify_contract_missing` 信号

### Requirement: admin 起草自证门
Administrator 起草 `.fenix/verify.yaml` 时 MUST 在落盘前完成三段自证：`prepare` 步骤全部执行成功、`serve` 实例启动并可探活、`ready` 就绪探针通过（含鉴别力自检）。自证 MUST 通过框架提供的显式校验入口执行（`core/verify_contract.py` 校验函数或 bin CLI），校验未全通 MUST NOT 落盘生效。

#### Scenario: 三段自证通过后落盘
- **WHEN** Administrator 为夹具项目起草契约并运行校验入口，prepare/serve/ready 三段全部通过
- **THEN** `.fenix/verify.yaml` 落盘，校验入口退出码 0 并输出三段结果

#### Scenario: 自证未通过不落盘
- **WHEN** 起草的契约 prepare 步骤失败或 ready 探针超时
- **THEN** 校验入口以非 0 退出并输出失败段与错误详情，`.fenix/verify.yaml` 不作为有效契约生效（不落盘或落盘为非契约路径）

### Requirement: 起草收尾与重验证
契约落盘后 Administrator MUST：将契约文件 git 提交（验证契约为随仓库提交的声明）；把被卡 spec 的状态复位为 ready 触发重验证。起草与自证在 2 轮内仍无法通过时，MUST 置 `escalate=true` 并在处置记录中附当前草稿内容与失败证据。

#### Scenario: 起草成功后 spec 复位重验证
- **WHEN** Administrator 完成契约落盘、git 提交
- **THEN** 被卡 spec 状态复位为 ready，daemon 重新派发实现/验证链路，验证使用新契约获得被测实例

#### Scenario: 两轮修不通升级人类
- **WHEN** Administrator 两轮起草/修正均未通过三段自证
- **THEN** 处置记录 `result=escalated`，附最新契约草稿全文与逐段失败证据，不落盘生效半成品契约

### Requirement: 契约权限边界
Administrator 对已存在的 `.fenix/verify.yaml`：可解析且 serve 段合法的有效契约 MUST 一律不碰（人类手写/手改始终权威）；解析失败或明显失效（如 prepare 指向已不存在的 script、serve root 目录不存在）MAY 修正，且修正动作 MUST 在处置记录 `actions_taken` 留痕（含 diff 摘要）。

#### Scenario: 有效契约不被覆盖
- **WHEN** 项目存在可解析且 serve 段合法的 `.fenix/verify.yaml`
- **THEN** Administrator 不修改该文件（即使命令触发起草任务，也以「契约有效、无需起草」结案）

#### Scenario: 修正失效契约留痕
- **WHEN** 契约 `prepare` 指向 package.json 中已不存在的 script（明显失效）
- **THEN** Administrator 修正该行，处置记录 `actions_taken` 包含修改前后内容的 diff 摘要

### Requirement: 契约校验入口
`core/verify_contract.py` MUST 提供契约校验函数，输入项目根（或契约路径），输出逐段结果（prepare/serve/ready 各自通过与否与错误详情）；`bin/` 提供对应 CLI 以项目根为参数运行同一校验。就绪探针鉴别力自检（SPA fallback 形态判定）纳入校验通过条件。

#### Scenario: CLI 校验健康契约
- **WHEN** 对包含有效三段契约的夹具项目运行校验 CLI
- **THEN** 退出码 0，输出 prepare/serve/ready 三段通过结果

#### Scenario: CLI 校验坏契约
- **WHEN** 对 serve root 指向不存在目录的契约运行校验 CLI
- **THEN** 退出码非 0，输出 serve 段失败详情
