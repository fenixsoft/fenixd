# spec delta: fix-windows-service-userprofile

## ADDED Requirements

### Requirement: 用户级配置目录 FENIX_HOME 覆盖单源

`core/config.py` 的 `USER_CONFIG_DIR` MUST 按 `FENIX_HOME` 环境变量解析：
设了 `FENIX_HOME` 时 `USER_CONFIG_DIR = Path(FENIX_HOME) / ".fenix"`（FENIX_HOME
语义为 home 替代，与 `Path.home()` 缺省路径形态一致）；未设时保持现状
`Path.home() / ".fenix"`。全库用户级配置目录消费 MUST 经该单源（门面
`core/dashboard/data/__init__.py` 的 `USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"`
派生跟随，不改绑定结构），禁止旁路 `Path.home()` 重复推导。

#### Scenario: FENIX_HOME 设置时覆盖解析

- **WHEN** 进程环境含 `FENIX_HOME=D:\fenix-home` 且导入 `core.config`
- **THEN** `USER_CONFIG_DIR == Path("D:\fenix-home") / ".fenix"`，
  门面 `USER_CONFIG_PATH` 为其下 `config.yaml`，`/api/config` 的 `path` 字段同步

#### Scenario: 未设 FENIX_HOME 时行为不变

- **WHEN** 进程环境无 `FENIX_HOME`
- **THEN** `USER_CONFIG_DIR == Path.home() / ".fenix"`（与现有部署完全兼容）

#### Scenario: 服务环境漂移逃生口

- **WHEN** 服务进程 `USERPROFILE` 漂移（如 LocalSystem 解析到 systemprofile）
  且服务环境注入了正确 `FENIX_HOME`
- **THEN** 用户级配置按 `FENIX_HOME` 解析，`raw_exists` 反映真实文件存在性

### Requirement: 设置页提示携带实际解析路径

`/api/config` 返回 `raw_exists=false` 时，Dashboard 设置页配置状态提示 MUST
同时展示该 scope 实际解析的配置文件路径（user scope 用 payload `path` 字段，
即 `str(USER_CONFIG_PATH)`；project scope 用项目配置路径），使「进程解析到哪个
home」漂移在界面上直接可见，不再只有「不存在」结论。

#### Scenario: 用户级缺失提示含路径

- **WHEN** `/api/config` 返回 `raw_exists=false, scope=user, path=<解析路径>`
- **THEN** 设置页提示为「用户级配置文件不存在，表单为默认值」并附 `<解析路径>`

#### Scenario: 项目级缺失提示含路径

- **WHEN** `/api/config` 返回 `raw_exists=false, scope=project`
- **THEN** 设置页提示为「项目尚无配置文件，表单为默认值」并附项目配置文件解析路径
