<!-- knowledge: capability=artifact-path-dashboard-ui rev=1 sources=spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default -->

# 构建产物路径配置界面

Dashboard 设置页产物卡片的编辑与回显契约：三态呈现区分「未配置/有产物/无产物」，写入经后端校验，回显不把未裁决洗成已裁决。

## 现行规则

- 卡片位置与控件：设置页「验证」页签「构建产物路径」卡片承载 `has_build_artifacts` 开关（文案「项目存在构建产物」）与路径列表；三态呈现——未裁决（键缺省）：控件处于可区分的「未配置」态，显示「尚未配置」提示，路径列表可编辑；已声明有产物（`true`）：开关为开，路径列表可编辑；已声明无产物（`false`）：开关为关，路径列表置灰/隐藏，显示「已声明本项目无构建产物」。
- 未配置态不得呈现为无产物：antd `Switch` 无 indeterminate 语义（`SwitchProps` 仅 `checked?: boolean`），承载三态须用 `Radio.Group` 类三态控件，或以开关关 + 显式「尚未配置」文案区分，不得声称开关处于未定态。
- 无 AI 起草按钮：本卡片不提供「AI 起草」入口（既有自动起草通路只覆盖 verify.yaml）；产物路径的起草由运行期信号 + Administrator 承担（见 `artifact-path-autofill`）；提示文案不得承诺本页面存在「AI 起草」入口。
- 作用域：两键为项目级键；用户级作用域下整卡只读（含开关），显示切换到项目级作用域的提示。
- 写入后端校验：`has_build_artifacts` 必须为布尔（非布尔返回 400 拒绝，不写入）；`build_artifact_paths` 经 `validate_build_artifact_paths` 校验（非法项被拒而非静默丢弃，如未以 `/` 结尾的项返回 400 附合法形态提示）；两键登记进 `config_admin.py` 的受管键、缺省字典与来源标注，出现在 `read_config`/`read_effective_config` 回显与来源标注中。
- 回显三态保真：配置未定义 `worktree.has_build_artifacts` 时回显为 `None`（未裁决），不得被缺省填充为 `false`；仅当配置显式写有 `false` 时回显才为 `false`——否则前端无法区分「未裁决」与「已声明无产物」；产物路径回显通路须一并返回该键。

## 溯源

- [2026-09-23 2026-09-23-fix-artifact-paths-hardcoded-default](spec/archive/2026-09-23-fix-artifact-paths-hardcoded-default/) — 新增产物卡片三态呈现与作用域只读、写入后端校验与受管键登记、回显未裁决/显式 false 保真
