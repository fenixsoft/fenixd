# Proposal: add-turn-limit-anchor-c

## Why

2026-09-10 fenix-server 项目同日三起 implementer `Max turns (400) reached` 强杀（add-ssh-foundation / add-web-ui / add-builtin-tasks-e2e），暴露 turn-limit 死法在框架侧的「三不管」缺口：

1. **未提交现场不保全**：轮询环 `proc.kill()` 后（可证明 agent 不再写盘的时刻）不走任何 WIP 提交锚点——add-builtin-tasks-e2e a1 的 84 分钟工作（E2E 验证型任务，38 次 sleep 共 22 分钟纯等待）全部滞留 worktree 未提交区，仅靠后续 a2 resume 恰好接住才未丢失；若 daemon 在 attempt 间隙崩溃重启（降级重建路径），该现场即毁。
2. **健康推进被无差别腰斩**：add-ssh-foundation a1 以标准 TDD 节奏正常推进（12 提交、tasks.md 勾选至第 378/400 轮、每任务稳定出提交），第 12 个提交与 SIGKILL 同秒落盘；超时路径已有活性感知续期先例（improve-run-lifecycle-governance D3 封闭决策矩阵 extend/kill），turn-limit 路径却无差别 kill。
3. **成本观测黑洞**：turn-limit 死法经 `_extract_usage_info(None)` 按「tokens counted as 0」记账，而对照 a2 实测成本（ssh=$4.80/25 轮、builtin=$18.52/139 轮）证明 400 轮的 a1 真实消耗显著——违反 add-cost-observability「金额展示不伪造」的设计前提（其「异常早夭消耗小」假设已被本轮三例证伪），污染成本审计与预算分析。

## What Changes

- **锚点 C（turn-limit 收口 WIP 提交）**：runner 轮询环判定 turn-limit、子进程终止确认后，对当前 attempt 的 worktree 调用既有 `commit_wip_checkpoint(wt, spec, "turn-limit")` 保全未提交现场——复用 wip_checkpoint 既有 helper/塌缩/resume 通道，新增锚点常量 `ANCHOR_TURN_LIMIT`。
- **活性感知续期**：轮询环 turn-limit 判定点改为封闭决策矩阵——临近/到达轮次上限时，若 run 表现出真实推进活性（近期有新分支提交 / 新 tool_result 流量），按封顶次数 extend（`turn_extension` 记录留痕），无活性才 kill。机制先例为超时路径 `_supervision_deadline_action`。
- **token 观测口径修正**：turn-limit/timeout 强杀路径的日志与记账语义改为「消耗不可观测（unobserved，非零）」，DEBUG 留痕不再写「counted as 0」；STATE 累计侧保持不伪造原则（不凭空补数），但区分「观测不到」与「确认为零」两种语义。

## Capabilities

### New Capabilities

- `turn-limit-lifecycle`: implementer 等 agent run 触及轮次上限时的收口行为——WIP 现场保全（锚点 C）、活性感知续期（封闭决策矩阵）、观测口径（unobserved ≠ zero）。

### Modified Capabilities

<!-- 无：wip_checkpoint 的锚点 A/B 语义不变，锚点 C 是新增第三锚点；D3 超时矩阵不改，turn-limit 新增自己的判定分支 -->

## Impact

- `core/agent_runner/runner.py`：轮询环 turn-limit 判定分支（现 runner.py:2852-2854 kill 直通）、收口分支（现 runner.py:2926-2931 raise 直通）、attempt 循环错误记账处的日志文案。
- `core/wip_checkpoint.py`：新增 `ANCHOR_TURN_LIMIT` 常量（helper 函数本体不变）。
- `core/agent_runner/session.py`：`_extract_usage_info` 语义扩展或调用侧分支——无 result 时返回/记录「unobserved」而非全零。
- 不改：`agents.max_turns` 配置默认值、wip_checkpoint 锚点 A/B、D3 超时矩阵、attempt 重试预算、prompt 模板（agent 轮次感知经评估无增量收益，不做）。
- 关联事故：fenix-server 09-10 三起（impl-add-ssh-foundation-1789030937-a1 / impl-add-web-ui-1789042616-a1 / impl-add-builtin-tasks-e2e-1789058381-a1）。
