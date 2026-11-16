# Proposal: fix-windows-service-userprofile

## Why

install.md 全新部署承诺「设置页不再提示配置文件不存在」，但 Windows 服务化部署（NSSM、ObjectName=LocalSystem）中服务进程的 `USERPROFILE` 由 SCM 提供为 `C:\WINDOWS\system32\config\systemprofile`，`core/config.py:20` 的 `USER_CONFIG_DIR = Path.home() / ".fenix"` 在 import 期按错误 home 绑定，导致用户级配置实际存在却报 `raw_exists=False`、设置页误显「用户级配置文件不存在，表单为默认值」。真机（Windows 11，fenixd v0.1.5）已复现并验证：手工向服务注册表 `AppEnvironmentExtra` 注入 `USERPROFILE` 后提示消失。当前该注入只是 install.md §8 的"建议"，`install_unit` 机制层（REG_MULTI_SZ read-modify-write 合并 + env_defect 自检，fix-spawn-attribution-hardening 交付）已就绪但默认不注入——全新部署仍会踩坑，须把正确性下沉到框架默认值。

## What Changes

- `install_unit`（core/platform/win32.py:1706）服务安装时**默认注入调用者 `USERPROFILE`**（读现有合并语义，同键覆盖/异键保留；显式 `env=` 传参仍可覆盖默认行为），LocalSystem 承载的服务因此解析到真实用户 profile；不再依赖手工注册表步骤。
- `USER_CONFIG_DIR`（core/config.py:20）支持 `FENIX_HOME` 环境变量覆盖（缺省仍 `Path.home() / ".fenix"`）——服务环境漂移时的防御性逃生口；门面绑定（core/dashboard/data/__init__.py:124 `USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"`）单源派生自动跟随，不改绑定结构。
- 设置页配置状态提示（core/dashboard/static/src/pages/settings/index.tsx:612-617）在 `!raw_exists` 时**附带实际解析路径**（`/api/config` payload `path` 字段——评审实测：config_admin.py `read_config` L895 payload 现无该键，须后端为 user/project 两 scope 补齐产出，原「已产出」表述系误引 L3382/3396 的 sync 错误返回字段），漂移一眼可见。
- docs/install.md §8 服务注册：USERPROFILE 注入从"建议"升为**必做步骤**表述，并注明 `install_unit` 已默认注入、存量手工部署的补救命令；G1 清单 G1-01b（用户级配置自举）随 Windows 过机复验回填结论。

## Capabilities

- **Modified Capabilities**:
  - `windows-native-support` — 「服务环境注入与自检」要求变更：`install_unit` 默认 env 增加调用者 `USERPROFILE` 注入（现行为：仅显式 `env=` 才注入）；env_defect 自检语义不变。存量 spec 快照见 spec/changes/fix-spawn-attribution-hardening/specs/windows-native-support/spec.md（2026-11-16 最新）。
- **Modified Capabilities**:
  - `hierarchical-config` — 分级配置路径解析与环境覆盖：`FENIX_HOME` 覆盖 `USER_CONFIG_DIR` 单源（core/config.py）、门面派生跟随、设置页提示携带实际解析路径（`path` 字段为该能力既有「Dashboard 配置 API 作用域化」Requirement 的 GET 返回面扩展）。规则真相源对应 spec/knowledge/domains/provider-models/hierarchical-config.md。**存量能力快照已在档**：spec/archive/2026-09-02-add-hierarchical-config/specs/hierarchical-config/spec.md（7 条 Requirement 在册）；本变更向该能力追加两条新 Requirement（specs/hierarchical-config/spec.md 的 ADDED 条目），不改动存量条目（评审修补：原「New Capabilities／此前无 SPEC 能力快照、首次成文」表述与在档快照不符）。

## Impact

- **代码面**：core/platform/win32.py（install_unit 默认 env）、core/config.py（FENIX_HOME 读取）、core/dashboard/data/config_admin.py（read_config/read_effective_config 补 `path` 字段）、core/dashboard/static/src/pages/settings/index.tsx（提示文案 + dist 重建）；无接口签名破坏（`install_unit(root, env=None)` 签名不变，env=None 语义从"不注入"变"注入默认集"）。
- **行为面**：Windows 服务化全新部署/幂等重装后 LocalSystem 服务解析正确 profile；既有手工注入的服务重跑安装不受影响（合并语义保留既有条目）。
- **平台面**：Linux `install_unit`（systemd unit）不受影响；`USER_CONFIG_DIR` 覆盖逻辑双平台生效（POSIX 下 `Path.home()` 漂移同样受益）。
- **验证面**：Linux 逻辑测试 + Windows 过机复验（win-vm：服务环境注入断言 + 用户级配置自举 G1-01b 回填）。
- **知识面**：排查结论已投递 spec/knowledge/_inbox/windows-service-userprofile-drift.md，归档时随蒸馏管线并入 windows-native-support 与 hierarchical-config 页。
