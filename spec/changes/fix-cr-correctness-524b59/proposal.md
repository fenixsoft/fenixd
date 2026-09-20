## Why

代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。

## What Changes

- 修复以下审查发现（SPEC `fix-cr-correctness-524b59`）：

### [major] `_git` never inspects `returncode`, and 

- 类别：`correctness`
- 位置：`bin/fixture_scheduling_showcase.py:91`

**问题描述**：

`_git` never inspects `returncode`, and `_commit_baseline` discards both `_git` results. If `git init`/`add`/`commit` fails (git missing, no identity usable, pre-existing broken index), `reset_fixture` still prints `fixture created (fresh baseline commit)` and returns 0, so the prepare step reports success while the fixture has no HEAD — a later daemon `worktree add` will then fail inside the scenarios, producing another confusing env failure. Check the return codes and surface a FAIL (or at least a clear WARN) instead of unconditionally claiming success.

**证据**：

bin/fixture_scheduling_showcase.py:91（ocr scan）

### [major] Non-atomic baseline writes. `Path.write_

- 类别：`correctness`
- 位置：`bin/fixture_scheduling_showcase.py:191`

**问题描述**：

Non-atomic baseline writes. `Path.write_text` truncates then writes, so a resident fixture daemon (or a concurrently running seed/status reader) can observe a zero-length or half-written STATE.md/config.yaml and fail spec-status assertions — exactly the failure mode `_reset_alerts_baseline` was explicitly hardened against a few lines below. Use the same mkstemp + `os.replace` form for these two baselines as well (factor a shared `_atomic_write_text` helper so all three baselines stay consistent).

**证据**：

bin/fixture_scheduling_showcase.py:191（ocr scan）

### [major] An explicitly configured `admin.shutdown

- 类别：`correctness`
- 位置：`core/config.py:1068`

**问题描述**：

An explicitly configured `admin.shutdown_drain_seconds: 0` is documented as "fast shutdown / no drain" and `_validate` explicitly allows 0 (it only rejects negatives), but the `or 1800` truthiness fallback here treats 0 as falsy and restores the 1800 default. The fast-shutdown path can therefore never be requested through this facade, contradicting the function's own docstring ("0 = 快速停机") and the daemon/supervisor readers that honor 0. Use an explicit `is None` check instead of truthiness.

**证据**：

core/config.py:1068（ocr scan）

### [major] Keep-alive body-drain gap on early retur

- 类别：`correctness`
- 位置：`core/dashboard/routes/base.py:448`

**问题描述**：

Keep-alive body-drain gap on early returns: the 405 branch for non-GET on `/api/stream`, the 405 branch for `POST`/`PUT`/`PATCH` on `/`/static paths, and the 503 `server busy` fast-path in `handle_one_request` all return without draining the request body. Under HTTP/1.1 keep-alive the leftover body bytes are parsed as the next request line — the exact BUG-01 desync class the POST/DELETE branches below are careful to avoid. `_drain_remaining_request_body` is already safe to call here (`_request_body_consumed` is reset at the top of `_handle_inner` and defaulted via `getattr`), so drain the remaining body before emitting the 405/503.

**证据**：

core/dashboard/routes/base.py:448（ocr scan）

### [major] In-flight dedup matches the project name

- 类别：`correctness`
- 位置：`core/dashboard/routes/settings_routes.py:375`

**问题描述**：

In-flight dedup matches the project name by substring, so a request for a project whose name is a prefix of another in-flight signal's project is wrongly suppressed (e.g. `项目名=proj` is contained in `项目名=proj2; 覆盖确认=是`). The endpoint then answers `dispatched` but no signal is written, so the user waits for a draft that will never come. Match the `项目名=` field with an explicit delimiter instead of a bare `in` test (note `evidence` is also written by `core/worktree_manager/mergeback.py:274` with the same pattern).

**证据**：

