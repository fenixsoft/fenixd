## Why

10-11 一个窗口内两处 win-only 缺陷都没被前置捕获：add-mediaremover-tool 实现 run（impl-add-mediaremover-tool-1791681211，1188 秒/$3.85）连做 2 轮交叉构建修复（09499aa/f3c0fad）才达编译加运行通过；receiver 重构提交 990133e 引入 win 分支重复声明，主树 tip 对 win 目标坏 4 分 21 秒（ab3930c 修复）。两者均可由秒级的交叉编译检查前置捕获——已用 x86_64-w64-mingw32-g++-posix -fsyntax-only 对 990133e 版实测复现 redeclaration 错误、单文件 0.79~3.5 秒。仓库第一方 #ifdef _WIN32 面共 13 个文件，而收工自证（result_gate --selfcheck）只查结果文件 schema、不含编译项，spec 内交叉构建只是后置验收任务，receiver 直改则完全无门禁——每个触及 win 路径的改动都靠后置修复轮或坏 tip 暴露。需要把交叉编译检查前置为强制门禁。

## What Changes

- 新增 `scripts/check-win-compile.sh`：缺省语法级快档（按 target 复用 build-win 各 target 的 flags.make include/define 集，x86_64-w64-mingw32-g++-posix -fsyntax-only，秒级）+ `--full` 档（`scripts/build-win.sh --no-deps` 全量交叉构建，分钟级）；任一失败非零退出，工具链缺失与编译失败退出码可区分
- 新建仓库根 `CLAUDE.md`（入库）：约定「触及 win-only 路径的改动，提交前必过快档；实现 run 收工自证前必过 --full 档」，附 13 文件敞口面的盘点命令
- 不改现有构建脚本、CMake 目标与既有 spec 任务

## Capabilities

### New Capabilities
- `win-cross-compile-gate`: win 目标交叉编译前置门禁——语法级快档与全量档两级，失败阻断提交/收工，工具不可用显式报错不静默跳过

### Modified Capabilities

（无——spec/changes/ 与 spec/archive/ 均无编译门禁类既有能力）

## Impact

- **新增文件**：`scripts/check-win-compile.sh`、`CLAUDE.md`，零现有文件改动
- **依赖**：宿主 mingw 工具链（实测在位：GCC 10-win32+posix 变体）与 `$HOME/.cache/cimbar-win-deps` 依赖缓存（就位）；无新第三方依赖
- **运行成本**：快档秒级/文件（实测 0.79~3.5 秒），全量档分钟级（未实测）
- **无破坏性变更**：门禁只读源码与 build-win 缓存，不改任何构建产物