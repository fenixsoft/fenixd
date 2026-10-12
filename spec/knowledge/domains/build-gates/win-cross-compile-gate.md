# win 交叉编译前置门禁
<!-- knowledge: capability=win-cross-compile-gate rev=1
     sources=spec/archive/evo-add-win-cross-compile-gate-1791765068 -->

win 目标（`#ifdef _WIN32` 面）编译错误的前置拦截门禁：以秒级语法检查与分钟级全量交叉构建两档，在提交与实现 run 收工自证之前拦下 win-only 编译缺陷。

## 规则

- 两级档位，快档缺省：`scripts/check-win-compile.sh` 无参数时对仓库 win 条件编译文件全清单逐个执行 `x86_64-w64-mingw32-g++-posix -fsyntax-only` 语法检查；带文件参数时只查指定子集。include/define 集按 target 复用 build-win 下对应 CMake target 的 flags.make（或 includes_CXX.rsp），不自维护 include 清单。
- 任一文件报错即以非零退出码终止，打印出错文件与首条错误；全部通过退出 0 并逐文件输出检查结论。
- 全量档：`scripts/check-win-compile.sh --full` 调用 `scripts/build-win.sh --no-deps` 执行全量交叉构建（分钟级），构建失败即非零退出，兜住链接级与头档缺失类错误；该档供实现 run 收工自证使用。
- 工具缺失显式失败：宿主缺 mingw 工具链（which 探测失败）或 build-win 依赖缓存缺失时，以专用退出码显式报错并给出补救命令；「工具不可用」与「编译失败」退出码可区分，不静默跳过、不以退出 0 收场。
- 门禁约定写在仓库根 CLAUDE.md 并随仓库入库（实现 run 的 worktree 与交互直改会话均可见）：触及 win-only 路径（`#ifdef _WIN32` 面）的改动，提交前必过快档；实现 run 收工自证前必过 --full 档；失败阻断。

## 关键行为

- 第一方 win 条件编译敞口面共 13 个文件：receiver/src/{main,gui}.cpp、tools/mediaremover.cpp、pack2/src/{main,video_muxer,stream_muxer,hls_http_server}.cpp、station/src/{main,assembler}.cpp、common/src/ffmpeg_pipe.cpp、common/include/vbit_common/utf8_path.h、tests/{test_pack2_stream,test_symbol_store}.cpp；以 `grep -rl _WIN32` 盘点命令的结果为敞口面权威口径。
- 门禁定位是编译级检查，不替代 win 运行时与 VM 侧验证链。

## 溯源

- 2026-10-12 evo-add-win-cross-compile-gate-1791765068（spec/archive/evo-add-win-cross-compile-gate-1791765068） — 新增本页全部规则：语法级快档与 --full 全量档两级门禁、按 target 复用 build-win flags 的 include 集、工具缺失显式失败、CLAUDE.md 门禁约定入库
