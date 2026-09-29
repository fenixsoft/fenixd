<!-- knowledge: capability=artifact-path-declaration rev=1 sources=spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default -->

# 构建产物路径判定契约

构建产物路径判定的配置驱动契约：判定器无内置默认路径，产物语义完全由项目配置两键表达，未裁决与显式无产物是不同状态。

## 现行规则

- 配置驱动、无内置默认：构建产物路径判定器（`ArtifactPathMatcher`）完全由配置驱动，不内置任何项目路径作为默认判定集合；代码中不存在 `DEFAULT_ARTIFACT_PREFIXES` 常量、`_matches_default()` 规则及包级判定函数到默认判定的委托；「未配置时回退到某个内置路径」的行为不存在。
- 判定依据仅两键：`worktree.has_build_artifacts`（布尔，可缺省）与 `worktree.build_artifact_paths`（字符串列表，产物路径前缀与通配集合）。
- 三态裁决语义：

  | `has_build_artifacts` | `build_artifact_paths` | 判定 | 是否需起草 |
  |---|---|---|---|
  | 缺省 | 空 | 恒假 | 是（未裁决） |
  | 缺省 | 非空 | 按配置判定 | 否 |
  | `false` | 任意 | 恒假 | 否 |
  | `true` | 非空 | 按配置判定 | 否 |
  | `true` | 空 | 恒假 | 是（标志与路径不一致） |

- 未裁决判定：缺省键、或 `has_build_artifacts=true` 但 `build_artifact_paths` 为空，均视为「未裁决」（需起草补齐）；显式 `false` 视为「已裁决无产物」。缺省（未裁决）与显式 `false` 语义不同，判定器在这两种态下均恒返回假。
- 容错：`has_build_artifacts` 值为非布尔（如字符串 `"yes"`、数字 `1`）时按缺省处理（未裁决），不因非法值让判定变宽。

## 溯源

- [2026-09-23 2026-09-23-fix-artifact-paths-hardcoded-default](spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default/) — 移除内置默认路径集合，判定改为纯配置驱动；确立 `has_build_artifacts` 缺省=未裁决的三态语义表
