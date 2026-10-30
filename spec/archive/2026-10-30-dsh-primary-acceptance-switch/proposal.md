## Why

依赖链前三环（SPEC-1 抽象层 / SPEC-2 Bundle / SPEC-3 DshAdapter）已立项，按母设计 §10 依赖链顺序实现中；本 SPEC 排序其后，**进入实现的前置条件是 SPEC-1/2/3 均已合并 main**（见 design 决策 6 前置门）。终态定位是「dsh 为主 harness」（母设计 §1.1），但翻转缺省前必须有真实全链验收证据与可回退的运维路径。本 SPEC 交付验收夹具/脚本/运行手册/报告模板，并以信号式交付物申请真实全链验收的执行；**默认值是否翻转由用户依据验收报告裁决，不是本 SPEC 的任务**。母设计：`docs/superpowers/specs/2026-10-13-multi-harness-adapter-design.md` §10。

## What Changes

- 新增 `bin/dsh_acceptance.py` 一键验收脚本：玩具项目夹具生成、假端点全链冒烟（无凭据可重复）、真实全链验收模式（需凭据，人工触发）、证据收集（run jsonl/投影可观测性计数/终态/产物硬门/耗时对比）。
- 假端点全链回归从 SPEC-3 的单车道冒烟扩展到多车道（implementer/verifier/监督 judge 至少三车道）。
- 新增 `docs/help/dsh-harness-runbook.md` 运行手册：`agent.harness: dsh` 切换步骤、回切 claude 步骤、故障处置（版本漂移/429/投影异常/健康检查失败）、真实验收执行指引、验收报告模板（含「默认值是否翻转」决策申请段）。
- 信号式人工动作：落位「真实全链验收执行请求」到 `.fenix/todo.md`（人工队列），agent 完成预演与自检；实际真实验收由用户发起。
- **BREAKING：无**（不翻转任何缺省值）。

## Capabilities

### New Capabilities
- `dsh-primary-acceptance`: dsh 通道的多车道全链验收夹具、一键验收脚本、切换/回切运行手册与验收报告契约。

### Modified Capabilities

（无。）

## Impact

- 新增 `bin/dsh_acceptance.py`、`docs/help/dsh-harness-runbook.md`、配套测试；`.fenix/todo.md` 登记（人工队列）。
- 不改 core 缺省值与任何车道行为；验收中发现缺陷的修复回归本 SPEC 范围（实现期 modify 不预声明）。
- 终态产出：验收报告供用户裁决默认值翻转；翻转本身（若批准）是后续一次性微变更，不在本 SPEC。
