# Design: 修复 dashboard 耗时列恒空与验证失败未被发现

## Context

`improve-dashboard-sections` 的 `spec-table-improvements` 要求表头排序与「耗时」列。调查确认两项在生产均未生效：

1. **duration 恒 0（代码缺陷）**：`run_id` 实际格式为 `<prefix>-<spec>-<unix_ts>-a<attempt>`（`agent_runner.py` `_execute_agent` 每次 attempt 生成 `f"{run_id}-a{attempt}"`）。`core/dashboard/data.py` `get_runs()` 用正则 `r"-(\d{9,10})$"`（要求纯数字结尾）提取开始时间戳 → 不匹配 `-a{n}` 结尾 → `start_ts` 退化为文件 mtime → `duration_seconds = max(0, mtime - mtime) = 0`。实测 20 个 run 全部为 0。
2. **生产实例跑旧代码（运维缺陷）**：8787 端口被 13:26 启动的旧实例占用；后续 4 个新实例 bind 失败后进程不退出僵挂（其一只会 fallback 到 8799），生产视图停留在旧代码。
3. **验证放行无闸门（流程缺陷）**：`improve-dashboard-sections` 验证进度 `{"total":34,"done":0}` 即被放行至 pushed；`fix-improve-dashboard-sections` 同样 0/32。验证器所见「—」（0 时长聚合）与合法占位「无运行记录」无法区分。

现状要点：
- `pm_engine.py` `_on_spec_verified()`（verified→done）已有 `add-task-progress-sync` 建立的「任务完成一致性门禁」先例（`_check_task_completion_gate`，拦截时写 error 字段保留 verified），验证闸门沿同一模式扩展。
- `improve-agent-config-and-verify-resume`（进行中）提供 verify-progress 断点续跑（done 单调递增至 total），保证「跑不完」从机制上可从断点续到完；本变更补的是「跑不完不放行」。
- 前端排序功能（新代码）已实测可用，不属本次修复对象——仅通过部署侧修复让生产实例生效。

## Goals / Non-Goals

**Goals:**
- `get_runs`/`get_spec_timeline` 正确解析 `-a{n}` 后缀 run_id，`duration_seconds`/`total_duration` 反映真实时长。
- dashboard `--serve` 端口冲突时自动接管旧 dashboard 实例，或明确报错退出；杜绝僵尸实例与旧代码长期驻留生产端口。
- SPEC 验证未全量完成（done < total）时阻止 verified→done 推进。
- 验证器对「有运行记录但耗时为空」判定缺陷。

**Non-Goals:**
- 不改 `agent_runner.py` 的 run_id 生成格式（`-a{n}` 是重试/resume 语义的一部分，改动会破坏现有 20 个 run 文件与续跑机制）。
- 不改前端排序逻辑（实测可用）与耗时列渲染逻辑（数据结构不变）。
- 不做「验证完成度 UI 展示」增强（`dashboard/watcher.py` 已消费 verify-progress，本次不动 UI）。
- 不改父 SPEC `improve-dashboard-sections` 的 spec 文本（本次以独立 fix capability 落地）。

## Decisions

### D1. run_id 解析两级 fallback（`data.py` `get_runs`）

- start_ts：优先 `re.search(r"-(\d{9,10})-a\d+$", run_id)`，回退 `re.search(r"-(\d{9,10})$", run_id)`，再无则用 mtime（现状兜底）。
- spec_part：先 `re.sub(r"-a\d+$", "", spec_part)` 去除 attempt 段，再按现逻辑剥 `<ts>` 段；`impl-` 等前缀剥离逻辑不变。
- 职责集中在 `get_runs()` 一处（`get_spec_timeline` 复用其输出，无独立正则）。
- **备选**：修改 `agent_runner` run_id → 否决：破坏 resume/产物对应关系，且历史 run 文件不可迁移。
- 风险 → 缓解：时间戳段取倒数第二段，已通过 `-(\d{9,10})-a\d+$` 精确锚定，不会与 spec 名中的数字串误配（spec 名后无 `-a{n}` 结构）。

### D2. dashboard 端口占用接管语义（`bin/fenix_dashboard.py`/`server.py`）

