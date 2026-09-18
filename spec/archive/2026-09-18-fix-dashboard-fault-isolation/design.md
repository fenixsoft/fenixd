## Context

多项目 Dashboard（`core/dashboard/`）以「自动扫描 `~` 一级子目录」为主发现被监控项目（`registry.py`），并在 `overview()`（`data.py`）与 `_api_projects()`（`server.py`）中逐项目聚合摘要供概览页展示。

2026-09-12 实测故障链：

1. `/data`（`/dev/sda1`）硬件故障（`DID_BAD_TARGET`、superblock 写失败），`/root/Qwen3.5-0.8B-Instruct`（指向前者的符号链接）目标目录数据块不可读（`ls` 直接 `EIO`）。
2. 默认扫描根 `~` 遍历一级子目录，`registry.py:133` 对每个子目录执行 `(child / ".fenix" / "STATE.md").is_file()`。
3. `pathlib.Path.is_file()` 只吞 `_IGNORED_ERROS = (ENOENT, ENOTDIR, EBADF, ELOOP)`（Python 3.10.12 实测），**`EIO` 直接上抛**。
4. `discover()` 子目录循环无异常隔离 → 整个发现失败。
5. `DashboardHTTPServer.projects()` 让异常冒泡且不推进 `_cache_ts` → 每个请求重试重炸。
6. `_api_overview()` → `server.py:305` 兜底 → `500 Internal Server Error`。
7. 前端概览页 `data` 为 null → 只渲染一条错误 Alert，整页无内容。

两条逃生通道同时失效：`ignored` 过滤位于探测**之后**（`registry.py:133` 探测 → `137` 过滤），用户无法把坏目录忽略掉；发现缓存异常时时间戳不推进，任何重试都必然再失败。

约束：扫描根保持 `~`（不改默认语义）；不引入「跳过符号链接」策略；本次不做 per-project 自动摘除/熔断。用户已决策：**发现层跳过不可读目录时 UI 静默**，仅落 WARNING 日志。

## Goals / Non-Goals

**Goals:**

- 单个（乃至多个）扫描子目录的文件系统故障 MUST NOT 中断项目发现，更 MUST NOT 使 `/api/projects` / `/api/overview` 返回 500。
- 单个项目在聚合阶段失败 MUST 降级为该项目卡片的 `error` 字段，其余项目与 `totals` 不受影响。
- 「加入忽略列表」MUST 成为面对不可读目录时可用的逃生通道。
- 概览页在请求失败时 MUST 有可操作的降级视图，且刷新失败 MUST NOT 清空已成功展示的数据。

**Non-Goals:**

- 不修 `/data` 硬件故障（运维事项）。
- 不改变默认扫描根为 `~` 的既有语义。
- 不引入 per-project 的 I/O 故障自动摘除 / 熔断机制。
- 不把跳过的目录上报为 UI 可见条目（用户已决策静默，仅日志）。

## Decisions

### D1：探测显式 `try/except OSError`，而非改用 `os.path.isfile`

`os.path.isfile()` 内部 `try: os.stat(...) except (OSError, ValueError): return False` —— 会**广泛**吞掉包括 `EIO` 在内的所有 `OSError`，是最省事的修法。但本项目需要区分两种语义：

- `ENOENT`（目录没有 `.fenix/STATE.md`）是**正常业务分支**，必须静默跳过、不得写告警日志；
- `EIO`（目录不可读）是**故障**，必须写 WARNING 日志（`project-discovery` 的可观测性要求）。

`is_file()` 的黑盒吞异常无法区分二者。因此保留 `pathlib` 调用但用显式 `try/except OSError` 包裹，在 `except` 分支内检查 `errno` 决定是否告警。

**Alternatives considered**：改用 `os.path.isfile()`（一行改动）——被否，无法满足「跳过时必须可观测」的契约；把 `errno` 判断塞进一个通用 helper 供 `is_dir()`/`is_file()` 复用——采纳，避免两处重复。

### D2：`ignored` 过滤前移到探测之前，匹配基于规范化路径

循环顺序改为：`for child in children:` → 计算规范化 key → `if key in ignored: continue` → `is_dir()` 探测 → `STATE.md` 探测。规范化沿用现有 `_norm()`（`Path.expanduser().resolve()`，非 strict；`os.path.realpath(strict=False)` 吞 `OSError`，对不可读**目标**目录仍可返回，因为它只需 `lstat` 各级组件而非读取目录数据块）。

**备选方案**：在 `except` 分支里再查一次 `ignored`（保留原顺序）。被否——两处判断易漂移；且「过滤先于一切可能抛异常的操作」是更清晰、可断言（mock 断言探测零调用）的契约。

### D3：发现层容错只做「跳过 + 日志」，不构造 degraded 条目

用户明确选择 UI 静默。`discover()` 的返回结构不变（仍为 `[{name, path, discovered, exists}]`），跳过的目录**不**进入返回值。这与 `dashboard-overview`「错误态卡片必须可见」的要求不冲突——后者针对的是**已发现但在聚合阶段失败**的项目，两者是不同情形。

