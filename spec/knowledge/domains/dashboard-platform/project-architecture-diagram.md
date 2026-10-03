# 项目架构图（archify 按需生成）

<!-- knowledge: capability=project-architecture-diagram rev=3
     sources=spec/archive/2026-10-04-add-project-architecture-tab,spec/archive/2026-10-04-fix-archify-vendored-injection,spec/archive/2026-10-04-add-architecture-two-stage-generation -->

项目详情页的「项目架构」页签：用户手动触发生成项目高层运行时架构图（headless claude 按 vendored archify 指引生成），产物经后端下发、前端沙箱渲染，让读者快速看懂项目核心组件、主链路与外部依赖。

## 规则

- 页签与手动触发：项目详情页页签序列固定为 …→测试回归→项目架构（key `architecture`、label「项目架构」）→会话接入，对全部注册项目一视同仁（无项目级特殊处理），未注册项目查询一律 404。页签内容由独立组件 ArchitectureTab 承载，按 `active` 门控——仅选中本页签才发起请求，未选中零请求。系统不得在页面加载、页签切换、daemon 启动等任何时机自动触发生成；从未生成时展示空态提示与「刷新架构图」按钮。
- 生成范式（两段式管线）：点击「刷新架构图」后 POST 只受理并立即返回，实际生成由 daemon 后台线程执行顺序两段式管线——阶段1 探索 run 读取证、阶段2 出图 run 产图，磁盘 `.fenix/architecture/evidence.md` 是两段间唯一交接面。每段各为一次性 headless claude：`claude -p <提示词> --permission-mode bypassPermissions`，cwd=项目根，`start_new_session=True`，env=`os.environ.copy()` 剔除 agent-run 专用三键（FENIX_RUN_PROJECT_ROOT / FENIX_RUN_WORKTREE / CLAUDE_CODE_ENABLE_TODO_TOOLS）。HTTP 线程不得同步等待生成（范式见 ADR-216）。生成完全在开发主链路之外：无 run 台账、无车道、无预算、无新增配置项，超时等均为模块常数。两段 prompt 均落在「小上下文 × 短输出」安全区、均不内嵌 vendored SKILL.md 全文（见 ADR-224）。
- 阶段1 探索 run：prompt 约 1KB、不注入 SKILL.md，按四项取证维度（组件/主链路/外部依赖/信任边界）只读取证写 evidence.md，marker 契约 `ARCHIFY_EVIDENCE_DONE`。判定链为「returncode==0 且 evidence.md 存在且非空」（不信 claude 自述），任一不满足直接判 failed 短路、不 spawn 阶段2；成功后 evidence.md 头部盖 `evidence-head: <HEAD sha> | <时间戳>` 指纹行。marker 命名保证 `ARCHIFY_EVIDENCE_DONE` 不以 `ARCHIFY_DONE` 开头，两段判定互不误中。
- evidence 取证复用与 HEAD 指纹失效：refresh 受理时 evidence.md 存在、非空、带指纹头且记录的 HEAD sha 与当前 repo HEAD 一致 → 跳过阶段1 直接进入阶段2（重试只付出图成本）；缺失、损坏、无指纹头、HEAD 不一致、detached HEAD、非 git 项目或取 HEAD 异常一律判不匹配、正常重探索（图不因复用而陈旧）。当前 HEAD 以 proot 为 cwd 执行 `git rev-parse HEAD` 取得（daemon 进程 cwd 与项目根不同，禁用进程 cwd 取 HEAD）。无 TTL、无定时失效，HEAD 一致即有效；daemon 侧不做阶段2 自动重试，用户再点刷新即等效触发 HEAD 命中跳段。
- archify 依赖保障（vendored 随库分发）：archify 以 vendored 整包随本仓库分发于 `vendor/archify/`——SKILL.md 与其指引引用的全部伴生文件（schemas/ examples/ references/ renderers/ bin/ scripts/ assets/ 等）必须整包在位，只交付路径引用不够；上游 LICENSE 与 THIRD_PARTY_NOTICES 随包保留，溯源（上游仓库/快照 commit/许可/剔除项）与升级方法见 `vendor/archify/VENDORED.md`，升级=手工整包替换并同步更新该文件，禁止只换 SKILL.md（指引与伴生文件版本耦合）。spawn 前校验包完整性：`vendor/archify/SKILL.md` 存在且非空；缺失或为空判 failed，错误信息注明 vendored 包缺件属部署损坏、提示对照 VENDORED.md 恢复，且 MUST NOT 触发任何安装动作。阶段2 prompt 以包根绝对路径引用 SKILL.md 与 evidence.md（不内嵌全文；指引中出现的相对路径均相对包根解析，`node bin/archify.mjs validate` 为本地执行、无网络依赖），不以「请使用 archify skill」等措辞隐含依赖环境已装 skill。生成链路零联网安装（含 `npx skills add`）、零用户环境依赖（不读不写 `~/.claude` 与 `$CLAUDE_CONFIG_DIR` 下任何路径），期间派生的唯一外部进程是 claude 本身（claude 进程 cwd=目标项目根，读 vendored 包走绝对路径）。
- 阶段2 出图 run 与分段写纪律：prompt 约 2KB，以绝对路径引用 SKILL.md 与 evidence.md，允许补充少量定向查证；prompt 显式要求候选 JSON 先写骨架再逐段 Edit 补全（分段小步写盘），禁止单次巨量 Write。产物判定沿用权威判定链（见下）。
- 图形态契约（约束落在提示词文本）：只保留 8–16 个核心组件；突出且仅突出一条主要路径；标注外部依赖与信任边界；辅助信息放说明卡片而非继续增加连线；节点与说明文字用中文。组件数机械校验只对「能提取到」的情况生效——提取到则越出 8–16 判 failed（错误信息含实际组件数与允许范围）；marker 缺失提取不到时记 `component_count: null` 放行，产物可用性优先于校验完备性。
- 产物判定权威链：进程退出码 → diagram.html 存在且非空 → 自包含 HTML 特征（起始 `<html` / `<!DOCTYPE html`）→ 组件数提取（stdout 末行 marker `ARCHIFY_DONE <组件数>`，缺失则从产物提取）。判定权威是产物实况，不采信 claude 自述（口径见 ADR-217）；任一必需环节不满足判 failed。
- 存储与单写者：产物按项目存于项目根 `.fenix/architecture/`（`diagram.html` + `status.json`，gitignored 运行时产物，目录按需创建），每次状态迁移 tmp+rename 原子写；dashboard 进程内 ArchitectureManager 持单飞锁与在飞进程句柄，是唯一写者。刷新即覆盖旧图，只保留最近一次，无历史版本。status.json 字段：`state` / `generated_at` / `started_at` / `error` / `duration_ms` / `component_count`，另加可选键 `stage`（向后兼容，读侧容忍缺键）。
- API 端点（mixin 形态，query 传 project）：`GET /api/architecture/status` 返回 state（`none|generating|ready|failed`）、generated_at、失败原因与 stage 等；`POST /api/architecture/refresh` 受理返回 200，在飞期间重复 POST 返回 409 语义（不产生第二个 claude 进程）；`GET /api/architecture/diagram` 以下发 `text/html` 返回产物字节。state=none 时 diagram 返回 404 结构化 JSON 错误，前端不渲染 iframe。
- 生命周期治理（无死态）：同一项目同时至多一个在飞生成（per-project 单飞）；分段硬超时——阶段1 探索 ≤720 秒、阶段2 出图 ≤1080 秒（总预算 1800 秒不变，模块常数），任一段到时以进程组方式击杀该段 claude 及其派生子进程并判 failed，每段独立 try/killpg/finish，错误信息注明所属阶段（「阶段1 探索超时」/「阶段2 出图超时」）；daemon 重启后 status.json 残留 generating 而内存无在飞进程时，读侧合成为 failed（生成被中断），不得永久停留 generating；failed 态展示错误信息且按钮恢复可点，重试受理即开始新一轮生成，旧失败原因被覆盖。
- 前端渲染：generating 期间以 3s 固定间隔轮询 status（活动门控内），刷新按钮置灰并提示生成中（`stage` 键为后端先行字段，前端暂不细分消费）；ready 后以 `<iframe sandbox="allow-scripts">` 渲染产物（sandbox 恰为 allow-scripts，不给 allow-same-origin，产物脚本与主站 cookie/DOM 隔离，见 ADR-218），同时展示生成时间等元信息，按钮可再次点击；容器用显式 flex 布局定高（`calc(100vh - 头部实测偏移px)` 加 minHeight 兜底），移动端按 useIsMobile 换用移动档常数，避免越界。

