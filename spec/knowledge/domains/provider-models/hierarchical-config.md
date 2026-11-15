<!-- knowledge: capability=hierarchical-config rev=3 sources=spec/archive/2026-09-02-add-hierarchical-config,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md,spec/knowledge/_inbox/done/user-config-fresh-install-bootstrap.md -->

# 分级配置（用户级 + 项目级深度合并）

配置分用户级与项目级两层，深度合并出有效配置；daemon 与 Dashboard 读写同走有效配置口径。

## 规则

- 两层配置路径：用户级 `~/.fenix/config.yaml`，项目级 `<project_root>/.fenix/config.yaml`，文件同名、作用域由所在目录决定；用户级存跨项目通用设置，项目级覆盖项目差异。
- 深度合并语义：以用户级为基础、项目级为覆盖——字典逐层递归合并（项目级优先），标量与列表由项目级整体替换（不做元素级合并）；项目级未显式定义的键继承用户级。
- `resolve_config(project_root)` 为有效配置统一入口：读取两层配置（任一或全部缺失均允许，缺失按空 dict 兜底），深度合并后返回；有效配置缺 `project.name` 时以项目根目录名补齐；对已存在键执行既有值级校验，顶层必填键缺失不强制报错（由消费方以默认值兜底）。
- daemon 启动使用 `resolve_config(PROJECT_ROOT)` 加载有效配置；两层配置文件均缺失时仍正常启动运行。
- Dashboard `/api/config` 双作用域：无 `project` 参数读写用户级配置；带 `project` 参数写项目级、读返回有效合并视图，并附 `sources`（标注每个受管键 `llm` / `agents.models` / `agents.max_concurrent` / `gates.approve_mode` 来自用户级还是项目级）、`scope`（user/project）与 `raw_exists`（当前作用域文件是否存在）。
- 前端配置页双模式渲染：未选项目为用户模式（标题标注「用户级」，保存写入用户级文件；文件缺失时提示「用户级配置文件不存在，表单为默认值」，保存后创建文件）；选项目为项目模式（显示有效合并值，来自用户级的受管键旁标注「继承自用户级」，保存写入项目级文件并提示路径）。
- 全新安装自举：install.sh 与 install.ps1 均含「生成用户级默认配置」步骤，从框架模板 `.fenix/config.user.template.yaml` 生成 `~/.fenix/config.yaml`（Linux 侧生成后权限 0600）；项目级配置另由 `fenix-init` 生成，两层在安装/初始化后即有文件。自举后设置页用户模式不再出现缺文件提示，该提示仅在文件被移除等场景兜底出现。
- 自举幂等红线：目标文件已存在（含符号链接形态）一律跳过、绝不覆盖——存量文件含 apikey 等用户数据。
- 模板零默认值语义：用户级模板只含注释文档、不固化任何默认值，未显式写出的键由框架代码默认值兜底，框架升级自动跟随新默认、不被安装时点的旧默认冻结；模板 yaml 解析结果为 None，与「文件缺失按空 dict 兜底」的读取口径语义等价，对 daemon 与设置页行为零影响。模板缺失时 Linux 侧跳过生成并提示经设置页保存创建，Windows 侧按部署面完整性硬失败处理；Windows 侧复制异常降级 WARN 不阻断安装。
- 用户级模板随仓库分发（`.gitignore` 白名单放行），模板内引导查阅项目级模板 `.fenix/config.template.yaml` 与 `docs/help/09-config.md` 获取全键清单。
- Registry 扫描与项目注册仅以 `STATE.md` 存在为识别条件，不要求 `.fenix/config.yaml` 存在——配置完全继承用户级的项目同样可被监控与注册。
- 排查 enabled/开关类配置问题两处物理文件都要看：用户级 `~/.fenix/config.yaml`（设置页用户模式写此处）与项目级 `.fenix/config.yaml`（daemon 经 `resolve_config` 直读合并结果）——只在设置页改过用户级、或只手改过项目级，都会造成「界面显示与 daemon 实际生效不一致」的盲区；对照 `/api/config` 响应的 `sources` 标注定位键的真实来源层。

## 溯源

- 史前复原 — 迁移期已存在的基线：配置按全局与项目两级深度合并（resolve_config）出有效配置；可选字段不强制存在校验；daemon 与 Dashboard 读写同走有效配置口径
- 2026-09-02 add-hierarchical-config（spec/archive/2026-09-02-add-hierarchical-config） — 固化两层路径与深度合并语义、resolve_config 兜底与 project.name 补齐、Dashboard 双作用域读写与继承标注、注册识别放宽为仅 STATE.md
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠排查纪律：enabled/开关类问题两处配置物理文件都要看，以 /api/config 的 sources 标注定位键来源层
- 2026-11-16 user-config-fresh-install-bootstrap（spec/knowledge/_inbox/done/user-config-fresh-install-bootstrap.md） — 折叠全新安装自举：安装链幂等生成用户级默认配置（不覆盖存量、模板零默认值语义、Windows 模板缺失按完整性硬失败），缺文件提示转为兜底面
