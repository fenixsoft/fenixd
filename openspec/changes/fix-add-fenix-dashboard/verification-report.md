# Fenix Dashboard Bug 修复验证报告

- **SPEC**: fix-add-fenix-dashboard
- **验证时间**: 2026-08-24
- **验证方式**: Playwright 浏览器测试 + API 测试 + 构造 UTF-8 边界测试文件
- **修复的 Bug**: `_read_run_lines` UTF-8 解码异常导致 API 500

## 结论：全部通过（10/10）

| 状态 | 数量 |
|------|------|
| 通过 | 10 / 10 |
| 失败 | 0 / 10 |

---

## 核心 Bug 修复验证

### Bug 1 & 2: `_read_run_lines` UTF-8 边界解码异常（已修复）

**修复前**: `f.seek(size - 4096)` 后直接用文本模式读取，当 seek 位置落在多字节 UTF-8 字符（如中文）的续字节上时，会抛出 `UnicodeDecodeError`，导致所有依赖运行数据的 API 500。

**修复后**（`core/dashboard/data.py:374-403`）:
1. 改用二进制模式读取文件
2. seek 后向前扫描直到合法的 UTF-8 起始字节（`(byte & 0xC0) != 0x80`）
3. 使用 `decode("utf-8", errors="replace")` 双重保险
4. `except OSError` 保持不变（UnicodeDecodeError 不再会触发，因为 errors="replace" 已兜底）

**验证方法**: 构造了精确的测试文件，使得 `size - 4096` 字节位置正好落在中文的续字节（0xad）上：
- 旧方法（无修复）: `'utf-8' codec can't decode byte 0xad in position 0: invalid start byte`
- 新方法（已修复）: 跳过 1 个续字节，成功解码，API 返回 HTTP 200

---

## 场景测试详情

### 核心修复验证（3 场景，3 通过）

| # | 场景 | 结果 | 证据 |
|---|------|------|------|
| 1 | 构造 UTF-8 边界测试文件，验证旧方法会失败 | ✅ 通过（旧方法抛出 UnicodeDecodeError） | 命令行验证 |
| 2 | UTF-8 边界文件的 runs API 返回 200 而非 500 | ✅ 通过（HTTP 200，events 正常解析） | API 测试 |
| 3 | 348KB 中文运行文件的 API 正常返回（254 个事件） | ✅ 通过（当前 verifier 运行文件，实时读取无异常） | API + 浏览器测试 |

### dashboard-ui（4 场景，4 通过）

| # | 场景 | 结果 | 证据 |
|---|------|------|------|
| 4 | 概览展示多项目统计（含中文运行文件项目） | ✅ 通过 | `01-overview-page.png` |
| 5 | 概览自动刷新（2s 轮询） | ✅ 通过（network 面板观测到多次 `/api/overview` 请求） | 浏览器 network 观测 |
| 6 | SPEC 详情展示任务与验证进度 | ✅ 通过 | `02-spec-detail.png` |
| 7 | 运行中对话实时渲染（含中文内容） | ✅ 通过（254 个事件，滚动容器高度 15111px） | `03-run-events.png` |

### dashboard-server（3 场景，3 通过）

| # | 场景 | 结果 | 证据 |
|---|------|------|------|
| 8 | 损坏数据源容错（损坏 JSON progress 文件） | ✅ 通过（HTTP 200，不崩溃） | API 测试 |
| 9 | 路径穿越防护 | ✅ 通过（`../../../etc/passwd` 返回 404） | API 测试 |
| 10 | 仅本机可访问 | ✅ 通过（ss 验证绑定 127.0.0.1:8790） | `ss -tlnp` 验证 |

---

## 补充验证：滚动位置保持

运行事件容器在自动刷新后保持滚动位置不变：设置 scrollTop=5000，等待 4 秒（经过 2 次刷新轮询）后仍为 5000。

---

## 测试环境

- **Dashboard 版本**: `bin/fenix_dashboard.py --serve`
- **端口**: 8790（127.0.0.1 绑定）
- **测试项目**:
  - fenixd（5 个 SPEC，2 个活跃运行，含当前 verifier 的 348KB 中文运行文件）
  - test-project（构造的边界测试项目，含 UTF-8 边界测试文件）
- **浏览器**: Playwright / Chromium
- **API 测试**: curl + Python 直接构造边界文件验证

## 截图证据

- `screenshots/01-overview-page.png` — 跨项目概览首页（2 个项目均正常显示）
- `screenshots/02-spec-detail.png` — SPEC 详情页（任务/验证进度）
- `screenshots/03-run-events.png` — 运行中 Agent 实时 LLM 对话（含中文内容）
