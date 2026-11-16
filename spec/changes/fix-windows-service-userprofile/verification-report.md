# 验证报告：fix-windows-service-userprofile

> ⚠️ 本报告由框架于 2026-11-16T12:23:15Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-16T12:23:14.533947+00:00+run-result@mtime1794831794592313589

## 结论：✅ 通过（verified）

**状态：verified — 13/13 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 13/13 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 14.27M |
| 本链增量 Token（输出） | 0.13M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| install-unit-default-userprofile-tests-green | install_unit 服务环境注入测试面全绿（tasks 1.2/1.3；spec delta windows-native-support「缺省调用注入调用者 USERPROFILE」「显式 env 覆盖默认注入」「非 LocalSystem 专用账户服务跳过默认注入」：tests/test_install_unit_env.py TestDefaultUserprofileInjection 六用例 + REG_MULTI_SZ read-modify-write 合并/env_defect 自检语义不变回归（TestInstallUnitEnvInjection/TestServiceEnvDefects）全部通过。出处：core/platform/win32.py:1652-1940（_SYSTEMPROFILE_SUFFIX/_resolve_caller_userprofile/_default_service_env/install_unit effective_env）。 | pass | 0/8 | - |
| install-unit-default-injection-decision-probe | install_unit 缺省 USERPROFILE 注入决策面独立探针（spec delta windows-native-support MODIFIED Requirement 的核心判据，独立于实现者自测的证据面）：systemprofile 后缀形态判定（正斜杠/盘符不敏感、真实用户 profile 不误判）、安装调用者 profile 双读锚定（env 侧优先、双读皆 systemprofile → None）、新装路径恒注入、显式 env 同名键显式优先（守卫不约束显式传入）、非 LocalSystem 专用账户守卫跳过并附 userprofile_skip 提示、LocalSystem 账户等价形态判定。出处：core/platform/win32.py:1652-1782（_is_systemprofile_path/_resolve_caller_userprofile/_service_object_name/_is_localsystem_account/_default_service_env）。 | pass | 0/11 | - |
| cfg-fenix-home-resolution-tests-green | FENIX_HOME 覆盖 USER_CONFIG_DIR 单源测试面全绿（tasks 2.1/2.2；spec delta hierarchical-config「FENIX_HOME 设置时覆盖解析」「未设 FENIX_HOME 时行为不变」「服务环境漂移逃生口」：tests/test_config_user_dir_env.py 三用例——home 替代语义解析、门面派生跟随、FENIX_HOME 严格优先于 USERPROFILE——全部通过，子进程独立解释器隔离防串扰）。出处：core/config.py:30-32、core/dashboard/data/__init__.py:124。 | pass | 0/5 | - |
| cfg-fenix-home-single-source-probe | FENIX_HOME 单源纪律探针（tasks 2.1/2.3；spec delta hierarchical-config ADDED Requirement「全库用户级配置目录消费 MUST 经该单源，禁止旁路 Path.home() 重复推导」）：子进程独立解释器实测 FENIX_HOME 设置态 USER_CONFIG_DIR=Path(FENIX_HOME)/.fenix 且门面 USER_CONFIG_PATH 派生跟随、未设态保持 Path.home()/.fenix 现状逐字节一致；全库 Path.home() 与 .fenix 同行拼接旁路 grep 零命中（core/config.py 单源除外）。出处：core/config.py:30-32、core/dashboard/data/__init__.py:124。 | pass | 0/8 | - |
| docs-install-userprofile-mandatory | install.md 文档升格核验（tasks 4.1/4.2）：§8 服务注册含「缺省调用 install_unit 已默认注入调用者 USERPROFILE」必做表述与 userprofile_skip 返回字段说明、手工 nssm 路径含 Set-ItemProperty 注入命令块（USERPROFILE 必做项）、存量部署补救一键命令、故障排查段含「设置页提示配置文件不存在 → 解析路径 → USERPROFILE 漂移/FENIX_HOME 逃生口」条目。出处：docs/install.md:840-891、1025。 | pass | 0/8 | - |
| g1-01b-backfill-recorded | G1 清单 G1-01b（用户级配置自举）复验结论已回填（task 5.3）：陈旧占位「待下次 dockur 过机时填写」已被 2026-11-16 dockur 过机复验 PASS 记录替换（缺失态生成/幂等不覆盖/服务化自举闭环留档）——tasks 5.1/5.2 的 win-vm 实测通道证据以本在档记录为验证面（本轮验证在 Linux 宿主，不再重跑 Guest 内服务安装实况；通道复验结论已随实现 run 落档）。出处：tests/integration/windows/g1_full_parity_checklist.md:10。 | pass | 0/3 | - |
| fixture-provision-cfgless-project | 自注册无 config.yaml 探针夹具项目（web/api 缺失态场景的前置供给）：/tmp/fenixd-cfgless-fixture 仅含 .fenix/STATE.md 骨架（无 .fenix/config.yaml），以 fixture=True 经 Registry.add_project 登记进共享注册表 ~/.config/fenixd/dashboard.yaml（ADR-163 夹具治理：打标对场景断言零影响、缺省聚合降噪）。出处：core/dashboard/registry.py:41（DEFAULT_CONFIG）、registry.py:476（add_project fixture 标记）；夹具规则见本项目验证提示词 fixture=True 硬约束。 | pass | 0/6 | - |
| api-config-user-scope-path-field | /api/config 用户级 scope payload 携带实际解析路径 path 字段（tasks 3.1；spec delta hierarchical-config「用户级配置目录 FENIX_HOME 覆盖单源」Scenario 的 API 面与「未设 FENIX_HOME 时行为不变」）：验证实例 HOME=/root 无 FENIX_HOME 预设，path 应为 /root/.fenix/config.yaml（=str(USER_CONFIG_PATH)），raw_exists 反映真实存在性（本机用户级配置在场=true），sources 作用域标注 user。出处：core/dashboard/routes/base.py:643（GET 路由）、core/dashboard/data/config_admin.py:932（read_config path 覆写）、core/dashboard/data/__init__.py:124（USER_CONFIG_PATH）。 | pass | 0/5 | - |
| api-config-project-scope-path-field | /api/config 项目级 scope payload 携带项目配置解析路径 path 字段（tasks 3.1 project scope，存在态）：project=fenixd → /root/fenixd/.fenix/config.yaml、raw_exists=true。出处：core/dashboard/routes/base.py:643、core/dashboard/data/config_admin.py:1129（read_effective_config path 覆写）。 | pass | 0/4 | - |
| web-settings-user-mode-normal-render | 回归点：设置页默认用户级正常渲染——本 SPEC 提示文案改动（!raw_exists 追加解析路径）不破坏既有用户模式：/root/.fenix/config.yaml 在场 → 缺失提示不出现、页面结构与面板正常挂载、零 console 错误。出处：core/dashboard/static/src/pages/settings/index.tsx:609-625（条件渲染：仅 !raw_exists 才出提示）、app.tsx:193。 | pass | 0/5 | - |
| api-config-project-scope-missing-path-field | 无 config.yaml 夹具项目缺失态 API 契约（tasks 3.1；spec delta hierarchical-config「服务环境漂移逃生口」的 raw_exists 真实性面）：GET /api/config?project=fenixd-cfgless-fixture 返回 200、raw_exists=false 且 path=/tmp/fenixd-cfgless-fixture/.fenix/config.yaml——缺失早退路径同样携带 path（设置页提示的数据源）。出处：core/dashboard/data/config_admin.py:886-890（_default_echo_view path 缺省）、932（缺失早退前覆写）、1129。 | pass | 0/4 | - |
| web-settings-project-missing-hint-shows-path | 设置页项目级缺失提示附带实际解析路径（tasks 3.2；spec delta hierarchical-config「项目级缺失提示含路径」）：深链 /#/settings?project=fenixd-cfgless-fixture 预选项目级作用域（顺带回归首屏深链预选 behavior），无 config.yaml 夹具项目触发「项目尚无配置文件，表单为默认值」提示且附「（解析路径：/tmp/fenixd-cfgless-fixture/.fenix/config.yaml）」。出处：路由 core/dashboard/static/config/config.ts:15（hash history）、core/dashboard/static/src/app.tsx:193（/settings）；深链读侧 core/dashboard/static/src/pages/settings/index.tsx:108（initialScopeFromUrl）、提示渲染 index.tsx:616-622。 | pass | 0/5 | - |
| web-settings-scope-switch-via-select | 设置页作用域下拉交互切换到无 config.yaml 夹具项目，缺失提示带路径（tasks 3.2 交互链路；spec delta hierarchical-config「项目级缺失提示含路径」交互形态）：默认用户级 → 顶栏作用域 Select 展开 → 选「项目级：fenixd-cfgless-fixture」（未脏不弹丢弃确认，settings/index.tsx:222-226 判脏前置）→ 项目级缺失提示与解析路径可见。出处：作用域 Select core/dashboard/static/src/pages/settings/index.tsx:494-514（PageTitleBar filters 槽）、PageTitleBar.tsx:244（filters testid）、提示 index.tsx:616-622、路由 config.ts:15。 | pass | 0/6 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

