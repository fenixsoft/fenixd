# check_health 两大 Windows 实测缺陷：裸名 spawn 与 GBK 解码（v0.1.9 勘误 B1/B2 治本记录）

来源：全新 Windows（zh-CN 代码页 936/GBK）制品路径安装实测（用户投递
fenixd-install-manual-errata.md，v0.1.9 + dsh-plugins v0.1.3 + dsh 0.2.2-rc.5）。
修复：commit 15bab607a（main，随下个 fenixd 发布携带）。

## B1：check_health 是全框架唯一不消费解析单源的 spawn 点

- 根因：`core/agent_runner/harness/dsh_adapter.py` check_health() 用裸名
  `[self._config.dsh_bin, "--version"]` 发起 spawn。Windows `CreateProcess` 裸名只
  自动补 `.exe`，而 npm 全局的 dsh 只有 `.cmd`/`.ps1` shim（包不带真身 exe）→
  `WinError 2`。dispatch 主路径 `spawn_argv0` 走 `resolve_harness_executable`
  （harness/__init__.py 定义）正常——同一台机器「dispatch 能跑、健康门恒挂」。
- 治本：两处 subprocess.run（--version 探针 + --dump-config 探针）argv[0] 均改
  `resolve_harness_executable(self._config.dsh_bin)`；解析 None → HarnessHealthError
  带 `HARNESS_CLI_UNAVAILABLE_MARKER`（与「未装」路径同归因标记）先 fail-fast，
  不发起 spawn。
- 结构教训：**任何 spawn 都必须消费解析单源**——「which 能找到的就是能 spawn 的」
  在 Windows 上不成立于裸名形态。新加 spawn 点时以 dispatch 为模板。

## B2：check_health 读流无 encoding → GBK locale 下假阴性

- 根因：`text=True` 不带 encoding 时按 locale（GBK）解码。`--dump-config` 产物含
  UTF-8 中文（patch 注释/插件描述）→ `UnicodeDecodeError: 'gbk' codec can't decode
  byte 0x94` → stdout 空 → 误报「未挂载 fenix-dsh-bundle」。注入 PYTHONUTF8=1 即恢复。
- 治本：两调用显式 `encoding="utf-8", errors="replace"`（CLI 产物恒为 UTF-8；
  replace 保探针健壮性）。
- 结构教训：**跨进程读流禁止依赖 locale**——凡 text=True 必显式 encoding；文档面
  服务环境最小集仍建议带 PYTHONUTF8=1（覆盖存量版本与其他 Python 子进程）。

## 实现注意：循环导入

`from core.agent_runner.harness import resolve_harness_executable` 不能放模块级——
包 `__init__` 先 import dsh_adapter（L61）、后定义该单源（L147），模块级导入撞
partially-initialized 循环（实测 ImportError）。check_health 内函数级导入解决。

## 测试锚点

tests/test_harness_dsh_adapter.py::TestCheckHealth 新增 3 测（monkeypatch 目标是
`core.agent_runner.harness.resolve_harness_executable` 包属性，非 dsh_adapter 模块属性）：
test_spawn_consumes_resolved_executable_single_source /
test_unresolved_binary_fail_fast_before_spawn / test_decode_explicit_utf8_regardless_of_locale。
注意既有 TestCheckHealth 用例在本机能过依赖本机 which("dsh") 可解析（真装了 dsh）。
