# Design: fix-windows-service-userprofile

## Context

- 真机诊断（2026-11-16，Windows 11 / fenixd v0.1.5）：dashboard 与 supervisor NSSM 服务均以 LocalSystem 运行且 `AppEnvironmentExtra` 未注入 USERPROFILE，SCM 提供的 `USERPROFILE=C:\WINDOWS\system32\config\systemprofile` 使 `Path.home()` 漂移；`core/config.py:20` `USER_CONFIG_DIR = Path.home() / ".fenix"` import 期一次性绑定后，`/api/config` 报 `raw_exists=False`，设置页误显「用户级配置文件不存在」。手工注入 USERPROFILE + 重启即愈（真机已验证）。
- 机制层已就绪：`install_unit(root, env=None)`（core/platform/win32.py:1706）支持 REG_MULTI_SZ read-modify-write 合并写 `AppEnvironmentExtra` + env_defect 自检（fix-spawn-attribution-hardening 交付，知识页 daemon-runtime/windows-native-support.md「服务环境注入与自检」条）；但 `env=None` 时什么都不注入，正确性依赖 install.md §8 的"建议"性手工步骤。
- 消费面单源已立：`core/dashboard/data/__init__.py:107` 自 core.config 导入 `USER_CONFIG_DIR`，:124 派生 `USER_CONFIG_PATH`（D8 门面绑定，config_admin 组内经 `_facade.USER_CONFIG_PATH` 解析）；`/api/config` payload 现无 `path` 字段（read_config config_admin.py:895 的 payload 无该键，:3382/3396 的 `path` 属 sync 错误返回非 GET payload——评审实测纠正，本变更须后端补齐，非纯前端改）。
- 设置页提示在 `core/dashboard/static/src/pages/settings/index.tsx:612-617`，纯前端文案改。
- 平台差异收口在 PAL（core/platform/api.py 六名操作面）；Linux `install_unit`（systemd unit）无此问题，本变更不动其签名行为。

## Goals

- Windows 服务化全新部署/幂等重装后，LocalSystem 服务进程解析到安装调用者的真实用户 profile——用户级配置自举承诺（install.md §4a）在服务化形态下成立。
- 提供服务环境漂移的通用逃生口（FENIX_HOME）与可见性（设置页提示带解析路径）。
- G1 清单 G1-01b（用户级配置自举，待复验）随过机验证回填。

## Non-Goals

- 不改 `install_unit` 签名与 REG_MULTI_SZ 合并写机制本身（只改默认 env 集合）。
- 不做 USER_CONFIG_DIR 的 import 后惰性重绑定（进程环境在服务生命周期内视为稳定；FENIX_HOME 是重配手段，不是运行时热切换开关）。
- 不迁移已有手工注入部署（合并语义天然兼容，无需数据迁移）。
- 不改 Linux systemd 承载链（EnvironmentFile PATH 卫生既有规则不受影响）。

## Decisions

1. **默认注入下沉到 `install_unit` 而非 install.md 文档要求**：机制已有、调用纪律散（§8 手工 nssm 与 `pal.install_unit` 两态并存）。默认值是唯一能让所有部署路径（脚本/agent 代部署/手工）同时正确的收口点；文档仍同步升格为必做表述，双保险。
2. **默认集只含 `USERPROFILE`，不自动扩 PATH/DSH_HOME**：A7-1 曾建议整组注入，但 PATH 最小集与 DSH_HOME 属安装形态决策（install.md §8 已有明确清单），自动注入整组会覆盖既有手工调优；USERPROFILE 是「LocalSystem 语义错误」的确定性修复，无此顾虑。显式 `env=` 仍可全量自定义（同键显式优先）。
3. **调用者 profile 在安装时刻解析**（`os.environ["USERPROFILE"]` / `Path.home()` 双读校验），不在服务运行期解析——服务进程的调用者已不可考，安装时刻是唯一可靠锚点；解析失败（无 USERPROFILE 且 home 即 systemprofile）时跳过注入并在返回 JSON 附提示字段，不 fail 安装。
4. **FENIX_HOME 语义 = home 替代**（`USER_CONFIG_DIR = Path(FENIX_HOME) / ".fenix"`），不用"配置目录直指"语义：与缺省路径形态一致、服务注入场景直觉（指向真实用户 home）、文档零歧义。
5. **不做运行时惰性重绑定**：6 个消费点均为 import 后取值或门面派生，惰性化要动绑定结构（D8 决策面）且无真实需求（服务环境在进程生命周期内不变）；import 期读 env 足够，风险最小。
6. **设置页提示消费后端补齐的 payload `path` 字段**：`/api/config` GET payload 现无该键（read_config config_admin.py:895 的 payload 无 `path`；原先以为「已产出」系把 :3382/3396 的 sync 错误返回字段误当 GET payload——评审实测纠正），user/project 两 scope 均在后端补齐（read_config 与 read_effective_config 正常/异常早退路径形状一致），前端只消费不二次推导。
7. **前端产物**：`core/dashboard/static/dist` 已被 gitignore 模式命中但 index.html 受Track——dist/index.html 在 Deliverables 声明为 `reference`（构建产物运行时重建），实现任务含 pnpm build 重建与提交，收工守卫不作硬门。
8. **默认 USERPROFILE 注入仅限 LocalSystem 承载形态**：`install_unit` 新装服务 NSSM 默认 LocalSystem，恒注入；already 路径先读服务账户（`sc qc` 的 ObjectName/StartName），非 LocalSystem 专用账户跳过默认注入——SCM 已为专用账户提供真实 profile，注入安装者 profile 反成覆写错误值（与决策 2 同理：只修确定性语义错误，不碰形态本来就正确的部署）；跳过时返回 JSON 附提示字段，不 fail 安装。

## Risks

- **默认注入改变 `env=None` 行为语义**（原"不注入"→"注入 USERPROFILE"）：存量测试断言（tests/test_install_unit_env.py、test_platform_pal.py）可能锁定旧行为，实现时同步更新断言；此为 proposal 已声明的非破坏性语义收紧（env=None 场景此前产物即有缺陷）。
- **安装调用者本身在服务上下文运行**（systemd/NSSM 服务的子进程再调 install_unit）：此时解析到的还是 systemprofile——按决策 3 跳过并提示，不注入错误值；文档注明须由交互式管理员会话执行安装。
- **FENIX_HOME 与 USERPROFILE 同时存在时优先级**：FENIX_HOME 严格优先（显式覆盖 > 环境默认），测试锁定。
- **默认注入若不加守卫会波及非 LocalSystem 专用账户服务**（SCM 已给该账户真实 profile，注入安装者 profile 反成覆写回归）：按决策 8 以服务账户（ObjectName）守卫收口，跳过时附提示字段。
- **过机通道可用性**：win-vm SSH（docker@127.0.0.1:22222，2026-11-16 实测可用）承载 Windows 复验；通道中断时按环境止损纪律申报 partial + unattainable，Linux 逻辑面照常交付。

## Migration / Compatibility

- 存量 LocalSystem 服务（无注入）：重跑 `install_unit` 或按 install.md §8 补救命令手工注入；文档给出一键命令。
- 存量已手工注入服务：重跑安装按合并语义保留既有条目，仅补缺键。
- Linux/前台运行形态：零影响（FENIX_HOME 未设时路径解析与现状逐字节一致）。