**Trade-off**：目录整体不可读的真实 Fenixd 项目会从列表中消失且 UI 无提示，仅日志留痕。缓解：WARNING 日志含路径与 errno；`ignored` 通道可用；后续如需可扩展为 degraded 上报（非本次范围）。

### D4：聚合层隔离放在 `overview()` / `_api_projects()` 内部，逐项目

不在 handler 层做一次性 try/except——那只能把整页 500 换成整页降级，无法定位是哪个项目坏了。改为在跨项目循环体内 per-project 包裹，失败项目复用既有摘要 schema 的 `error` 键（`data.py:3753` 的 `exists=False` 分支已在用这个键），且**不累加**该项目对 `totals` 的任何贡献。

`exists` 语义保持：路径本身可解析（`is_dir`）即 `exists=True`，失败原因只体现在 `error` 字段——避免 UI 把「不可读」误渲染成「项目不存在」。

### D5：`projects()` 缓存异常兜底 —— 保留上次成功结果并推进时间戳

```python
try:
    self._projects_cache = self.registry.discover()
except Exception:
    # 保留 self._projects_cache 原值；记录错误；不抛出
self._cache_ts = now          # 无论成败都推进
```

关键在 `_cache_ts` 的**无条件推进**：若只在成功时推进，TTL 判断恒为过期，每个请求都会重跑注定失败的发现——这正是事故中「每请求重炸」的机制。

**Alternatives considered**：异常时不推进时间戳（保持快速重试以便尽快恢复）——被否，会放大故障期负载且测试上表现为调用次数不可控；改为按 `_cache_ttl` 节奏重试，兼顾恢复速度与稳定性。

### D6：前端降级采用「保留 stale data + 错误提示 + 重试入口」

`overview/index.tsx` 的状态处理改为：请求失败时 **不清空** `data`，设置 `error`；渲染时若 `data` 非空则照常渲染卡片与 `totals`，并在其上叠错误提示与「重试」按钮；若 `data` 为空（首屏即失败）则只渲染错误提示 + 重试。

**备选方案**：失败时清空 `data` 显示全屏错误页——被否，正是当前事故的表现（一次刷新失败 → 整页空白）。

### D7：`dist` 产物声明为 `reference`

前端改动需重建 `core/dashboard/static/dist/index.html`。该路径为构建产物（gitignored / 运行时重建），在 `tasks.md` 的 Deliverables 中声明为 `reference`，不作为交付物硬校验。

## Risks / Trade-offs

- **[静默跳过掩盖真实的 Fenixd 项目临时不可读]** → 缓解：WARNING 日志含路径与 errno；`ignored` 通道可反向使用；设计上保留后续升级为 degraded 上报的空间（D3）。
- **[`ignored` 路径规范化对不可读路径的可靠性]** → `_norm()` 用非 strict `resolve()` 且外层已包 `try/except (OSError, RuntimeError)`，失败时退化为未展开路径；风险是「写入侧」与「扫描侧」规范化结果不一致导致匹配失败。缓解：两侧共用 `_norm()`，并在验证场景中断言「写入后确实被短路」。
- **[跳过仅覆盖 `OSError` 家族，其它异常类型（如 `RuntimeError`、符号链接循环）仍可能穿透]** → 探测层的 `except` 收 `OSError`；`ELOOP` 本身已被 `is_file()` 吞掉。若需更宽兜底，可在循环体外再加一层，但会牺牲可诊断性，本次不做。
- **[聚合层 per-project `except Exception` 可能吞掉真实编程错误（如 `AttributeError`）]** → 接受的代价：错误文本写入该项目 `error` 字段并在 UI 可见，不会静默丢失；与既有 `server.py` 兜底风格一致（本项目历史上多次因「不隔离导致整页失败」付出代价）。
- **[前端保留 stale data 可能与 SSE 增量状态更新不一致]** → SSE 事件仍按既有逻辑驱动告警横幅等局部刷新，`overview` 数据本身由 30s 心跳校准；刷新失败期间展示的是自洽的上一次快照。
- **[重建 `dist` 遗漏导致前端改动不生效]** → 验证场景须经 `:8787` 实跑断言（本项目既有教训：dist 与 src 漂移会造成「改了但界面没变」）。

## Migration Plan

无数据/配置迁移。部署步骤：

1. 重启 8787 上的 dashboard 进程（tmux 会话 `fenix-dashboard`）使后端改动生效。
2. 重建前端 `dist`。
3. 回滚：revert 提交并重启进程即可，无持久化状态变更（`dashboard.yaml` 结构不变）。

## Open Questions

- 无阻塞性未决项。后续可评估：是否将跳过的不可读目录上报为 degraded 条目（D3 的非目标，待观察到「静默漏项目」造成实际损失时再立项）。
