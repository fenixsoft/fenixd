# Design: fix-push-credential-env-and-retry-rearm

## Context

推送车道（done→pushed 自动推送）在 2026-11-09 cloud-phone 事故中暴露两个独立单点：

1. **凭证环境单腿**：`core/pm_engine/engine.py` 的 `_git_push_ref` 以 `subprocess.run(["git","push","origin",ref], cwd=…)` 裸继承 daemon 进程环境；systemd 承载的 daemon env 无 `HOME`（实证 `/proc/<pid>/environ` 缺键、子进程 `git config --global` 报 `fatal: $HOME not set`）→ `~/.git-credentials`/`~/.gitconfig` 均不可达，凭证只剩 remote URL 内嵌 token 一条腿；token 二次失效（`Authentication failed`）后全部推送瘫痪。承载层已有成熟范式：`core/systemd_hosting.py` 的 PATH 基线并集（`PATH_BASELINE_DIRS` 常量、`capture_env_candidate` 捕获补齐留痕、`render_project_unit` unit 模板 `Environment=PATH` 保底行、迁移摘要卫生结论），HOME 可并列套用。
2. **退避无消费者**：`_handle_push_failure` 失败时把 `_push_attempts` / `_push_backoff_next_retry_at`（专用字段 + error 文本双活）写盘，`_is_push_backoffed`（`core/pm_engine/reporting.py`）按 `next_retry > now` 判定；但到期重试的消费通道不存在——`core/event_bus.py` 的 `_recover_one` 状态分支仅覆盖 drafted/reviewing/implemented/testing/ready/bug-found/verified，**无 done 分支**；重试唯一触发面是 done 转换事件与 `.fenix/approve_push_request.json` 人工信号。退避字段虽持久化（跨重启存活），却无人拾取 → spec 永久滞留 done。

既有知识约束：`scheduled-reverify-restart-durability` 已确立「未来时点动作必须 STATE 字段持久化 + 周期扫描兜底消费，MUST NOT 依赖内存定时器（内存定时器只是准点主通道）」；`push-ref-hygiene` 规定退避级数 `pm.push.retry_backoff_seconds` 默认 [300,900]、`pm.push.max_retries` 默认 3、耗尽后停自动重试并发 push_failed 困境信号——本 SPEC 全部保持不变。

## Goals / Non-Goals

**Goals:**

- git 子进程环境确定性：推送不再依赖 daemon 进程恰好带 HOME，凭证双腿（URL 内嵌 token + 凭证文件）任一可用即可推送。
- 承载层从出生即带 HOME：env 候选稿 HOME 基线补齐、unit 模板 HOME 保底行，存量坏环境由启动自检告警暴露。
- done 态退避到期后由周期扫描自动续推，跨重启存活；耗尽升级（push_failed）后维持人工收敛，不自动死循环。

**Non-Goals:**

- 不改退避级数、重试上限、push_failed 升级语义（push-ref-hygiene 不动）。
- 不做凭证的自动续期/轮换/token 管理（运维动作，文档登记即可）。
- 不改 PATH 基线既有行为（HOME 基线为并列新增，PATH 产物逐字节不变）。
- 不引入推送专用的内存定时器/新线程（续推粒度＝扫描周期，最坏延迟一个 poll 周期，可接受）。
- 不处理 feature 分支推送语义（仍为 best-effort 留痕）。

## Decisions