## 溯源

- 2026-10-04 add-project-architecture-tab（spec/archive/2026-10-04-add-project-architecture-tab） — 新建本能力：项目详情页新增「项目架构」页签，确立手动触发、一次性 headless claude + archify 生成、单飞/超时/重启残留合成三件套生命周期治理、`.fenix/architecture/` 产物存储与 3 端点下发、iframe 沙箱渲染契约
- 2026-10-04 fix-archify-vendored-injection（spec/archive/2026-10-04-fix-archify-vendored-injection） — 改写「archify skill 可用性保障」：废除运行时自动安装（`npx skills add` 限时 120s 及三探测函数），改为 vendored 整包随库分发（`vendor/archify/`，commit 4e03cd2f 先于本 SPEC 入库）+ SKILL.md 原文与包根绝对路径注入提示词，生成链路零联网安装、零用户环境依赖，缺件按部署损坏判失败；其余规则不变
- 2026-10-04 add-architecture-two-stage-generation（spec/archive/2026-10-04-add-architecture-two-stage-generation） — 生成编排从单体 claude -p 一次完成改写为探索/出图顺序两段式管线（evidence.md 磁盘唯一交接面、两段 prompt 不内嵌 SKILL.md 全文改包根绝对路径引用）、新增 evidence HEAD 指纹跳段复用与阶段1 判定链、超时 1800s 拆为探索 720s/出图 1080s 分段击杀、status.json 增可选 stage 键、候选 JSON 分段小步写纪律；产物权威判定链与其余生命周期治理不变
