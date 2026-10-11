## Context

10-11 窗口两处 win-only 缺陷（run 内 2 轮修复 + 4 分 21 秒坏 tip）证明交叉编译错误只能后置暴露：收工自证实测为 `PYTHONPATH=/root/fenixd python3 -m core.agent_runner.result_gate --selfcheck`（结果文件 schema 自检，无编译项）；spec 内交叉构建（add-mediaremover-tool tasks 2.2）是后置验收任务；receiver 走无 SPEC 直改，无任何门禁。990133e 版错误已用 -fsyntax-only 实测复现（EXIT=1 redeclaration），单文件 0.79~3.5 秒。

仓库约束：第一方 win 条件编译面 13 文件（receiver/src/{main,gui}.cpp、tools/mediaremover.cpp、pack2/src/{main,video_muxer,stream_muxer,hls_http_server}.cpp、station/src/{main,assembler}.cpp、common/src/ffmpeg_pipe.cpp、common/include/vbit_common/utf8_path.h、tests/{test_pack2_stream,test_symbol_store}.cpp）；build-win/ 各 target 的 CMakeFiles/<t>.dir/flags.make 存有交叉编译 include/define 集可复用；CLAUDE.md 不存在且从未存在过（git 全历史为空），新建须入库才能进 worktree。脚本风格参照 scripts/build-win.sh（bash、log/die 函数、中文头注释）。

## Goals / Non-Goals

**Goals:**
- 提交/收工前一键可跑：快档秒级（-fsyntax-only）、--full 档分钟级（build-win.sh --no-deps）
- 失败非零退出+首条错误直接可读；工具缺失与编译失败退出码可区分
- 约定入 CLAUDE.md，实现 run 与交互直改共用同一门禁

**Non-Goals:**
- 不做 win 运行时验证（VM 侧验证链已另有覆盖）
- 不改构建脚本/CMake/仓库工作流（无 CI）
- 不优化全量档耗时

## Decisions

### D1 两级档位：快档缺省、全量选配
-fsyntax-only 实测秒级且已复现抓到本轮 redeclaration 错误，足以拦截绝大多数 win-only 编译错误；--full 档复用 build-win.sh --no-deps 兜住链接级/头档缺失类。备选「只做全量档」被否：分钟级成本不适合提交前频跑。

### D2 include 集复用 build-win 缓存而非自维护清单
按 target 读 build-win/<target>/CMakeFiles/<t>.dir/flags.make（或 includes_CXX.rsp），避免手维护 include 清单漂移；build-win 缓存缺失时快档显式报「先跑一次 build-win.sh --no-deps」，不静默降级。

### D3 约定落 CLAUDE.md 而非 git hooks
仓库无 hooks 惯例（.git/hooks 仅 sample），且 hook 不入库、对实现 run 的 worktree 不生效；CLAUDE.md 入库后实现 run 与交互直改会话都会读到。备选 pre-commit hook 被否。

### D4 工具缺失显式失败
toolchain 探测失败即专用退出码+补救指引——门禁最怕假绿，静默跳过等于没有门禁。