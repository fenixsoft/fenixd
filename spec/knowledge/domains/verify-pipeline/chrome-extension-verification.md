<!-- knowledge: capability=chrome-extension-verification rev=1 origin=prehistoric sources=git:44e1443ba-..2026-09-02 -->

# 扩展项目验证

浏览器扩展类项目的验证由专用启动器与验证引擎的扩展目标回退规则共同支撑。

## 现行规则

- 启动器 `bin/launch-chrome-extension.js`（Node）负责扩展构建产物的加载与检测：支持 `--dist-path`、`--detect <spec-dir>`、`--timeout`、`--headless`、`--debug`、`--output` 等参数，产出结构化检测结果。
- 环境健全性门（`env_gate`）对 `chrome-extension://` 基址不做 HTTP 连通探测：扩展内页无法在验证上下文直接探测，直接视为健康（保守通过），不判环境阻塞。
- 验证浏览器不加载被测扩展，`chrome-extension://` 页面不可达；navigate 目标为 `chrome-extension://` URL 时统一回退到本地 HTTP 服务器入口（`verify.html` 或 `index.html`），并记 warning，不据此判 fail。
- 扩展项目中 navigate 到 `about:blank`/`about:` 目标同样回退本地 HTTP 入口。
- 回退入口与 `navigate_to_app` 同款，保证场景断言基于可达页面执行。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基础规则
