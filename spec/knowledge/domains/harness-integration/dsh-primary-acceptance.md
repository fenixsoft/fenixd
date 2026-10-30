# dsh 主通道验收与切换治理

<!-- knowledge: capability=dsh-primary-acceptance rev=1
     sources=spec/archive/2026-10-30-dsh-primary-acceptance-switch -->

dsh 通道从「可用」到「主 harness」之间的验收与切换治理：可重复的验收证据、可回退的运维路径、以及把「真实环境验收」与「缺省值翻转」两个人工决策从自动链路中隔离出来（ADR-302）。

## 规则

- **一键验收脚本三模式**：`bin/dsh_acceptance.py` 提供 `fixture`（生成玩具项目夹具：临时目录+最小 SPEC 种子+唯一前缀）、`smoke`（假端点全链冒烟：无凭据可重复，覆盖 ≥3 车道）、`accept`（真实全链验收：需凭据，执行前自检凭据/健康检查并输出 dry-run 计划，凭据缺失时列出缺失项与修复指引、不发起任何真实模型调用）。
- **证据以既有机制产物为唯一真相源**：脚本只收集与比对 run jsonl、投影计数、`.fenix-run-result.json`、run_metrics，不另造证据格式；claude 基线对比用同夹具在 claude 通道的最近 run 指标；脚本失败 fail-loud，MUST NOT 产出「假绿」报告；夹具在脚本退出时清理（含 runs 产物），真实项目注册表与 `~/.dsh` 零残留。
- **切换与回切运行手册**：`docs/help/dsh-harness-runbook.md` 覆盖切换到 dsh 完整步骤（Bundle 安装/`agent.harness: dsh`/健康检查确认）、回切 claude 步骤（含在飞 run 按既有排水语义处置）、故障处置（版本漂移/429 同刻叠峰/投影异常/健康检查失败）、真实验收执行指引；每步均有可验证检查点。
- **验收报告契约**：五段证据——各车道终态、投影计数与坏事件统计、usage 降级情况、耗时对比 claude 基线、产物硬门结果——加「默认值是否翻转 claude→dsh」决策申请段；假端点证据与真实证据分栏呈现，翻转决策只认真实环境证据。
- **真实验收人工信号式触发**：真实全链验收的执行请求落位 `.fenix/todo.md` 人工队列（restart_request 信号范式：agent 落位+预演，人工发起）；agent 侧完成预演自检（凭据存在性、健康检查通过、dry-run 计划输出）；agent 无凭据与运维权限，不自动发起任何真实模型调用。
- **缺省值翻转禁入自动化路径**：默认值翻转不出现在任何自动化路径中；用户依验收报告裁决后由一次性微变更执行（config 缺省值翻转 + ADR-271 补记）。验收夹具/脚本自身缺陷就地修复；dsh 通道功能性缺陷根源在 Bundle/adapter 交付物时，修复在验收分支内完成并注明来源能力，避免跨变更打回循环。

## 溯源

- 2026-10-30 dsh-primary-acceptance-switch（spec/archive/2026-10-30-dsh-primary-acceptance-switch） — 新增本能力：三模式验收脚本与证据契约、切换/回切运行手册与报告模板、真实验收落位 todo.md 人工队列、缺省翻转隔离在自动化路径之外
