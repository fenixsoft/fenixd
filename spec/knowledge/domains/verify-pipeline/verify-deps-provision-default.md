# 验证依赖供给默认模式
<!-- knowledge: capability=verify-deps-provision-default rev=1 sources=spec/archive/2026-09-23-fix-verify-serving-disk-reclaim -->

验证 worktree node_modules 供给的默认模式语义：缺省 hardlink 共享 inode，降级链与界面默认标注三处一致。

## 现行规则

- 默认模式：verify.yaml 未指定 `deps_mode` 且项目 config 未设 `verify.deps_mode` 时，采用 `hardlink`——以共享 inode 方式供给依赖，每个 serving worktree 不实装一份 `node_modules`。
- 优先级链：`verify.yaml deps_mode` > `config verify.deps_mode` > 代码默认（`hardlink`）；显式声明不受代码默认影响。
- 自动降级：解析为 `hardlink` 但主树对应子目录不存在 `node_modules` 时，供给自动降级为 `prefer-offline`（`npm ci`），不失败。
- 三处默认一致：代码默认、`.fenix/config.template.yaml` 显式列出 `deps_mode: hardlink`、Dashboard 设置页「验证契约」`VerifyPanel` 在配置缺该键时缺省选中 `hardlink` 并在该项标注「默认」；项目 config 已有显式偏好（如 `prefer-offline`）时界面照实选中，不强制回落新默认。

## 溯源

- 2026-09-23 fix-verify-serving-disk-reclaim（spec/archive/2026-09-23-fix-verify-serving-disk-reclaim） — 依赖供给默认模式定为 hardlink（`prefer-offline` 默认使每个 serving worktree 实装一份 1.6G node_modules，verify-serving 实测占 30G），确立降级链与模板/界面默认标注一致性
