# Design: fix-provider-transient-backoff

## Context

取证定案（2026-09-07）：43 个 error 终局 run 中 37 个实为 daemon restart 屠杀（与本 SPEC 无关，drain 配置用户决策暂不动），3 个为 CLI 自死于网关错误。真·瞬断死亡链路：

1. claude CLI 某次 API 请求撞网关故障 → 网关回 400 形态（`unrecognized_model`）不在 CLI 重试白名单（官方文档：仅 5xx/429/断连/流停滞重试，默认 10 次指数退避）→ CLI 死亡（exit 1，无 result 事件）。
2. runner `_run_claude` 轮询环得 rc≠0 → 取 stderr 末 5 行拼 error（`runner.py:2427`）→ stderr 里高频存在的 `[claude-code:unrecognized_model]` 诊断噪音行（v2.1.233+ 自定义 BASE_URL 下每请求必写，成功 run 也大量出现）成为错误文本主角 → 死因误标。
3. `_execute_agent_inner` 捕获后 `classify_switch_error`（provider_circuit.py:133-136 文本匹配）→ 该 provider 进 300s switch 冷却 + 链前进 → 网关**全局**瞬断时链上全部 provider 被先后烧尽并冷却，`chain_exhausted`。
4. dispatch 层 `_read_implementer_result` 得 None → 死亡豁免回退预算 → `_retry_count` 清零重入队 → 全新 run_id/全新 worktree 从零跑。

关键事实约束：
- CLI 对 400 形态不重试——runner 层是唯一能补退避的位置。
- `--resume` 依赖 session 数据存在于创建时的 `CLAUDE_CONFIG_DIR`（session.py:24-27）；provider 切换后隔离目录不同，跨 provider resume 必然 `No conversation found`——**同 provider 才可 resume 是硬约束**。
- attempt 间 worktree 复用现仅 implementer/fast-track/repair（runner.py:2017-2033）；fast-track 的 `keep_for_reuse` → `_take_reusable_worktree` 认领通道（worktree_manager.py:901-981）已生产验证。
- 瞬断是分钟级恢复的瞬态（历史死亡 run 的重派 16 分钟后成功）。

## Goals / Non-Goals

**Goals**
- 瞬断时优先「等它恢复」而非「换链烧全链」：同 provider 原地指数退避 + `--resume` 续跑。
- 任何 agent_type 的 attempt 间不丢 worktree 现场；transient 终态失败保留现场供下轮认领。
- dispatch 对 transient 终态排程等待重派，不被死亡豁免+清零计数拖入无刹车重派循环。
- 全局错误指纹熔断：风暴期冻结派发（自省建议「同错误 10 分钟 ≥3 次熔断」）。
- 错误归因可信：降噪诊断噪音行。
- 新配置键与 Settings UI 同步落地。

**Non-Goals**
- 跨 provider 移植 session 后 resume（隔离目录硬约束 + 兼容风险，收益小）。
- drain / shutdown 行为改动（用户决策暂不改）。
- CLI 内部重试参数（`CLAUDE_CODE_MAX_RETRIES` 等 env）调整。
- Administrator run 接入 attempt 级 failover / 原地退避（runner.py:1035 保持现状，仅受全局熔断保护）。

## Decisions

### D1 原地退避放在 attempt 循环内，作为「attempt 内子重试」，不递增 attempt 计数

`_execute_agent_inner` 的异常分类处（runner.py:1890-1915）：`classify_switch_error` 命中时，先查原地重试预算（独立计数器，按 `agents.transient_backoff_schedule` 长度定上限），有预算 → 写 `transient_retry` 事件留痕 → sleep 退避序列下一档 → **重跑同一 attempt**：run_id 加 `r{n}` 后缀（独立 jsonl，session_id 从上一产物提取续 `--resume`），provider 不变、不触发 switch 冷却、不改 chain_cursor。预算耗尽才走现行逻辑（switch 冷却 + 链前进）。

- 为何不在 `_run_claude` 内做进程级重试环：attempt 循环已有 provider 选择/session 提取/frozen 检查的全部上下文，子重试复用该循环最薄；`_run_claude` 内做会把「重试语义」埋进轮询环，与秒挂计数、超时护栏的交互更难推演。
- 为何用独立 run_id 而非同文件续写：jsonl 是 append-only 产物契约，混流破坏 `_extract_session_id` 头尾读取假设与 dashboard 终态判定（末行 type）。
- 替代否决：把退避放 provider_circuit 选择器——它只选不执行，无 sleep 时机。

### D2 瞬断判定与降噪解耦：判定看原始信号，降噪只影响 error 文本

判定信号（任一）：错误文本含 switch 类 pattern（unrecognized_model / 5xx / 连接类，从**全量** stderr_lines 匹配而非末 5 行）；或「exit≠0 + 无 result 事件 + stderr 存在 `[claude-code:...]` 行」（CLI 实验实证：400 fatal / 500 耗尽 / 流断耗尽三种形态均为 exit 1 + 无 result + stderr 仅剩诊断行）。

