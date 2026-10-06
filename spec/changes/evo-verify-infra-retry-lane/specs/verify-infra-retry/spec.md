# verify-infra-retry Specification

## Purpose

验证准备阶段的宿主/环境失败获得廉价重试车道：预检短路不再烧全价升级，改走限次 infra-retry；宿主预检以项目 prepare 步骤表达并有模板样板可抄。

## Requirements

### Requirement: 预检失败 infra-retry 车道

verify prepare 失败或可达性 fail-fast（0 场景执行即短路）MUST 优先归类为 infra-retry：不计 env 冻结轮（_env_block_rounds 不递增）、MUST NOT 触发 admin 呼叫，按 infra-retry 专用台账（连续重派计数，缺省 2 次，与既有 _verify_infra_rounds 观测账分离）直接重派验证；重派仍失败达阈值后 MUST 恢复既有全价升级路径。

#### Scenario: 预检失败廉价重试

- **WHEN** prepare 步骤失败或可达性检查失败且本轮 infra 重派次数未达阈值
- **THEN** 记 infra 失败台账并直接重派验证，不递增 env 冻结轮、不产生 admin 升级告警

#### Scenario: 连败达阈值恢复全价升级

- **WHEN** 连续 infra-retry 重派达到阈值仍失败
- **THEN** 恢复既有 _escalate_env_blocked 全价路径（计冻结轮、按阈值升级）

#### Scenario: env 阻塞语义不回归

- **WHEN** 场景执行后的 env 阻塞分类（非预检短路）命中
- **THEN** 既有 blocked→升级路径不变，infra-retry 轮不污染 env 冻结计数与豁免语义

### Requirement: 宿主预检模板样板

verify 契约模板的 prepare 段 MUST 提供宿主预检示例步骤（注释形态）：无主 qemu/emulator 进程扫描与清理（只清理 ppid=1 且可归属到已完成 run 的进程、记录被杀 pid）、残留 AVD 锁清理、KVM/内存水位检查，以及场景特异冒烟探针（如 OpenCV init）的添加指引；并说明预检失败将走 infra-retry 廉价重试。

#### Scenario: 项目按样板启用预检

- **WHEN** 项目从模板生成/更新 verify.yaml 并启用预检步骤
- **THEN** 预检在场景执行前运行，失败触发 infra-retry 车道而非整轮验证失败升级