core/dashboard/routes/settings_routes.py:375（ocr scan）

### [major] Truncated/malformed `/proc/net/tcp` line

- 类别：`correctness`
- 位置：`core/dashboard/server.py:206`

**问题描述**：

Truncated/malformed `/proc/net/tcp` lines are only guarded with `len(parts) < 4`, but `parts[9]` (the socket inode) is read further down. A line with 4–9 fields raises `IndexError`, which is swallowed by the outer `except Exception: return None`, so any parse failure becomes indistinguishable from “no occupant”. In `serve()` this makes the caller print the misleading “未知进程” message and exit non-zero instead of taking over a stale dashboard instance. Guard the actual index used (inode is field 10) and avoid silently converting parse errors into “no process found”.

**证据**：

core/dashboard/server.py:206（ocr scan）

### [major] SSE 分支是死代码：后端 watcher/sse 只广播 `refresh` 

- 类别：`correctness`
- 位置：`core/dashboard/static/src/pages/projects/components/QualityTab.tsx:143`

**问题描述**：

SSE 分支是死代码：后端 watcher/sse 只广播 `refresh` / `state` / `detail` / `run_events` / `run_meta` / `admin_activities`（core/dashboard/watcher.py），全仓库不存在 `code_review_updated` / `code_review_run_done` 事件（grep 仅命中本文件）。也就是说这条「随 SSE 增量刷新」链路实际永不触发，数据新鲜度完全依赖 2s 轮询与 30s 心跳，而 30s 心跳期间审阅结果不会刷新。建议改为订阅后端真实事件（如 `refresh`/`state` 中与 project 匹配的帧）或让后端补发专用事件，避免误导后续维护者。

**证据**：

core/dashboard/static/src/pages/projects/components/QualityTab.tsx:143（ocr scan）

### [major] `item.summary ?? null` 把「summary 字段缺失/为 

- 类别：`correctness`
- 位置：`core/dashboard/static/src/pages/projects/list.tsx:578`

**问题描述**：

`item.summary ?? null` 把「summary 字段缺失/为 undefined」与「显式删除」并入同一语义：只要后端某次事件因序列化或字段裁剪导致 summary 缺失，本地表就会误删该行（列表行流式消失）。建议只在显式删除标识存在时才当作删除标记，例如区分 `item.summary === null`（契约上的删除）与字段缺失（忽略该条）。

**证据**：

core/dashboard/static/src/pages/projects/list.tsx:578（ocr scan）

### [major] Tri-state read-back uses `=== undefined`

- 类别：`correctness`
- 位置：`core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288`

**问题描述**：

Tri-state read-back uses `=== undefined`, but the backend (`worktree_config_view`) always emits the key and returns `None` for「未裁决」, which serializes to JSON `null` (not `undefined`). In the read-only (user-scope) branch this makes all three branches false when the value is `null`, so the row renders as an empty label (“需要豁免的派生产物：” with nothing after it). Compare against `null` instead (or derive a normalized tri-state), and widen `toFormState`'s parameter type to include `null`.

**证据**：

core/dashboard/static/src/pages/settings/components/VerifyPanel.tsx:288（ocr scan）

### [major] `loadConfig` has no cancellation/ignore 

- 类别：`correctness`
- 位置：`core/dashboard/static/src/pages/settings/index.tsx:91`

**问题描述**：

`loadConfig` has no cancellation/ignore guard. Rapidly switching project (or scope) fires overlapping requests, and a slower earlier response can resolve after a newer one, overwriting `config` with stale data for the previously selected project. Add a cleanup flag (or AbortController) and bail out of `setConfig`/`setLoading` when the effect has been superseded.

**证据**：

core/dashboard/static/src/pages/settings/index.tsx:91（ocr scan）

## Capabilities

### New Capabilities

- 修复 code-review 台账中选中的代码质量问题。

## Impact

- 修改 `## Deliverables` 声明段所列文件。
