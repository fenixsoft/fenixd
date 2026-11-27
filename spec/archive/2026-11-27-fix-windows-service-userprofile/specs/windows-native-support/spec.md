# spec delta: fix-windows-service-userprofile

## MODIFIED Requirements

### Requirement: daemon 服务环境注入与自检

`install_unit` MUST 支持 `env` 参数（`dict`）以**注册表 REG_MULTI_SZ 形态**写入
`AppEnvironmentExtra`（元素边界确定，禁 nssm set 多参数引号坑形态），写入 MUST 为
read-modify-write 合并（同键 K=V 覆盖、异键保留——install.md §8 手工配置的服务
PATH 最小集等既有条目不得被整值替换清除）；调用未显式传 `env` 时 MUST 默认并入
调用者 `USERPROFILE`（安装时刻解析的真实用户 profile；**仅限服务账户为 LocalSystem
的承载形态**——新装服务 NSSM 默认即 LocalSystem 恒注入；已装服务经服务账户配置
（`sc qc` 的 ObjectName/StartName）判为非 LocalSystem 专用账户时 MUST 跳过默认
注入，该形态 SCM 已为账户提供真实 profile，注入安装者 profile 反成覆写错误值；
显式 `env` 中同名键以显式值优先）——LocalSystem 承载的服务进程因此解析到真实用户 profile 而非
`C:\WINDOWS\system32\config\systemprofile`，用户级配置（`%USERPROFILE%\.fenix\config.yaml`）
不再因服务环境漂移而误报不存在；幂等重跑与安装完成路径 MUST 做服务环境
自检——以服务 PATH 视角解析 claude/git，解析失败在返回 JSON 报
`env_defect`（含缺失目录指引），不等派发烧三轮才暴露。

#### Scenario: env 注入一次配对

- **WHEN** `install_unit(root, env={"PATH": "<最小集>", "DSH_HOME": "..."})`
- **THEN** 服务注册表 Parameters/AppEnvironmentExtra 为 REG_MULTI_SZ 多元素，
  nssm restart 后服务内可见

#### Scenario: 缺省调用注入调用者 USERPROFILE

- **WHEN** `install_unit(root)`（未传 `env`），注册表已有手工配置条目（如服务 PATH 最小集）
- **THEN** AppEnvironmentExtra 为合并结果：含 `USERPROFILE=<安装调用者真实profile>`
  且既有条目保留（不整值替换）；nssm restart 后服务内 `Path.home()` 解析为该 profile，
  `%USERPROFILE%\.fenix\config.yaml` 可见

#### Scenario: 显式 env 覆盖默认注入

- **WHEN** `install_unit(root, env={"USERPROFILE": "C:\custom\profile"})`
- **THEN** 注册表 USERPROFILE 为 `C:\custom\profile`（显式值优先于默认注入）

#### Scenario: 非 LocalSystem 专用账户服务跳过默认注入

- **WHEN** `install_unit(root)`（未传 `env`），已装服务的服务账户
  （ObjectName/StartName）为非 LocalSystem 专用账户
- **THEN** 不注入默认 `USERPROFILE`（SCM 已为该账户提供真实 profile），既有
  AppEnvironmentExtra 条目不受影响

#### Scenario: 服务环境缺陷提前暴露

- **WHEN** 幂等重跑时服务 PATH 无法解析 git 或 claude
- **THEN** 返回 JSON 含 `env_defect` 与缺失可执行指引
