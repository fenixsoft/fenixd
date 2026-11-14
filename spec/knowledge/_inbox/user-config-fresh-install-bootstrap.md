# 用户级配置全新安装自举（fresh-install config bootstrap）

## 背景

全新安装 fenixd 框架后进入 Dashboard 设置页「用户级」模式，页面提示
「用户级配置文件不存在，表单为默认值」。排查发现：安装链（install.sh /
install.ps1）只做依赖检查、skills 软链与 fenix-init 入 PATH；`fenix-init`
只生成项目级 `.fenix/config.yaml`；用户级 `~/.fenix/config.yaml` 此前唯一
创建入口是设置页手动保存（2026-09-02 add-hierarchical-config 的原始设计
即「不存在时提示保存后创建」），与项目级「init 即有文件」不对称。

## 结论（当前生效规则）

- install.sh / install.ps1 均含第 4 步「生成用户级默认配置」：从框架模板
  `.fenix/config.user.template.yaml` 生成 `~/.fenix/config.yaml`
  （Linux 权限 0600；PowerShell 侧 Copy-Item 失败降级 WARN 不阻断安装）。
- 幂等红线：目标文件已存在（或为符号链接）一律跳过，绝不覆盖——存量文件
  含 apikey 等用户数据。
- 模板只含注释文档、不固化任何默认值：未显式写出的键由框架代码默认值兜底，
  框架升级自动跟随新默认，不被安装时点的旧默认冻结；该文件 yaml 解析结果
  为 None，与「文件缺失按空 dict 兜底」的读取口径（`safe_load(...) or {}`）
  语义等价，对 daemon/设置页行为零影响，仅消除 raw_exists=False 提示。
- 新模板随仓库入库（.gitignore 白名单 `!.fenix/config.user.template.yaml`），
  模板内引导用户参考项目级模板 `.fenix/config.template.yaml` 与
  docs/help/09-config.md 查阅全键清单。

## 证据

- 提示文案出处：`core/dashboard/static/src/pages/settings/index.tsx:601`
  （`config.raw_exists` 为 false 时渲染）；raw_exists 判定：
  `core/dashboard/data/config_admin.py` read_config（scope="user" 读
  `USER_CONFIG_PATH`，文件缺失返回 raw_exists=False）。
- 隔离 HOME 实测（`HOME=<隔离目录> bash install.sh`）：文件生成、内容与
  模板逐字节一致、权限 600；二次追加 marker 后重跑安装器，marker 保留
  （不覆盖）；本机真实 `~/.fenix/config.yaml` md5 前后一致（存量保护）。
- `ca.read_config(_, scope='user')` 实链路：raw_exists=True、error=None。
- Windows 侧 pwsh 不可用未本机验证，已登记
  `tests/integration/windows/g1_full_parity_checklist.md` G1-01b「待复验」；
  Linux e2e 集成（tests/integration/e2e.sh）已加生成断言。
