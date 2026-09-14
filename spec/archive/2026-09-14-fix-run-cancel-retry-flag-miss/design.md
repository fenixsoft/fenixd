# Design: fix-run-cancel-retry-flag-miss

## Context

add-run-cancel 的取消链路：`cancel_run(run_id)` 以 `_normalize_run_id` 剥 `-a\d+$` 得 base 键登记旗标 → 持有线程在 `_run_claude` 轮询环（每轮 `self._cancel_is_requested(base_run_id)`）与 attempt 循环顶（`self._cancel_is_requested(run_id)`）消费。

瞬态重试子循环（runner.py `sub_run_id = f"{attempt_run_id}-r{transient_retries}"`）使实际在飞 run_id 形如 `<base>-a1-r1`：

- 轮询环键 = `_normalize_run_id("<base>-a1-r1")` = 原样（尾部是 `-r1`，`-a\d+$` 不匹配）
- 登记键 = `_normalize_run_id("<base>")` = `<base>`
- 精确集合匹配失配 → 旗标永不消费。事故实证 2026-09-08（verify-draft-fixture 收口，日志「已登记旗标、命中活跃 attempt」但进程持续运行直至人工按轮询环精确键补登记）。

## Goals / Non-Goals

**Goals:**

- 登记键与两类消费点（轮询环、attempt 顶）对任意 `-a<N>`/`-r<N>` 后缀组合收敛到同一 base 键
- 既有语义零回归（无后缀 / 纯 `-a<N>` 输入）
- 单测覆盖事故路径（`-r1` 重试轮）

**Non-Goals:**

- 不改取消的登记入口/API（dashboard 文件信号、admin 审计流不动）
- 不改瞬态重试的 `-r{N}` 命名机制本身
- 不处理跨进程旗标持久化（旗标仍为 daemon 进程内存态，与现状一致）

## Decisions

1. **归一化集中在 `_normalize_run_id`，消费侧统一过它**：正则改为 `(?:-a\d+|-r\d+)+$` 剥离连续多组后缀；`_cancel_is_requested` 内部先对入参归一化再做集合精确匹配。三处调用（cancel_run 登记、轮询环、attempt 顶）无需各自维护键形态，新后缀种类只改一处。
2. **不做前缀匹配替代**：startswith 语义会把 `<base>` 与 `<base>-更长run名` 混淆（spec 名是 run id 的子串形态），精确匹配 + 归一化对齐更窄且可测。
3. **审计信号不动**：cancel_run 现有 `run_spec_part(base_id)` 提取 spec 失败时留空，与本缺陷无关。

## Risks / Trade-offs

- **过度剥离**：spec 名以 `-a<N>`/`-r<N>` 形态结尾（如 `fix-runner-a2`）会被多剥。本项目 spec 名 kebab-case 语义命名，无纯 `字母+数字` 尾段形态；既有代码对 `-a\d+$` 已有同级暴露，风险不新增。缓解：单测锁定 `fix-runner-a2` 类输入的剥离行为符合预期文档化语义。
- **旗标清理幂等**：`_cancel_clear` 以归一化键清理，与登记键同源，无泄漏变化。
