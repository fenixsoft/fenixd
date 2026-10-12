## ADDED Requirements

### Requirement: 语法级快档
scripts/check-win-compile.sh SHALL 缺省对参数指定的源文件集（无参数时对仓库 win 条件编译文件全清单）执行 x86_64-w64-mingw32-g++-posix -fsyntax-only 编译检查，include/define 集按 target 复用 build-win 下对应 CMake target 的 flags.make（或 includes_CXX.rsp）；任一文件报错 MUST 以非零退出码终止并打印出错文件与首条错误。

#### Scenario: 当前树通过
- **WHEN** 在编译健康的 HEAD 上执行 scripts/check-win-compile.sh
- **THEN** 退出码 0，逐文件输出检查结论，总耗时在秒级量级

#### Scenario: 捕获 win 分支重复声明
- **WHEN** 对一个含 win 分支内重复变量声明的源文件执行快档
- **THEN** 退出码非 0，输出含该文件名与 redeclaration 首条错误

### Requirement: 全量档
scripts/check-win-compile.sh --full SHALL 调用 scripts/build-win.sh --no-deps 执行全量交叉构建，构建失败即非零退出；该档供实现 run 收工自证使用。

#### Scenario: 全量交叉构建通过
- **WHEN** 在编译健康的 HEAD 上执行 scripts/check-win-compile.sh --full
- **THEN** build-win.sh --no-deps 构建成功，退出码 0

### Requirement: 工具缺失显式失败
宿主缺少 mingw 工具链（which 探测失败）或 build-win 依赖缓存缺失时，脚本 MUST 以专用退出码显式报错并说明补救命令，MUST NOT 静默跳过或以退出 0 收场。

#### Scenario: 工具链不可用
- **WHEN** PATH 中无 x86_64-w64-mingw32-g++-posix 时执行脚本
- **THEN** 非零退出，错误信息区分「工具不可用」与「编译失败」并给出安装/修复指引

### Requirement: 门禁约定入库
CLAUDE.md SHALL 写明：触及 win-only 路径（#ifdef _WIN32 面）的改动，提交前必过快档；实现 run 收工自证前必过 --full 档。该文件 MUST 提交入库（worktree 内可见）。

#### Scenario: 约定可发现
- **WHEN** 实现 run 或交互直改会话在仓库内工作
- **THEN** 仓库根 CLAUDE.md 含上述门禁约定与 13 文件敞口面的盘点命令（grep -rl 窗口的 #ifdef _WIN32）