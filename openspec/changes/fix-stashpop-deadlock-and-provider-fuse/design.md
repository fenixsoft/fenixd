## Context

merge-back 死锁已三次引发人工处置（2026-08-25 $23 token-waste 事故；2026-08-26 untracked 变体两次、stash pop 变体一次熔断）。当前框架状态：

- `core/worktree_manager.py::restore_after_merge`（第 440-457 行）：`git stash pop` 失败仅 `logger.warning` + 返回 False，调用方（pm_engine merge-back 流程）忽略返回值，主树留在 UU 半合并状态——此后所有 git 写命令（stash/merge/commit）全部失败，直到人工处置。
- `core/agent_runner.py`：provider 网关 4xx（400/401/404）按普通失败处理，走 `max_retries` 重试；状态机 per-spec 反复 ready→implementing，每次派发都 `ensure_clean_tree` autostash，故障窗口内 stash 累积、冲突概率放大（2026-08-26 20:15~20:33 deepseek-v4-flash 下线实证）。
- 2026-08-26 `fix-worktree-spec-seeding` 仅缓解了 untracked 变体的流程侧（spec 播种+提交），autostash/pop 冲突与 provider 故障窗口均无覆盖。

## Goals / Non-Goals

**Goals:**
- merge-back 恢复流程对 pop 冲突**自行止血**：不瘫痪主树 git 写操作、不阻塞其它 spec 的 merge-back。
- provider 4xx 故障窗口内**不派发不重试**：不烧 token、不积累 stash、不放大冲突。
- 所有被自愈丢弃或拦截的信息**可追溯**（error 字段 / admin 告警 / dashboard），人工可决策（充值 / 换模型 / 修代码）。

**Non-Goals:**
- 不自动解决 pop 的内容冲突本身（stash 版本 vs merge 版本谁对谁错，只能人工判断）——自愈只保证"止血 + 信息保留 + 可找回"。
- 不做 provider 自动切换（多 provider 负载均衡/故障转移）——那是更大特性，超出本次范围。
- 不改动 StateMachine 状态模型与 SPEC 格式。

## Decisions

### D1: 自愈只「丢弃 stash 版本」，保住 merge 结果
pop 冲突时文件含三种内容：merge 结果（HEAD+已合入分支）、stash 的主树改动、冲突标记。选择 `git checkout HEAD -- <UU>` + `git reset`：
- merge 结果 = 已成功合并的实现（最不可丢失，是 flow 的核心产物）；stash 的主树改动 = 派发前的散落改动（可从此前 stash 中找回）。
- 若反过来保留 stash 版本会**覆盖已 merged 的实现**，直接丢失產出，否决。
- 冲突文件可能是 stash 前就有、与 merge 无关的 IDE 残留——在 stash 条目中完整保留，人工可 `git stash show -p` 恢复，信息不丢。

### D2: 冲突清单走既有 error/admin 通道，不引入新持久化
`restore_after_merge` 返回值从 bool 改为 `(ok: bool, conflict_files: list[str])`（或增加 result 对象），pm_engine 在 spec `error` 字段追加 `stash pop conflict: files=[...]`，admin_monitor 已有 distressed 规则（spec error 变化会触发）负责告警。零新增状态文件。

### D3: 熔断状态进程内存 + 二进制常量，不落盘
`agent_runner` 维护 `provider_circuits: dict[name, {code, count, open_since, cooldown_until}]`，窗口与冷却用滑动时间戳。理由：熔断只影响"故障窗口内的派发决策"，daemon 重启后状态清空，最坏后果是重新探测一次（探针成本=一次 4xx），可接受。常量化便于调参，不引入 dashboard 配置 UI（超出范围）。

### D4: 熔断判据只认解析出的 HTTP 状态码
agent_runner 已从 claude CLI 输出解析 `api_error_status`（400/404 由网关经 SDK 包装为 unrecognized_model 等）。熔断计数只对该字段命中的 4xx；5xx/网络错误不计数（属瞬态，走既有 retry）。401 与 400/404 一并计数（余额不足同样要熔断防烧钱）。

### D5: 熔断期 spec 不动状态机
熔断期派发失败**不**调用 state_machine 回退（spec 保持 implementing/ready 原状）、`_retry_count` 不增。冷却结束后由既有轮询/事件机制自然重排。若熔断持续超过 stuck_threshold，admin_monitor 按既有 stuck 规则唤起 admin（人工排查充值/模型）。

## Risks / Trade-offs

- **R1 误伤**：网关短暂 400 波动可能误熔断某 provider 30 分钟，期间该 provider 的 spec 全挂起。权衡：4xx 属明确故障信号（模型下线/余额不足通常持续 >30 分钟），且 30 分钟可调；比现状（反复重试烧钱 + stash 冲突）收益大。
- **R2 探针把 400 当 success**：半开探针请求若网关以 400 应答但 claude CLI 偶发解析不出 code，会误闭合。防护：探针沿用同一 code 解析路径，解析不到 code 视为失败、不进计数。
- **R3 自愈后丢弃内容被误删**：checkout HEAD 覆盖的 stash 改动若未被及时找回可能被人工后续 `git stash drop` 清掉。缓解：error/告警明确提示"stash 保留，用 git stash show 找回"，且框架不自动 drop。
- **R4 多实例 daemon（多项目）共存**：熔断状态是 daemon 进程内内存，多项目各自判定互不影响——符合"每项目独立 daemon"既有架构。