降噪（D5）后 error 文本不再含 unrecognized_model 字样，因此 `classify_switch_error` 与 dispatch 的 transient 判定**必须依赖原始 stderr_lines / 结构化标记**，不得读降噪后的 error 字符串反推。

### D3 worktree 保留全 agent_type + transient 终态 keep_for_reuse

- attempt 间保留：runner.py:2017-2033 的类型白名单删除（全 agent_type 保留），非 implementer 族复用前仍过 frozen/取消检查。
- transient 终态失败：替代 `cleanup(success=False)`（runner.py:2047），走 `keep_for_reuse`（复用 fast-track 既有登记，worktree_manager 加 agent_type 参数泛化）；非 transient 的终态失败维持现行清理，避免真实缺陷现场被误续用。
- 认领：下轮派发经 `_take_reusable_worktree`（有效性 = `is_available` 三态），长期无人认领由既有 `cleanup_stale_worktrees` 兜底，不新增清理逻辑。

### D4 dispatch 排程等待 + 全局错误指纹熔断

- transient 终态标记：error 消息头部拼 `[provider-transient]`（写侧 runner 异常分类处统一注入）。dispatch `_run_agent_worker` 失败分支（dispatch.py:920-951）识别该标记 → 不走 `_retry_count` 递增/清零路径 → 调 `_schedule_transient_recovery`（仿 dispatch.py:146-189 的 instant_fail_recovery 定时器模式，`agents.transient_redispatch_delay_seconds` 缺省 600s）→ 到期重入 `_on_spec_ready`。
- 全局熔断：provider_circuit 增加全局错误指纹计数（错误文本归一化：剥 model 名/时间戳后指纹），窗口/阈值/冷却 = `agents.transient_break_*` 配置；触发 → 全局派发闸门（`_process_queue` 检查，同 instant_fail_cooled 模式）+ major 告警（带 throttle）。计数与熔断状态保持进程内存（与既有 4xx 熔断/switch 冷却同构，重启清零可接受）。
- 死亡豁免保留：`_exempt_dead_run_budget` 不动——它防的是预算误耗，重派刹车由排程等待 + 熔断承担，二者职责正交。

### D5 降噪：拼装 error 前过滤 stderr 诊断行

runner.py:2427 拼 `error_msg` 前过滤 `^\[claude-code:` 行；过滤后为空 → 回退 `f"Exit code: {returncode}"`；全量 stderr 仍保留原始行（jsonl 的 stderr 事件不动，取证现场完整）。

### D6 配置键（core/config.py + template + SystemPanel 同步）

| 键 | 缺省 | 语义 |
|---|---|---|
| `agents.transient_backoff_schedule` | `"30,60,120"` | 原地退避秒序列，长度=原地重试上限 |
| `agents.transient_redispatch_delay_seconds` | `600` | dispatch 排程等待 |
| `agents.transient_break_threshold` | `3` | 熔断窗口内同指纹次数 |
| `agents.transient_break_window_seconds` | `600` | 熔断窗口 |
| `agents.transient_break_cooldown_seconds` | `600` | 熔断冷却 |

非负整数/逗号序列校验，非法回退缺省（同 `_shutdown_drain_seconds` 的防御式先例）。

## Risks / Trade-offs

- [resume 死 session（No conversation found）秒挂] → 既有清 session 兜底（runner.py:1916-1928）扩展覆盖 `r{n}` 重试路径；连续 2 次 resume 失败放弃 resume 改全新会话。
- [worktree 保留导致磁盘堆积] → stale 清扫既有兜底；transient 保留仅限派发间隔（认领或清扫），不设永久区。
- [原地重试拉长 run 存活时长，与 supervision 矩阵交互] → 子重试发生在 attempt 循环（无 claude 进程在跑），supervision 只盯进程；单 attempt deadline 不受影响；`transient_retry` 事件留痕供排查。
- [瞬断判定误报（把真实缺陷判成瞬断）] → 判定条件收紧为「网关侧错误文本 **或** 诊断行+无 result」双通道；真实缺陷通常带具体错误文本（非诊断行），误报面小；误报代价=多等一轮退避，可控。
- [重派循环与排程等待叠加导致 spec 饥饿] → 排程等待有上限窗口；熔断提供全局兜底；both 均带告警可见性。
- [全局熔断误伤（多 spec 各自真实同型错误）] → 指纹归一化仅剥可变字段，不同 spec 同型瞬断本就该熔断（同源网关故障）；真实缺陷型错误文本各异，指纹不同。

## Migration Plan

纯增量改动，无 schema/数据迁移。上线顺序：先降噪与判定（D2/D5，零行为风险）→ 退避与保留（D1/D3）→ dispatch 闸门与熔断（D4）。回滚 = 配置键置空（`transient_backoff_schedule: ""` 关闭原地退避，阈值置 0 关闭熔断），代码路径保持可跳过。
