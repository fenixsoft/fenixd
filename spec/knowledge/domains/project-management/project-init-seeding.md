# 项目初始化骨架播种

<!-- knowledge: capability=project-init-seeding rev=2
     sources=spec/changes/add-onboarding-init-setup-guidance -->

`fenix-init` 在目标目录生成使用 fenixd 所需的工程骨架，并对其自身初始化产物自举（gitignore 覆盖 + 白名单文件入库）。

## 规则

- 用法：`fenix-init [DIR] [--name NAME] [--type web|cli|library|api]`；`--ensure-gitignore` 模式仅幂等补 `.gitignore` 规则，不做其他初始化；对已初始化项目重跑整体幂等，不重复报错。
- 生成骨架：`.fenix/`（`config.yaml` 由 `config.template.yaml` 渲染、状态文件 `STATE.md`、`PROJECT_LOG.md`、运行时目录、指向框架根的软链接）、`spec/{changes,specs}/` 与 `spec/archive/`、`.claude/agents/`（软链 `implementer.md`/`verifier.md`）与 `.claude/worktrees/`。
- 框架根目录定位：脚本路径经 `.resolve()` 跟随软链接解析到真实安装位置（`FENIXD_HOME`）；状态与日志文件由 `templates/` 下模板播种。
- gitignore 保障（幂等确保，判据取关键规则行、已在场即跳过不重复）：模板覆盖 `.fenix/*`（用 `/*` 而非整目录排除，以便 `!` 规则放行其下入库文件）、`.claude/worktrees/` 与 `.claude/agents/`——`.claude/agents/` 为框架播种运行时产物目录，预防性 ignore（新模板项目 `git status` 不再视其下文件为 untracked）；规则不影响已被用户手工跟踪的文件（gitignore 只作用于 untracked）。
- gitignore 追加块（规则行 + 成因注释）以 `templates/gitignore-fenix.txt` 为唯一文本来源，从中按规则行整行锚定抽取；模板侧（新项目）与 `--ensure-gitignore` 侧（既有项目）同一段实现产出，禁止两处文本漂移；模板被改坏（规则行缺席）时退化为裸规则行，不丢功能。
- 白名单文件自举：gitignore `!` 规则放行的 `.fenix/todo.md` 与 `.fenix/verify.yaml`（放行即声明入库意图）在骨架写入完成后自动 `git add`——仅 staged、MUST NOT 自动 commit（提交时机留给用户）；只 add 白名单文件离散路径，MUST NOT `git add .`（骨架生成时项目里可能已有用户未跟踪文件，批量 add 会替用户做出入库决定）。
- 白名单逐文件存在性守卫：`todo.md` 非 init 播种物（由自省/进化车道后续创建），当期不存在时跳过该文件且不因 pathspec 缺失报错，其在场时（如后续重跑）一并入库；unborn 分支（零提交史）git add 正常生效，无需特殊处理；非 git 仓库跳过 git add 并输出「白名单文件待 `git init` 后手工入库」提示，骨架照常生成。
- 配置模板注释按 `agent.harness` 选型分形态描述无分配时的默认行为：claude（缺省）=各 Agent 继承 Claude CLI 会话环境（环境变量/登录档）默认模型，框架不做独立分配；dsh=无分配回落 dsh profile 默认档（对称回落），该回落落地前注释用条件式表述（「将随对称回落闭环落地生效」），不得断言当下不存在的行为；并说明显式分配（provider+model）是获得确定模型与 failover 的建议路径。注释不得出现「默认环境变量模型」这类对两形态都不准确的表述；其余配置注释保持不动（控制模板 diff 面积），渲染产物 YAML 必须可正常解析。

## 代码锚点

- 主实现：`fenix-init`（`git_add_whitelist_files` 白名单自举 / `append_gitignore` 幂等补规则 / `render_config` 模板渲染）
- 模板：`templates/gitignore-fenix.txt`（gitignore 追加块唯一文本来源）、`.fenix/config.template.yaml`
- 守卫测试：`tests/test_init_self_bootstrap.py`

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
- 2026-11-08 add-onboarding-init-setup-guidance（spec/changes/add-onboarding-init-setup-guidance） — 新增初始化产物自举：白名单文件 staged 自动入库（离散路径、不 commit、逐文件存在性守卫、非 git 跳过提示）、gitignore 模板补 `.claude/agents/` 预防性 ignore 与 `--ensure-gitignore` 幂等补齐（追加块模板单源）、配置模板注释按 harness 分形态改写（废除「默认环境变量模型」误导表述）
