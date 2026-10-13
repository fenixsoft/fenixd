## ADDED Requirements

### Requirement: 一键验收脚本

`bin/dsh_acceptance.py` MUST 提供三模式：`fixture`（生成玩具项目夹具：临时目录+最小 SPEC 种子+唯一前缀）、`smoke`（假端点全链冒烟：无凭据可重复，覆盖 ≥3 车道）、`accept`（真实全链验收：需凭据，执行前自检凭据/健康检查并输出 dry-run 计划）。脚本 MUST 收集既有机制产物为证据（run jsonl/投影计数/`.fenix-run-result.json`/run_metrics）并 MUST 失败即 fail-loud，MUST NOT 产出「假绿」报告。夹具 MUST 在脚本退出时清理（含 runs 产物）。

#### Scenario: 假端点模式可重复

- **WHEN** 在无 dsh 凭据的环境连续执行两次 `smoke`
- **THEN** 两次均能完整跑通 ≥3 车道假端点全链并产出证据，真实项目注册表与 `~/.dsh` 零残留

#### Scenario: 真实模式执行前自检

- **WHEN** 凭据缺失时执行 `accept`
- **THEN** 自检失败并列出缺失项与修复指引，不发起任何真实模型调用

### Requirement: 切换与回切运行手册

`docs/help/dsh-harness-runbook.md` MUST 覆盖：切换到 dsh 的完整步骤（Bundle 安装/`agent.harness: dsh`/健康检查确认）、回切 claude 步骤（含在飞 run 处置）、故障处置（版本漂移/429 同刻叠峰/投影异常/健康检查失败）、真实验收执行指引、验收报告模板。报告模板 MUST 含五段证据（各车道终态/投影计数与坏事件统计/usage 降级情况/耗时对比 claude 基线/产物硬门结果）与「默认值是否翻转 claude→dsh」决策申请段。

#### Scenario: 回切路径完整可执行

- **WHEN** 按运行手册回切步骤在 `agent.harness: dsh` 环境操作
- **THEN** 每步均有可验证的检查点，最终恢复 claude 通道派发且在飞 run 按既有排水语义处置

### Requirement: 真实验收信号式交付

真实全链验收的执行请求 MUST 落位 `.fenix/todo.md`（人工队列，参照 restart_request 信号范式：agent 落位+预演，人工发起）；agent 侧 MUST 完成预演自检（凭据存在性、健康检查通过、dry-run 计划输出）。默认值翻转 MUST NOT 出现在任何自动化路径中。

#### Scenario: 请求落位且预演通过

- **WHEN** 本 SPEC 实现完成
- **THEN** `.fenix/todo.md` 含真实验收执行请求（含执行命令与前置条件），脚本自检模式全绿，无任何自动发起的真实模型调用
