# Design: fix-windows-review-longtail

> 归属变更：fix-windows-review-longtail（fast-track）
> 上游输入：三轮部署评审 C3/C4 + v0.1.0 部署实录（C5–C9）
> 基线约束：spec/knowledge/domains/daemon-runtime/windows-native-support.md
> —— Linux 零变化硬约束；过机复验铁则（本轮改动全部落在日志/解码/preflight 路径，
> 不触进程 API 契约，以 Linux 契约测试收口 + 设计声明豁免，下次过机窗口顺带复验）

## 决策

### D1 — install_unit 告警分级：None=预期态

`_service_state` 返回 None 同时覆盖「未安装」与「sc query 瞬时失败」两种形态。
区分口径（按 sc 退出码判别；退出码为数字、locale 无关，与 `_sc_query` 既有
解析纪律一致）：

- **`sc query` 退出码 == 1060**（ERROR_SERVICE_DOES_NOT_EXIST，服务确实未装
  = 首装预期态）→ debug 级留痕或静默，直接走安装决策；
- **其余失败证据**（超时/SubprocessError/OSError/其他非零退出码/rc 0 但无
  STATE 段的解析失败）→ 保留 warning（这是真异常信号）。

> **关键机制事实（评审修补）**：`sc query <未安装服务>` 本身就以**非零码
> 1060** 退出——首装正常路径天然落在「非零返回」里。若按「非零返回 ⇒ 告警」
> 的朴素口径实现，首装路径将照旧发 warning，C4 目标不可达。故预期态判据
> MUST 是**退出码 == 1060**，而非「非零」。
> 落地上 `_sc_query`/`_service_state` 需把失败证据（退出码/异常形态）透传给
> `install_unit`（如 `_sc_query` 返回 `(rc, out)` 或抛携带 rc 的私有异常）；
> 两者均为 `_` 前缀私有助手，不属于六协议公开进程 API 面，不触过机复验铁则。

`install_unit` 返回 JSON 形状（`ok/error/already/unit`）与安装语义不变。
sc 抖动误入重装分支的纠偏已有兜底（`nssm install` 失败 → sc 复查 → already=True
启动路径），本决策不改该链。

### D2 — subprocess 解码：全 capture_output 处 text=True + utf-8 + errors=replace

GBK 控制台+提权 PS5.1 下 sc.exe 输出含 GBK 双字节（首字节 0xb0 等），按默认
locale 解码抛 `UnicodeDecodeError`。**决策按 UTF-8 + errors=replace 解码而非 GBK**：
sc/nssm 输出语义在 ASCII 域（SERVICE_RUNNING / STATE / 4 RUNNING 等），
GBK 字节只出现在中文 Windows 的服务描述等字段——替换降级不损判读语义，
且避免引入 cp936 平台依赖（Linux 侧跑测试时不依赖 GBK codec 行为）。
适用面：`core/platform/win32.py` 全部 `capture_output` 调用点（sc query、
nssm 系列、taskkill 等）。

### D3 — logger stderr 编码安全

含中文的 win32 日志写 stderr 在受限控制台编码下抛 UnicodeEncodeError。
实现口径：平台 logger 的 stderr handler 侧对流做 errors=replace 包装
（等价于 `sys.stderr.reconfigure(errors="replace")` 的 handler 层形态，
不污染进程全局 stderr）。Linux 侧 handler 不动。

### D4 — fenix-init preflight 前置（原子性）

骨架全读面 = `.fenix/config.template.yaml`、`.fenix/config.user.template.yaml`、
`FENIX_LINKS` 各项、`AGENT_LINKS` 各项、`templates/` 全部文件。
（其中 `config.user.template.yaml` 为 install.ps1 侧硬读面，fenix-init 本体
只读 `config.template.yaml`——前者入清单按「制品完整性」口径校验，实现时
不得以「fenix-init 不读」为由删除该项。）
`main()` 入口第一步（任何 mkdir/写盘之前）校验全部路径存在，缺失即
**exit 2 + 逐项缺失明细**。`render_config` 等后续失败时清理本次已建目录
（best-effort 回滚，保证不留半成品）。v0.1.0 的「mkdir 后才读模板崩溃」形态
被本决策结构性排除。

### D5 — `--version`

argparse `--version`，读包根 `VERSION` 文件；缺失时输出 `unknown` 并退出 0
（version 查询不是部署关键路径，不 fail-fast）。

### D6 — FENIX_LINKS 去 `__init__.py`

源码根（制品与 git 两形态）均无 `__init__.py`——清单悬空引用，preflight 会
永远拒绝。从清单移除；不虚构文件（fenixd.py 是唯一入口，包语义不需要它）。

### D7 — install.ps1 完整性硬失败

模板/部署面自检缺失时 **exit 1 + 缺失清单**（原 WARN + exit 0 是 v0.1.0
「看似成功」事故面）。与打包侧 `scripts/package.sh` 21 项断言（已落地）
构成双保险：打包侧防出包缺件，安装侧防解压/传输缺件。

### D8 — C3 注记模板

统一注记块（8 文件同构插入，置于首个可复制命令之前）：

> **Windows 命令换算**：本文 `python3` 在 Windows 上一律写作 `py -3`；
> 其余 Unix 形态命令按各节注记换算。

高频命令行内双写仅限每 skill 最常被复制执行的 1–3 处（`python3 X` →
`python3 X   # Windows: py -3 X`），禁止全文改写（保持 diff 可审）。

### D9 — 验证与豁免声明

- Linux 全量：`tests/test_platform_pal.py` + `tests/test_platform_guard.py`
  + `tests/test_dashboard_orphan_guard.py` 0 failed 0 新增豁免（Linux 零变化）。
- 纯逻辑层新增覆盖：preflight 缺模板 → exit 2 不落盘；`--version` 输出；
  `FENIX_LINKS` 无 `__init__.py`；win32 解码路径 errors=replace 冒烟
  （喂 GBK 字节序列断言不抛）。
- 过机豁免声明：本轮 win32 触点 = 日志分级/解码/编码安全（含 `_sc_query`/
  `_service_state` 私有助手的失败证据透传，不动公开六协议面），不触 Popen 句柄、
  ctypes、Job Object 等进程 API 契约——按知识页铁则以 Linux 契约测试收口，
  下次过机窗口顺带复验 D1–D3 行为。

## 交付清单（精确文件面）

- `core/platform/win32.py`（D1/D2/D3）
- `fenix-init`（仓库根脚本；D4/D5/D6）
- `install.ps1`（D7）
- `tests/test_platform_pal.py`（D9 纯逻辑覆盖）
- `skills/{8 个}/SKILL.md`（D8）
- （已随本轮提前落地，不占任务）`scripts/package.sh`、`.github/workflows/release.yml`、`docs/install.md` §3A/§4b/§8/§9.0/§10
