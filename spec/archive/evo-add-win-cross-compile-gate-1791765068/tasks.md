## Deliverables

```yaml
- path: scripts/check-win-compile.sh
  kind: new
- path: CLAUDE.md
  kind: new
```

## 1. 门禁脚本 scripts/check-win-compile.sh

- [ ] 1.1 语法级快档（缺省档）：无参数时对仓库 win 条件编译文件全清单（receiver/src/{main,gui}.cpp、tools/mediaremover.cpp、pack2/src/{main,video_muxer,stream_muxer,hls_http_server}.cpp、station/src/{main,assembler}.cpp、common/src/ffmpeg_pipe.cpp、common/include/vbit_common/utf8_path.h、tests/{test_pack2_stream,test_symbol_store}.cpp）逐个跑 x86_64-w64-mingw32-g++-posix -fsyntax-only；支持文件参数指定子集；include/define 集按 target 复用 build-win/<target>/CMakeFiles/<target>.dir/flags.make（或 includes_CXX.rsp）；任一文件报错非零退出并打印文件名与首条错误
- [ ] 1.2 --full 档：调 scripts/build-win.sh --no-deps 全量交叉构建，失败非零退出；供实现 run 收工自证使用
- [ ] 1.3 工具链与缓存前置探测：which x86_64-w64-mingw32-g++-posix 失败或 build-win 缓存缺失时以专用退出码报错并给出补救命令，不静默跳过；脚本风格对齐 scripts/build-win.sh（log/die 函数、中文头注释含用途/用法/退出码）

## 2. 门禁约定 CLAUDE.md（新建入库）

- [ ] 2.1 仓库根新建 CLAUDE.md 并提交入库：写明「触及 win-only 路径（#ifdef _WIN32 面）的改动，提交前必过 scripts/check-win-compile.sh 快档；实现 run 收工自证前必过 --full 档；失败阻断」
- [ ] 2.2 附敞口面盘点命令（grep -rl 窗口的 _WIN32 面文件清单）与门禁定位说明（编译级检查，不替代运行时与 VM 侧验证）

## 3. 自测

- [ ] 3.1 快档正向：当前 HEAD 上跑 scripts/check-win-compile.sh 退出 0，记录逐文件耗时（基线 0.79~3.5 秒/文件）
- [ ] 3.2 快档负向：以 mktemp 临时目录复制一份源文件并注入 win 分支重复声明类错误，以文件参数跑快档验证非零退出与错误输出；不污染仓库
- [ ] 3.3 --full 档：跑通一次 scripts/check-win-compile.sh --full（即 build-win.sh --no-deps）退出 0，记录耗时
- [ ] 3.4 工具缺失路径：以受限 PATH 模拟工具不可用，验证专用退出码与补救指引输出