- **D1 HOME 单源解析器独立成模块（新文件 `core/git_env.py`）**：解析序 daemon env `HOME` → `pwd.getpwuid(os.getuid()).pw_dir` → 配置覆盖 `pm.push.credential_home`（可选）；产出①解析后 HOME、②git 子进程 env（含 HOME 注入）、③credential helper 参数。理由：`_git_push_ref` 与启动自检两个消费点共用一套判定，避免双源漂移（对齐 scheduled-reverify 的「单点定义、禁裸串」纪律）；独立模块便于无 git 环境的单元测试。
- **D2 凭证文件兜底走显式 `-c credential.helper`**：git 命令行追加 `-c credential.helper=store --file=<abs>`（配置 `pm.push.credential_file` 可覆盖路径，缺省＝解析 HOME 下 `.git-credentials`；文件不存在则不追加该参数，避免 git 静默建空文件造成「有凭证」假象）。理由：不依赖 daemon env 是否带 HOME，runtime 层自洽；URL 内嵌 token 与 helper 双腿并存时 git 先查 helper 再用 URL 凭证，行为兼容。
- **D3 承载层 HOME 基线照抄 PATH 范式**：`capture_env_candidate` 捕获时检查候选稿是否含非空 `HOME`，缺失则以解析器单源补 `HOME=<resolved>` 并加注释留痕（同 PATH 追加留痕格式）；`render_project_unit` 增加 `Environment=HOME=<resolved>` 保底行（env 文件在场且含 HOME 时照常覆盖，systemd 加载顺序语义不变）；迁移摘要输出 HOME 卫生结论行。理由：与 systemd-env-path-hygiene 同构，评审/测试心智零增量。
- **D4 续推消费通道＝`_recover_one` done 分支 + 周期扫描**：分支逻辑——status==done 且**未被** `_is_push_backoffed` 拦截且 `_get_push_retry_count < max_retries` 且未被 push_failed 升级终局化（耗尽标记在 → 跳过）→ 经既有 admin executor 非阻塞投递 `pm_engine.approve_push(spec)`（复用单飞锁、pushed 幂等跳过、SHA 去重；同构 `_check_approve_push_requests` 的 `_submit_approve_push` 投递形态）。退避期内记 debug 级跳过（每轮扫描一条，退避窗分钟级，噪音可控）。理由：周期扫描是既有跨重启存活机制，零新增定时器；done 分支天然覆盖「daemon 停机期间错过推送时机」与「退避到期续推」两种形态；executor 投递避免 120s git 超时阻塞扫描主循环（与推送车道既有非阻塞纪律一致）。
- **D5 启动自检探测放 daemon 启动自检链（`fenixd.py`）**：fail-open 探测三项——解析 HOME 是否为存在目录、凭证文件（解析后路径）是否在场、任一 remote URL 是否含内嵌凭证；双腿皆缺发 WARNING 自检告警（不派发、不阻断启动）。理由：与 dispatch-precheck/PATH 卫生自检同链路；探测纯本地（不做 ls-remote 网络探测，避免启动期网络抖动误报）。

## Risks / Trade-offs

- [续推最坏延迟一个扫描周期] → 退避窗（≥300s）远大于扫描周期（分钟级），语义上「准点」无承诺必要；design 明示粒度即为扫描周期。
- [`-c credential.helper` 对非 store 类既有 helper 的叠加效应] → 追加参数仅在 `pm.push.credential_file` 解析路径存在时生效；配置显式置空字符串可关断兜底（文档登记）；既有项目 helper 行为不变（无文件 → 不追加）。
- [done 分支误推已人工收口的 spec] → 四重门：status==done（pushed 不进分支）+ 退避门 + 重试计数门 + 耗尽升级门；approve_push 内部再有单飞锁与 pushed 幂等跳过兜底。
- [pwd 解析在极端容器环境不可用] → 解析器逐级 fail-open，三级皆空时不注入 HOME（行为回退现状）并发自检告警，不抛异常中断推送。
- [HOME 注入改变 git 对 `~/.gitconfig` 的可见性（原先不可见）] → 这是修复目标本身（凭证文件可达）；`.gitconfig` 中的 alias/credential 配置恢复生效属预期行为，风险登记至 design 与 help 文档。

## Migration Plan

存量项目零迁移：daemon 重启后新代码生效——unit 保底行仅在下次迁移/重装 unit 时写入（无害），runtime 层 env 注入即时生效；启动自检首轮即对无 HOME 环境发告警提示补 env。回滚＝回退代码（无 STATE 结构变更，退避字段既有格式不变）。

## Open Questions

（无——两项修复的机制、锚点与既有纪律均已核实于代码与知识库。）