- `serve()` bind 抛 `OSError`（EADDRINUSE）时：遍历 `/proc/*/cmdline`，匹配「cmdline 含 `fenix_dashboard.py` 且含 `--serve`」（对应待用端口的解析链）→ 对其 `terminate()`（SIGTERM），等其退出（≤3s），重新 bind 一次；仍失败或占用者为非 dashboard 进程 → stderr 打印占用信息并以非 0 退出。
- 不引入 psutil 等新依赖（`/proc` 遍历在 Linux 足够；dashboard 本就在 Linux 场景运行）。
- **备选 A**：仅报错退出 → 生产 8787 仍被旧实例占死，不解决问题。
- **备选 B**：端口 +1 fallback（现状）→ 多端口碎片化、用户访问旧端口，否决。
- 风险 → 缓解：误杀同参数的其他 dashboard 实例（如多项目各自起 dashboard）→ 终止条件限定为「监听同一目标端口」的实例（检查其 `/proc/<pid>/net/tcp` 或直接依赖 bind 失败即占用者必然持有该端口的事实，用 `ss`/`/proc` 定位 PID 后校验其 cmdline 再 kill）。

### D3. 验证完成度闸门（`pm_engine.py` `_on_spec_verified`）

- 新增 `_check_verification_gate(spec_name)`，与 `_check_task_completion_gate` 并列：读 `.fenix/verify-progress/<spec>.json`；文件存在且可解析且 `done < total`（或字段缺失/解析失败）→ 拦截 verified→done，将原因（`done/total` + `current`）写入 spec 的 `error` 字段并保留 verified；文件不存在（无验证流程）→ 不拦截（维持原路径）。
- 落点选择 `_on_spec_verified` 而非 state_machine 的 `transition()`：过渡层无 spec 数据源语义（哪些 spec 需要验证、进度文件归属），且已有同构门禁作为先例。
- 与 checkpoint-resume（进行中 spec）的组合：resume 让 done 可最终到达 total；闸门在到达前不放行；两者同时合入后验证流程闭环。
- **备选**：在 `transition("done")` 统一拦截 → 影响所有 spec 类型（含无验证需求路径），误伤面大，否决。
- 风险 → 缓解：`bug-found` 回退流等借用 verified 语义的路径 → 闸门仅拦截「存在进度文件且未完成」，其余放行，不影响回退。

### D4. 耗时真实性断言（verifier 提示词规则）

- 在 `agents/verifier.md`（或 verify_engine 构造 verifier 提示词的注入点）增加规则：验证「耗时」列时，若 SPEC 在 `.fenix/runs/` 有运行记录而 `total_duration` 为 0 或显示「—」，判定为缺陷并记录 run 数。
- 与 D1 配合：D1 修复后该断言天然通过；断言的价值是防止同类回归（run_id 格式再变时立即暴露）。
- **备选**：在 `verify_engine/assertions.py` 增加结构化断言 → 与现有 agent 驱动的 34 场景框架（planner 生成场景、agent 自由测试）不匹配，且无法覆盖「含运行记录的非指定随机 SPEC」，否决。

## Risks / Trade-offs

- **[误杀同参数 dashboard]** → D2 校验占用 PID 的 cmdline 与目标端口后再 terminate；SIGTERM 优雅退出（dashboard 无状态，重启无损）。
- **[闸门误拦合法路径]**（如手动/旧 spec 无进度文件语义）→ 仅「进度文件存在且未完成」拦截；无文件放行，兼容存量 spec（如 20 个已 pushed 的旧 spec 不受影响）。
- **[修复后旧 run 数据不可回溯]**（历史 run 已生成 mtime≈start 的文件，`-a{n}` 段仍在文件名中可解析，无数据损失）→ 修复即时生效，无需数据迁移。
- **[验证放行依赖进度文件写入正确]**（若 verifier 不写进度文件则闸门形同虚设）→ checkpoint-resume 已保证写入链路（`agent_runner.py:569`）；D3 将「有 verifier run 记录但进度文件缺失」在 spec 中暂记 warning。

## Migration Plan

1. D1/D2/D4 是纯增量代码修复，无 schema/数据变更，可随 implementer 分支直接合入。
2. D3 放行闸门合入后，对**存量已验证 spec**（done/pushed 已达成）无影响（无待办验证）；对**进行中 spec**（improve-agent-config-and-verify-resume、fix-graceful-shutdown-agents 等）需待其验证 done==total 方可 done——与 checkpoint-resume 合入顺序无硬依赖，但建议同批验证。
3. 回滚：撤掉对应 commit 即可；闸门拦截仅写 error 字段，不破坏状态数据结构。

## Open Questions

- 无进度文件但有 verifier run 记录的 SPEC（验证启动过但进度文件缺失/损坏）：当前定为「拦截并写 warning」，是否要在实现时进一步区分「验证被中止」与「验证从未开始」？
- dashboard 接管是否允许跨端口配置（如旧实例监听 8787、新实例 8788，是否杀旧）——当前仅限同端口，避免多项目共机场景误杀。