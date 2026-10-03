# 项目架构图（archify 按需生成）

<!-- knowledge: capability=project-architecture-diagram rev=1
     sources=spec/archive/2026-10-04-add-project-architecture-tab -->

项目详情页的「项目架构」页签：用户手动触发生成项目高层运行时架构图（headless claude 挂 archify skill），产物经后端下发、前端沙箱渲染，让读者快速看懂项目核心组件、主链路与外部依赖。

## 规则

- 页签与手动触发：项目详情页页签序列固定为 …→测试回归→项目架构（key `architecture`、label「项目架构」）→会话接入，对全部注册项目一视同仁（无项目级特殊处理），未注册项目查询一律 404。页签内容由独立组件 ArchitectureTab 承载，按 `active` 门控——仅选中本页签才发起请求，未选中零请求。系统不得在页面加载、页签切换、daemon 启动等任何时机自动触发生成；从未生成时展示空态提示与「刷新架构图」按钮。
- 生成范式：点击「刷新架构图」后 POST 只受理并立即返回，实际生成由 daemon 后台线程执行一次性 headless claude：`claude -p <提示词> --permission-mode bypassPermissions`，cwd=项目根，`start_new_session=True`，env=`os.environ.copy()` 剔除 agent-run 专用三键（FENIX_RUN_PROJECT_ROOT / FENIX_RUN_WORKTREE / CLAUDE_CODE_ENABLE_TODO_TOOLS）。HTTP 线程不得同步等待生成（范式见 ADR-216）。生成完全在开发主链路之外：无 run 台账、无车道、无预算、无新增配置项，超时等均为模块常数。
- archify skill 保障：spawn 前探测 skill 安装，`$CLAUDE_CONFIG_DIR/skills/archify/SKILL.md` 与 `~/.claude/skills/archify/SKILL.md` 两处都查（settings env 可能覆盖 CLAUDE_CONFIG_DIR）；缺失时后台线程自动执行 `npx skills add tt-a1i/archify -g`（限时 120s）；安装失败或超时判 failed，错误信息原样携带该安装命令供人工执行。
- 图形态契约（约束落在提示词文本）：只保留 8–16 个核心组件；突出且仅突出一条主要路径；标注外部依赖与信任边界；辅助信息放说明卡片而非继续增加连线；节点与说明文字用中文。组件数机械校验只对「能提取到」的情况生效——提取到则越出 8–16 判 failed（错误信息含实际组件数与允许范围）；marker 缺失提取不到时记 `component_count: null` 放行，产物可用性优先于校验完备性。
- 产物判定权威链：进程退出码 → diagram.html 存在且非空 → 自包含 HTML 特征（起始 `<html` / `<!DOCTYPE html`）→ 组件数提取（stdout 末行 marker `ARCHIFY_DONE <组件数>`，缺失则从产物提取）。判定权威是产物实况，不采信 claude 自述（口径见 ADR-217）；任一必需环节不满足判 failed。
- 存储与单写者：产物按项目存于项目根 `.fenix/architecture/`（`diagram.html` + `status.json`，gitignored 运行时产物，目录按需创建），每次状态迁移 tmp+rename 原子写；dashboard 进程内 ArchitectureManager 持单飞锁与在飞进程句柄，是唯一写者。刷新即覆盖旧图，只保留最近一次，无历史版本。status.json 字段：`state` / `generated_at` / `started_at` / `error` / `duration_ms` / `component_count`。
- API 端点（mixin 形态，query 传 project）：`GET /api/architecture/status` 返回 state（`none|generating|ready|failed`）、generated_at 与失败原因等；`POST /api/architecture/refresh` 受理返回 200，在飞期间重复 POST 返回 409 语义（不产生第二个 claude 进程）；`GET /api/architecture/diagram` 以下发 `text/html` 返回产物字节。state=none 时 diagram 返回 404 结构化 JSON 错误，前端不渲染 iframe。
- 生命周期治理（无死态）：同一项目同时至多一个在飞生成（per-project 单飞）；超时上限 1800 秒（模块常数），到时以进程组方式击杀 claude 及其派生子进程并判 failed（错误信息注明超时）；daemon 重启后 status.json 残留 generating 而内存无在飞进程时，读侧合成为 failed（生成被中断），不得永久停留 generating；failed 态展示错误信息且按钮恢复可点，重试受理即开始新一轮生成，旧失败原因被覆盖。
- 前端渲染：generating 期间以 3s 固定间隔轮询 status（活动门控内），刷新按钮置灰并提示生成中；ready 后以 `<iframe sandbox="allow-scripts">` 渲染产物（sandbox 恰为 allow-scripts，不给 allow-same-origin，产物脚本与主站 cookie/DOM 隔离，见 ADR-218），同时展示生成时间等元信息，按钮可再次点击；容器用显式 flex 布局定高（`calc(100vh - 头部实测偏移px)` 加 minHeight 兜底），移动端按 useIsMobile 换用移动档常数，避免越界。

## 溯源

- 2026-10-04 add-project-architecture-tab（spec/archive/2026-10-04-add-project-architecture-tab） — 新建本能力：项目详情页新增「项目架构」页签，确立手动触发、一次性 headless claude + archify 生成、单飞/超时/重启残留合成三件套生命周期治理、`.fenix/architecture/` 产物存储与 3 端点下发、iframe 沙箱渲染契约
