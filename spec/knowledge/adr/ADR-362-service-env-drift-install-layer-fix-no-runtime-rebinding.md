# ADR-362：服务环境漂移在安装/部署环境层修复——缺省注入下沉机制层，不做运行时重绑定

date: 2026-11-16
status: accepted

## Context

Windows 服务化承载（NSSM + LocalSystem）下，SCM 为服务进程提供的 `USERPROFILE` 恒为 `C:\WINDOWS\system32\config\systemprofile`；`USER_CONFIG_DIR` 在 import 期按进程 home 一次性绑定后，用户级配置实际存在却被 `/api/config` 报 `raw_exists=False`，设置页误显「用户级配置文件不存在」（v0.1.5 真机复现）。机制层（`install_unit` 的 REG_MULTI_SZ read-modify-write 合并写 `AppEnvironmentExtra` + env_defect 自检）已就绪，但 `env=None` 时什么都不注入——正确性此前只由 install.md §8 的建议性手工步骤承载，调用纪律散（手工 nssm 与 `pal.install_unit` 两态并存），全新部署必然踩坑。另一侧，配置目录解析若改为运行时惰性重绑定，要动门面绑定结构（六个 import 后取值/派生消费点），且服务环境在进程生命周期内不变，惰性化无真实需求。

## Decision

- 服务承载的环境正确性收口在**安装/部署环境层**，进程启动前定形：`install_unit` 未显式传 `env` 时缺省并入安装调用者 `USERPROFILE`——默认值是唯一能让脚本、agent 代部署、手工全部部署路径同时正确的收口点，文档纪律不作正确性唯一承载。
- 缺省注入只修**确定性语义错误**：仅 LocalSystem 承载形态注入（新装 NSSM 服务默认 LocalSystem 恒注入；已装服务按服务账户 `sc qc` ObjectName 判定，专用账户形态 SCM 已为账户提供真实 profile，注入安装者 profile 反成覆写错误值，跳过并附 `userprofile_skip` 提示）；PATH 最小集、DSH_HOME 等安装形态决策类 env 不自动扩入，显式 `env` 同名键恒显式优先。
- 调用者 profile 在**安装时刻**锚定（env 与 `Path.home()` 双读取非 systemprofile 侧），不在服务运行期解析——服务进程内的调用者已不可考，安装时刻是唯一可靠锚点；解析失败跳过注入并附提示，不 fail 安装（安装调用者可能自身已在服务上下文运行）。
- 通用漂移逃生口走**部署期环境覆盖**：`FENIX_HOME`（home 替代语义）经服务环境注入重配；`USER_CONFIG_DIR` 保持 import 期单次绑定 + 门面单源派生，不做运行时惰性重绑定——环境漂移不做运行时热切换修复。
- 漂移可见性由读侧单源产出：`/api/config` payload 附实际解析路径（`path` 字段，user/project 双 scope），前端只消费不二次推导。

## Consequences

- `install_unit` 的 `env=None` 语义从「不注入」收紧为「注入默认集」——锁定旧行为的测试断言随语义收紧同步更新；既有手工注入部署靠合并语义天然兼容（只补缺键、不整值替换），零迁移。
- 重配 `FENIX_HOME` 须重启进程生效；「import 期绑定」成为后续配置路径类 SPEC 的结构约束，引入运行时动态解析须显式推翻本裁定。
- 服务上下文内再调 `install_unit` 解析到的仍是漂移 profile——按守卫跳过并提示，服务安装必须由交互式管理员会话执行（文档注明）。
- 设置页缺文件提示附带解析路径后，「进程解析到哪个 home」漂移在界面直接可见；存量部署补救走重跑 `install_unit` 或文档一键手工注入命令。
