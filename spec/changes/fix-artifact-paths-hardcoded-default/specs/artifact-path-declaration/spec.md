## ADDED Requirements

### Requirement: 产物判定由配置驱动，无内置默认路径

构建产物路径判定器（`ArtifactPathMatcher`）MUST 完全由配置驱动，MUST NOT 内置任何
项目路径作为默认判定集合。

系统 MUST NOT 再包含 `DEFAULT_ARTIFACT_PREFIXES` 常量、`_matches_default()` 规则、
以及包级 `_is_build_artifact_path()` 到默认判定的委托。任何形如
「未配置时回退到某个内置路径（如 `core/dashboard/static`）」的行为 MUST 被移除。

判定只依据两个配置键：
- `worktree.has_build_artifacts`（布尔，可缺省）：项目是否存在构建产物；
- `worktree.build_artifact_paths`（字符串列表）：产物路径前缀与通配集合。

#### Scenario: 未配置任何键时判定恒为假

- **WHEN** `has_build_artifacts` 缺省且 `build_artifact_paths` 为空（未裁决）
- **THEN** `is_artifact("core/dashboard/static/dist/a.js")` MUST 返回假
- **AND** `is_artifact("dist/index.html")` MUST 返回假
- **AND** 判定器 MUST NOT 因任何内置默认路径而返回真

#### Scenario: 代码中不再存在内置默认前缀常量

- **WHEN** 在代码库中检索 `DEFAULT_ARTIFACT_PREFIXES`、`_matches_default`、
  或 `_is_build_artifact_path` 的定义
- **THEN** 这三者 MUST NOT 存在（判定逻辑完全由配置注入）

#### Scenario: 已声明带产物的项目按配置判定

- **WHEN** `has_build_artifacts=true` 且 `build_artifact_paths=["dist/"]`
- **THEN** `is_artifact("dist/index.html")` MUST 返回真
- **AND** `is_artifact("src/app.tsx")` MUST 返回假

#### Scenario: 已声明无产物的项目判定恒为假

- **WHEN** `has_build_artifacts=false`（无论 `build_artifact_paths` 取值）
- **THEN** `is_artifact(<任意路径>)` MUST 返回假
- **AND** 判定器 MUST NOT 因任何路径而返回真

### Requirement: has_build_artifacts 三态语义与裁决状态

系统 SHALL 以布尔键 `worktree.has_build_artifacts` 表达项目是否存在构建产物，
其缺省（未设置）MUST 表达「未裁决」，与显式 `false`（已声明无产物）语义不同。

裁决状态 MUST 满足下表（`is_artifact` 列即判定器返回值）：

| `has_build_artifacts` | `build_artifact_paths` | 判定 | 是否需起草 |
|-----------------------|------------------------|------|-----------|
| 缺省 | 空 | 恒假 | 是（未裁决） |
| 缺省 | 非空 | 按配置判定 | 否 |
| `false` | 任意 | 恒假 | 否 |
| `true` | 非空 | 按配置判定 | 否 |
| `true` | 空 | 恒假 | 是（标志与路径不一致） |

系统 SHALL 提供函数判定「该项目是否已裁决产物配置」，未裁决时返回真：
缺省键、或 `has_build_artifacts=true` 但 `build_artifact_paths` 为空，均视为未裁决。

#### Scenario: 缺省键视为未裁决

- **WHEN** 配置中 `worktree` 段不存在或 `has_build_artifacts` 缺省
- **THEN** 裁决判定 MUST 返回「未裁决」
- **AND** 判定器的 `is_artifact` MUST 恒返回假

#### Scenario: 显式 false 视为已裁决无产物

- **WHEN** `has_build_artifacts=false`
- **THEN** 裁决判定 MUST 返回「已裁决」
- **AND** 判定器的 `is_artifact` MUST 恒返回假

#### Scenario: true 配空路径视为未裁决

- **WHEN** `has_build_artifacts=true` 且 `build_artifact_paths=[]`
- **THEN** 裁决判定 MUST 返回「未裁决」（标志与路径不一致，需起草补齐路径）

#### Scenario: 非法布尔值回退未裁决

- **WHEN** `has_build_artifacts` 的值为非布尔（如字符串 `"yes"`、数字 `1`）
- **THEN** 系统 MUST 按「缺省」处理（未裁决），MUST NOT 因非法值让判定变宽
