#!/usr/bin/env node

/**
 * Fenix Tier 2 Verifier — Chrome Extension Launch Script
 *
 * 启动 Chromium 并加载 dist/ 目录中的 Chrome 扩展，收集网络请求日志，
 * 自动检测异常状态码，输出结构化 JSON 结果。
 *
 * 用法:
 *   node .fenix/bin/launch-chrome-extension.js [options]
 *
 * 选项:
 *   --dist-path <path>    扩展目录路径 (默认: ./dist)
 *   --timeout <ms>        采集+UI 测试段总超时，超时后提前收卷并标注 timedOut (默认: 60000)
 *   --debug               保留 Chromium profile 用于调试
 *   --headless            无头模式 (默认: 有头)
 *   --output <path>       输出 JSON 文件路径 (默认: stdout)
 *   --detect <spec-dir>   仅检测 SPEC 是否需要 Tier 2 验证后退出，不启动浏览器
 *
 * 输出 JSON:
 *   {
 *     "success": true/false,
 *     "extensionLoaded": true/false/null,  // null = 超时收卷且一条 UI 测试都未跑，扩展加载未经任何验证（不确定态，非 false）
 *     "networkLog": [...],
 *     "anomalies": [...],
 *     "duration": <ms>,
 *     "timedOut": true/false,
 *     "error": "<message if success=false>"
 *   }
 */

import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ============================================================================
// 命令行参数解析
// ============================================================================

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    distPath: './dist',
    timeout: 60000,
    debug: false,
    headless: false,
    output: null,
    detect: null,
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--dist-path':
        opts.distPath = args[++i];
        break;
      case '--timeout':
        opts.timeout = parseInt(args[++i], 10);
        break;
      case '--debug':
        opts.debug = true;
        break;
      case '--headless':
        opts.headless = true;
        break;
      case '--output':
        opts.output = args[++i];
        break;
      case '--detect':
        opts.detect = args[++i];
        break;
      default:
        // 对未匹配任何 case 且以 -- 开头的参数告警：拼写错误的选项（如 --timeut）若被静默忽略，
        // 调用方难以察觉参数未生效，验证口径会静默漂移；仅告警不退出，兼容调用方传入的新合法选项。
        // 非 -- 开头的位置参数不在此列（可能作为独立占位实参，不属于选项拼写错误）。
        if (String(args[i]).startsWith('--')) {
          console.error(`警告: 未识别的命令行选项 "${args[i]}"，已忽略`);
        }
        break;
    }
  }

  // 校验参数取值：--timeout 缺值/非数字会得 NaN、0 或负数会使剩余预算恒为 0 立即超时收卷，
  // 造成零验证假通过，故须为正数；带值选项缺值时静默得 undefined，空串取值（如 `--detect ""`）
  // 则会通过缺值校验后在 main 里按假值分支走（--detect 空串跳过检测、--output 空串放弃落盘），
  // 调用方预期被静默改变，故空串与 undefined 同列报错；取值以 -- 开头（如 `--dist-path --debug`
  // 漏给值）会把下一个选项名当作路径静默通过——--dist-path 报「dist 目录不存在: …/--debug」误导
  // 排障，--output 更会在 cwd 落出错误命名的结果文件，故以 -- 开头的取值一并报错（code-review item 6075c3ad88f7）
  const usage = '用法: node launch-chrome-extension.js [--dist-path <path>] [--timeout <ms>] [--debug] [--headless] [--output <path>] [--detect <spec-dir>]';
  let invalidReason = null;
  if (!Number.isFinite(opts.timeout) || opts.timeout <= 0) invalidReason = '--timeout 需要正数参数（毫秒，须大于 0）';
  if (opts.distPath === undefined || opts.distPath === '' || opts.distPath.startsWith('--')) invalidReason = '--dist-path 缺少取值';
  if (opts.output === undefined || opts.output === '' || opts.output.startsWith('--')) invalidReason = '--output 缺少取值';
  if (opts.detect === undefined || opts.detect === '' || opts.detect.startsWith('--')) invalidReason = '--detect 缺少取值';
  if (invalidReason) {
    console.error(`错误: ${invalidReason}\n${usage}`);
    process.exit(1);
  }

  return opts;
}

// ============================================================================
// 工具函数
// ============================================================================

/**
 * 判断主机名是否为本机/回环地址（localhost、127.x、[::1]、0.0.0.0、*.local 等）
 * 按精确主机名匹配，而非对整条 URL 做子串匹配
 */
function isLocalHostname(hostname) {
  // URL 的 hostname 对 IPv6 自带方括号；去掉首尾括号与结尾的 FQDN 点号后归一化比较
  const host = String(hostname || '').toLowerCase().replace(/^\[/, '').replace(/\]$/, '').replace(/\.$/, '');
  return (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    // 127/8 须整体为四段点分数字，否则 127.0.0.1.<公网域名> 这类可公网解析的子域
    // （DNS rebinding 常用形态）会被误判为本机而漏采进 networkLog/anomalies
    /^127(\.\d{1,3}){3}$/.test(host) ||
    host === '::1' ||
    host === '::' ||
    host === '0.0.0.0' ||
    host.endsWith('.local')
  );
}

/**
 * 判断 URL 是否为外部 URL（非本机/回环主机 / 非扩展内部资源）
 * URL 解析失败时按外部处理，保持采集保守性
 */
function isExternalUrl(url) {
  if (!url || typeof url !== 'string') return false;
  // 放行 ws://、wss://：外部 WebSocket 连接同样进 networkLog 与异常检测，
  // 否则其连接失败对 hasCriticalAnomalies 不可见，验证结论漏报该类故障（code-review item 90f2565d2d1e）
  if (!/^(https?|wss?):\/\//i.test(url)) return false;
  try {
    if (isLocalHostname(new URL(url).hostname)) return false;
  } catch {
    return true;
  }
  return true;
}

/**
 * 检测已知 API 域名所需的请求头
 * 返回缺失的必需头列表
 *
 * 域名→必需头规则表默认为空：原内置的 hq.sinajs.cn/sina.com.cn Referer 检查是
 * stock-panel 扩展的项目特化遗留规则，对其他被验证扩展无作用，且按整条 URL 子串
 * 匹配会误伤查询串中恰含该域名的请求，已移除。需要域名级头检查时由调用方在
 * 此注入规则，并按 URL 解析后的 hostname 匹配（勿用整条 URL 子串匹配）。
 */
function checkRequiredHeaders(url, headers) {
  // 规则表默认为空（见上），当前无可检查规则；保留签名作为调用方注入规则的落点
  return [];
}

/**
 * 根据状态码确定异常严重级别
 * 唯一调用点（detectAnomalies 的 status >= 400 分支）已保证 status >= 400，
 * 故不设更低区间的分支（原 return 'low' 死分支已移除，口径同 26d37b169a48 删除 critical 死分支）
 */
function severityFromStatus(status) {
  if (status >= 500) return 'external-service';  // 外部服务异常，不计为代码缺陷
  if (status === 403) return 'high';              // 403 通常是配置问题
  if (status === 401) return 'high';
  if (status === 404) return 'medium';
  return 'high';
}

/**
 * 检测网络异常
 */
function detectAnomalies(networkLog) {
  const anomalies = [];

  for (const entry of networkLog) {
    if (entry.type === 'response') {
      const status = entry.status;
      if (status >= 400) {
        const severity = severityFromStatus(status);
        anomalies.push({
          type: severity === 'external-service' ? 'external-service-error' : 'http-error',
          severity,
          url: entry.url,
          method: entry.method || 'GET',
          statusCode: status,
          statusText: entry.statusText || '',
          timestamp: entry.timestamp,
          description: severity === 'external-service'
            ? `外部服务返回 ${status} — 非代码缺陷`
            : `HTTP ${status} ${entry.statusText || ''}`,
          suggestion: status === 403
            ? '检查请求头（Referer、Origin 等）是否正确设置'
            : status === 404
              ? '检查 API 端点是否正确'
              : '检查请求参数和 API 可用性',
        });
      }
    }

    if (entry.type === 'failure') {
      const errorMsg = (entry.error || '').toLowerCase();
      const isCors = errorMsg.includes('cors') || errorMsg.includes('cross-origin');
      // 取消/拦截类失败并非被验证扩展的代码缺陷：ERR_ABORTED 是导航取消或页面侧 abort，
      // ERR_BLOCKED_BY_CLIENT/ADMINPOLICY 是被浏览器或其它扩展拦截，降为 medium（category
      // 单列 cancelled/blocked）不入 hasCriticalAnomalies 的 high 档，避免功能完好的扩展
      // 因取消类失败被误判 success=false；仅真实网络层错误（ERR_CONNECTION_*/
      // ERR_NAME_NOT_RESOLVED 等）保持 high
      const isCancelled = errorMsg.includes('err_aborted');
      const isBlocked = errorMsg.includes('err_blocked_by_client') || errorMsg.includes('err_blocked_by_adminpolicy');
      const isBenign = isCancelled || isBlocked;
      const severity = isBenign ? 'medium' : 'high';

      anomalies.push({
        type: 'request-failure',
        severity,
        url: entry.url,
        method: entry.method || 'GET',
        error: entry.error,
        timestamp: entry.timestamp,
        category: isBenign ? (isCancelled ? 'cancelled' : 'blocked') : (isCors ? 'cors' : 'network'),
        description: isCancelled
          ? `请求被取消/中止（${entry.error}）— 导航取消或页面侧 abort，非代码缺陷`
          : isBlocked
            ? `请求被拦截（${entry.error}）— 被浏览器或其它扩展拦截，非代码缺陷`
            : isCors
              ? 'CORS 错误 — 浏览器拦截了跨域请求'
              : `请求失败: ${entry.error}`,
        suggestion: isCancelled || isBlocked
          ? '若该请求为预期行为可忽略；否则检查导航/abort 逻辑或拦截来源（其它扩展、浏览器策略）'
          : isCors
            ? '检查 manifest.json 中的 host_permissions 是否包含该域名'
            : '检查网络连接和目标服务器状态',
      });
    }

    // 检查请求头完整性
    if (entry.type === 'request' && entry.url) {
      const missingHeaders = checkRequiredHeaders(entry.url, entry.headers);
      for (const mh of missingHeaders) {
        anomalies.push({
          type: 'missing-header',
          severity: mh.severity,
          url: entry.url,
          method: entry.method || 'GET',
          header: mh.header,
          timestamp: entry.timestamp,
          description: `缺少 ${mh.header} 请求头`,
          suggestion: mh.suggestion,
        });
      }
    }
  }

  return anomalies;
}

// ============================================================================
// 主逻辑
// ============================================================================

async function launchChromeExtension(distPath, opts = {}) {
  const {
    timeout = 60000,
    debug = false,
    headless = false,
  } = opts;

  const startTime = Date.now();
  const networkLog = [];

  // 解析 dist 路径为绝对路径
  const absoluteDist = path.resolve(distPath);

  // 验证 dist 目录存在
  if (!fs.existsSync(absoluteDist)) {
    return {
      success: false,
      extensionLoaded: false,
      networkLog: [],
      anomalies: [],
      duration: Date.now() - startTime,
      error: `dist 目录不存在: ${absoluteDist}`,
    };
  }

  // 验证 manifest.json 存在
  const manifestPath = path.join(absoluteDist, 'manifest.json');
  if (!fs.existsSync(manifestPath)) {
    return {
      success: false,
      extensionLoaded: false,
      networkLog: [],
      anomalies: [],
      duration: Date.now() - startTime,
      error: `manifest.json 不存在: ${manifestPath}`,
    };
  }

  // mkdtemp 生成含随机后缀的临时 profile 目录，避免 Date.now() 可预测命名在共享主机上的符号链接占位风险
  const userDataDir = fs.mkdtempSync('/tmp/fenix-ext-profile-');
  let browserContext = null;

  try {
    // 启动 Chromium 并加载扩展
    browserContext = await chromium.launchPersistentContext(userDataDir, {
      // [fenix-ignore:e6ec04e0f23d] 实测环境 Playwright（全局 1.59.1、tests/v2 1.62.1）均 ≥1.49，headless:true 默认即 new headless，可加载 MV3 扩展，旧 headless 前提不成立
      headless: headless,
      args: [
        `--disable-extensions-except=${absoluteDist}`,
        `--load-extension=${absoluteDist}`,
        // 验证机常以 root/容器身份运行，Chromium 在 root 下无法启用内核沙箱，故保留 --no-sandbox（仅加载本地 dist 扩展，验证场景风险可控）
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
      ],
      timeout: 30000, // 30s 启动超时
    });

    // ========================================================================
    // 网络日志收集
    // ========================================================================

    // 在 context 级设置网络监听 — 必须在任何等待/开页之前挂载，
    // 否则扩展初始加载窗口内的请求（最关键的外部 API 调用）会漏采。
    // Playwright 的 page 级事件不携带 MV3 service worker 发起的请求
    // （SW 请求只在 browserContext 上发出），而扩展后台抓取恰跑在 SW 里；
    // context 级同时覆盖所有页面与 SW，故不再另挂 page 级监听，避免同请求双计 anomalies
    setupNetworkLogging(browserContext, networkLog);

    // ========================================================================
    // 网络采集 + UI 测试 — 受 --timeout 总预算约束，超时后提前收卷已有 networkLog
    // ========================================================================

    let timedOut = false;
    const collectAndTest = async () => {
      // 等待扩展加载 — 扩展接管 newtab 后会自动打开一个新标签页
      // 给扩展一些时间加载
      await new Promise(resolve => setTimeout(resolve, 3000));

      // 无已有页面时兜底开一页（网络监听挂于 context 级，开页时序不影响采集覆盖）
      const pages = browserContext.pages();
      if (pages.length === 0) {
        await browserContext.newPage();
      }

      // 打开新标签页 — 应该由扩展接管
      const newtabPage = await browserContext.newPage();
      // console 错误监听必须在页面加载前挂载（同 networkLog 的时序约束），
      // 否则页面初始化窗口内的控制台错误会漏采致假通过；测试 5 只读取累计结果
      const consoleErrors = [];
      newtabPage.on('console', msg => {
        if (msg.type() === 'error') {
          consoleErrors.push(msg.text());
        }
      });
      // 等待页面加载
      await newtabPage.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {
        // 超时不算致命错误
      });

      // 等待一段时间让页面完成初始网络请求
      await new Promise(resolve => setTimeout(resolve, 5000));

      // ======================================================================
      // UI 交互测试
      // ======================================================================

      return runUITests(browserContext, newtabPage, consoleErrors);
    };

    // 用剩余预算作总超时；超时后用已采集到的 networkLog 提前收卷
    const remaining = Math.max(0, timeout - (Date.now() - startTime));
    let timeoutTimer;
    const timeoutPromise = new Promise(resolve => {
      timeoutTimer = setTimeout(() => { timedOut = true; resolve(null); }, remaining);
    });

    // 超时收卷后 collectAndTest 仍在后台执行，finally 中 browserContext.close() 会使其内部
    // 未兜底的 await（如 newPage）以 Target closed 拒绝；附加 catch 分支吞掉迟到失败，
    // 避免 unhandledRejection 使进程崩溃（race 本身仍监听原 Promise，失败时照常进外层 catch）
    const collectPromise = collectAndTest();
    collectPromise.catch(() => {});
    const raced = await Promise.race([collectPromise, timeoutPromise]);
    clearTimeout(timeoutTimer);
    const uiResults = raced === null ? [] : raced;

    // ========================================================================
    // 收集结果
    // ========================================================================

    const endTime = Date.now();
    const anomalies = detectAnomalies(networkLog);
    // 判定范围只含实际会产生的 severity（high）；'critical' 无任何产生来源，已移除死分支（code-review item 26d37b169a48）
    const hasCriticalAnomalies = anomalies.some(a => a.severity === 'high');

    // UI 测试 fail/error（面板未渲染、Console 报错等，与 buildSummary.uiTestFailures 同口径）
    // 纳入 success，防止页面功能全挂时仅凭网络无异常即假通过；超时收卷时 uiResults 为空不受影响
    const hasUiTestFailures = uiResults.some(t => t.status === 'fail' || t.status === 'error');

    const result = {
      // 超时收卷且 UI 测试与 networkLog 均为零证据时，扩展未经任何验证，不判通过
      success: !hasCriticalAnomalies && !hasUiTestFailures && !(timedOut && uiResults.length === 0 && networkLog.length === 0),
      // 超时收卷且一条 UI 测试都未跑时，扩展加载未经任何验证，置 null 表示不确定而非乐观通过
      extensionLoaded: timedOut && uiResults.length === 0 ? null : true,
      extensionId: await getExtensionId(absoluteDist, browserContext),
      manifestPath,
      userDataDir: debug ? userDataDir : null,
      networkLog,
      anomalies,
      uiTests: uiResults,
      timedOut,
      duration: endTime - startTime,
      summary: buildSummary(anomalies, uiResults),
    };

    return result;

  } catch (error) {
    const endTime = Date.now();
    const anomalies = detectAnomalies(networkLog);
    return {
      success: false,
      extensionLoaded: false,
      extensionId: null,
      manifestPath,
      networkLog,
      anomalies,
      uiTests: [],
      timedOut: false,
      duration: endTime - startTime,
      summary: buildSummary(anomalies),
      error: error.message || String(error),
    };
  } finally {
    // 清理
    if (browserContext) {
      try {
        await browserContext.close();
      } catch (_) { /* ignore */ }
    }

    // 清理临时 profile（除非 debug 模式）
    if (!debug && fs.existsSync(userDataDir)) {
      try {
        fs.rmSync(userDataDir, { recursive: true, force: true });
      } catch (_) { /* ignore */ }
    }
  }
}

// ============================================================================
// 网络日志设置
// ============================================================================

// 敏感键名词表：认证/Cookie/令牌/密钥/凭据/口令/会话类，请求头与 URL 查询串脱敏共用同一口径
// （key 子串已覆盖 apikey/access_key，token 已覆盖 access_token；
//   pwd 用字符类边界避免误伤内嵌 pwd 的普通词形）
const SENSITIVE_KEY_PATTERN = /auth|cookie|token|key|secret|credential|password|passwd|session|(?:^|[^a-z0-9])pwd(?:[^a-z0-9]|$)/;

/**
 * 脱敏请求/响应头：保留键名，敏感键（认证/Cookie/密钥类）的值替换为固定占位符；
 * URL 形态的值（Referer/Origin 等）额外过 sanitizeUrl 脱敏其查询串
 * networkLog 会随验证产物落盘（--output 文件或 stdout），不落盘密钥；
 * 头检测（checkRequiredHeaders）只判断键名存在性，脱敏不影响
 */
function sanitizeHeaders(headers) {
  if (!headers || typeof headers !== 'object') return headers;
  const sanitized = {};
  for (const [name, value] of Object.entries(headers)) {
    if (SENSITIVE_KEY_PATTERN.test(name.toLowerCase())) {
      sanitized[name] = '[REDACTED]';
    } else if (typeof value === 'string' && /^https?:\/\//i.test(value)) {
      // 值本身是 URL 的头：其查询串可能携带 token/key 等敏感参数，
      // 与 sanitizeUrl 同口径脱敏后再落盘，避免经 networkLog 明文泄露（code-review item 1f3f7b7c7a29）
      sanitized[name] = sanitizeUrl(value);
    } else {
      sanitized[name] = value;
    }
  }
  return sanitized;
}

/**
 * 脱敏 URL 查询串：保留路径与非敏感参数，键名命中敏感词的参数值替换为占位符
 * 外部 API 常把凭据放在 query（如 ?key=...、?access_token=...），与请求头同口径在落盘前脱敏；
 * 解析失败时原样返回（采集侧 isExternalUrl 已按原始 URL 判定，脱敏不影响过滤结果）
 */
function sanitizeUrl(url) {
  if (!url || typeof url !== 'string') return url;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  if (!parsed.search) return url;
  const params = new URLSearchParams(parsed.search);
  // 同名多值参数（如 ?a=1&a=2）会让 keys() 迭代出重复键名，若对命中键用 set（先删后插）
  // 会把多值折叠成单值，脱敏后落盘的 URL 丢失参数个数信息，排查网关行为时误读请求形态
  // （code-review item 8b0227b84e1d）。故先收集命中键集合，再重建查询串：
  // 非命中键逐值原样 append 复制，命中键按原值个数逐个 append 占位符，保持多值结构
  const redactedKeys = new Set();
  for (const name of params.keys()) {
    if (SENSITIVE_KEY_PATTERN.test(name.toLowerCase())) redactedKeys.add(name);
  }
  if (redactedKeys.size === 0) return url;
  const rebuilt = new URLSearchParams();
  for (const name of new Set(params.keys())) {
    const values = params.getAll(name);
    if (redactedKeys.has(name)) {
      for (let k = 0; k < values.length; k++) rebuilt.append(name, '[REDACTED]');
    } else {
      for (const value of values) rebuilt.append(name, value);
    }
  }
  parsed.search = rebuilt.toString();
  return parsed.toString();
}

/**
 * 在 BrowserContext 级挂载 request/response/requestfailed 监听：
 * page 级事件收不到 MV3 service worker 发起的请求（扩展后台轮询/刷新恰跑在 SW 里），
 * 漏采会使 hasCriticalAnomalies 对后台网络行为失明；context 级事件覆盖全部页面与 SW。
 */
function setupNetworkLogging(context, networkLog) {
  context.on('request', (req) => {
    if (isExternalUrl(req.url())) {
      networkLog.push({
        type: 'request',
        url: sanitizeUrl(req.url()),
        method: req.method(),
        headers: sanitizeHeaders(req.headers()),
        timestamp: Date.now(),
      });
    }
  });

  context.on('response', (res) => {
    if (isExternalUrl(res.url())) {
      networkLog.push({
        type: 'response',
        url: sanitizeUrl(res.url()),
        // 直接从 response 关联的 request 对象取 method：同 URL 并发时按 url 扫描会取错条目，且长采集下为 O(n^2)
        method: res.request().method() || 'GET',
        status: res.status(),
        statusText: res.statusText(),
        headers: sanitizeHeaders(res.headers()),
        timestamp: Date.now(),
      });
    }
  });

  context.on('requestfailed', (req) => {
    if (isExternalUrl(req.url())) {
      networkLog.push({
        type: 'failure',
        url: sanitizeUrl(req.url()),
        method: req.method(),
        error: req.failure()?.errorText || 'Unknown error',
        timestamp: Date.now(),
      });
    }
  });
}

// ============================================================================
// 扩展 ID 获取
// ============================================================================

async function getExtensionId(distPath, context) {
  try {
    const manifest = JSON.parse(
      fs.readFileSync(path.join(distPath, 'manifest.json'), 'utf-8')
    );
    const extName = manifest.name || 'unknown';

    // 尝试从 service worker 获取扩展 ID
    const workers = context.serviceWorkers();
    if (workers.length > 0) {
      const swUrl = workers[0].url();
      const match = swUrl.match(/chrome-extension:\/\/([^/]+)\//);
      if (match) return match[1];
    }

    // 回退：从 background pages 获取
    const bgPages = context.backgroundPages();
    if (bgPages.length > 0) {
      const bgUrl = bgPages[0].url();
      const match = bgUrl.match(/chrome-extension:\/\/([^/]+)\//);
      if (match) return match[1];
    }

    return `unknown (${extName})`;
  } catch {
    return 'unknown';
  }
}

// ============================================================================
// UI 交互测试
// ============================================================================

async function runUITests(context, page, consoleErrors = []) {
  const results = [];

  try {
    // 测试 1: 页面标题
    try {
      const title = await page.title();
      results.push({
        test: '页面加载',
        status: title ? 'pass' : 'fail',
        detail: title ? `页面标题: ${title}` : '页面无标题',
      });
    } catch (e) {
      results.push({ test: '页面加载', status: 'error', detail: e.message });
    }

    // 测试 2: 面板渲染
    // panel/widget 类名选择器是 stock-panel 时代沿用的启发式：以 shadow DOM、canvas 或
    // 无此类命名的 UI 形态（列表页、全屏 newtab 等）承载功能的扩展会命中 0 而恒 fail，
    // 给功能完好的扩展假阴性结论。主选择器未命中时改查替代命中面（页面实质内容：
    // 元素数、shadow root、文本量），仍未命中才 fail，且 detail 标注启发式局限，
    // 供上游区分真缺陷与 UI 形态不匹配（code-review item d731fddbf7c3）
    try {
      const panels = await page.$$('[class*="panel"], [class*="widget"], [data-panel]');
      if (panels.length > 0) {
        results.push({
          test: '面板渲染',
          status: 'pass',
          detail: `发现 ${panels.length} 个面板`,
        });
      } else {
        const alt = await page.evaluate(() => {
          let shadowRoots = 0;
          for (const el of document.querySelectorAll('*')) {
            if (el.shadowRoot) shadowRoots++;
          }
          const body = document.body;
          const textLen = body && body.textContent ? body.textContent.trim().length : 0;
          return {
            shadowRoots,
            elementCount: document.querySelectorAll('body *').length,
            textLen,
          };
        });
        if (alt.elementCount > 0 || alt.shadowRoots > 0 || alt.textLen > 0) {
          results.push({
            test: '面板渲染',
            status: 'pass',
            detail: `未命中 panel/widget 类名启发式，但页面已有实质内容（元素 ${alt.elementCount} 个、shadow root ${alt.shadowRoots} 个、文本 ${alt.textLen} 字符）`,
          });
        } else {
          results.push({
            test: '面板渲染',
            status: 'fail',
            detail: '未发现面板元素（panel/widget 类名启发式未命中且页面无实质内容；可能为 UI 形态不匹配，也可能确实渲染失败）',
          });
        }
      }
    } catch (e) {
      results.push({ test: '面板渲染', status: 'error', detail: e.message });
    }

    // 测试 3: 按钮可见性（仅检测可见性，未实际点击，避免测试产生副作用）
    try {
      const buttons = await page.$$('button');
      let clickableCount = 0;
      for (const btn of buttons.slice(0, 10)) {
        const isVisible = await btn.isVisible();
        if (isVisible) clickableCount++;
      }
      results.push({
        test: '按钮可见性',
        status: buttons.length > 0 ? 'pass' : 'warn',
        detail: buttons.length > 0
          ? `${buttons.length} 个按钮 (${clickableCount} 个可见；仅检测可见性，未点击)`
          : '未发现按钮',
      });
    } catch (e) {
      results.push({ test: '按钮可见性', status: 'error', detail: e.message });
    }

    // 测试 4: localStorage 可用
    try {
      const hasStorage = await page.evaluate(() => {
        try {
          localStorage.setItem('__fenix_test__', '1');
          const val = localStorage.getItem('__fenix_test__');
          localStorage.removeItem('__fenix_test__');
          return val === '1';
        } catch {
          return false;
        }
      });
      results.push({
        test: 'localStorage',
        status: hasStorage ? 'pass' : 'fail',
        detail: hasStorage ? 'localStorage 可用' : 'localStorage 不可用',
      });
    } catch (e) {
      results.push({ test: 'localStorage', status: 'error', detail: e.message });
    }

    // 测试 5: Console 错误检查 — consoleErrors 自页面创建起累计（含加载期），此处只读取
    try {
      results.push({
        test: 'Console 错误',
        status: consoleErrors.length === 0 ? 'pass' : 'fail',
        detail: consoleErrors.length === 0
          ? '无控制台错误'
          : `${consoleErrors.length} 个错误: ${consoleErrors.slice(0, 3).join('; ')}`,
      });
    } catch (e) {
      results.push({ test: 'Console 错误', status: 'error', detail: e.message });
    }

  } catch (e) {
    results.push({ test: 'UI 测试', status: 'error', detail: e.message });
  }

  return results;
}

// ============================================================================
// 结果汇总
// ============================================================================

function buildSummary(anomalies, uiTests = []) {
  // codeDefects 与 success 判定同口径：只计 high（即 hasCriticalAnomalies 的判定范围）
  const codeAnomalies = anomalies.filter(a => a.severity === 'high');
  // warning 级问题单列，不混入 codeDefects。当前唯一产生源 missing-header 依赖
  // checkRequiredHeaders 的规则表（现为空，见其函数注释），故 warnings 现阶段恒 0；
  // medium（HTTP 404，以及取消/拦截类请求失败，见 detectAnomalies）异常不入任何分档，
  // 仅计入 totalAnomalies，分档之和可与 totalAnomalies 不一致（预期口径，needsAttention
  // 与 success 判定不依赖分档）
  const warningAnomalies = anomalies.filter(a => a.severity === 'warning');
  const serviceAnomalies = anomalies.filter(a => a.severity === 'external-service');
  const uiFailures = uiTests.filter(t => t.status === 'fail' || t.status === 'error');

  return {
    totalAnomalies: anomalies.length,
    codeDefects: codeAnomalies.length,
    warnings: warningAnomalies.length,
    externalServiceIssues: serviceAnomalies.length,
    uiTestFailures: uiFailures.length,
    uiTestTotal: uiTests.length,
    // needsAttention 保持原口径：所有非 external-service 异常或 UI 失败都提示关注
    needsAttention: anomalies.some(a => a.severity !== 'external-service') || uiFailures.length > 0,
  };
}

// ============================================================================
// Tier 2 触发条件检测
// ============================================================================

/**
 * 检测 SPEC 是否需要 Tier 2 验证
 * @param {string} specDir - SPEC 目录路径 (如 spec/changes/stock-panel/)
 * @param {string} projectRoot - 项目根目录
 * @param {string|null} [distManifestPath=null] - 构建产物 manifest 首选探测位
 *   （由调用方 --dist-path 解析得出，与 launch 侧加载的扩展目录同源）；
 *   缺省时回退 <projectRoot>/dist/manifest.json 旧口径
 * @returns {{ triggered: boolean, reasons: string[] }}
 */
export function detectTier2Trigger(specDir, projectRoot, distManifestPath = null) {
  const reasons = [];

  // specDir 归一化为绝对路径：相对路径以 projectRoot 为基准解析（与本函数内 src/、dist
  // 的查找基准一致）。若按进程 cwd 解析，调用方 cwd 与项目根不一致时 .spec.yaml 查找会
  // 静默 miss，requiresTier2 手动标记失效致 Tier 2 验证被静默跳过（code-review item
  // 046316689e6c）；cwd==projectRoot 时解析结果与原行为一致
  specDir = path.isAbsolute(specDir) ? specDir : path.resolve(projectRoot, specDir);

  // 1. 检查 .spec.yaml 中的 requiresTier2 标记
  const specYamlPath = path.join(specDir, '.spec.yaml');
  if (fs.existsSync(specYamlPath)) {
    try {
      const content = fs.readFileSync(specYamlPath, 'utf-8');
      if (/requiresTier2:\s*true/.test(content)) {
        reasons.push('manual: .spec.yaml requiresTier2=true');
      }
    } catch (_) { /* ignore */ }
  }

  // 2. 检查 src/ 中是否有 fetch() 调用
  const srcDir = path.join(projectRoot, 'src');
  if (fs.existsSync(srcDir)) {
    try {
      // 使用 grep 搜索 fetch( 调用（排除 node_modules 目录；代码注释行不排除，接受该误报口径）
      // 数组形式绕开 shell，避免含空格/元字符的路径被拆词或注入
      const result = execFileSync(
        'grep',
        // POSIX ERE 写法（[[:space:]] 而非 GNU 扩展 \s），BSD/macOS grep 下同样生效；
        // 与原 BRE fetch\s*( 在 GNU grep 下匹配行为等价
        ['-rl', '-E', 'fetch[[:space:]]*\\(', srcDir, '--include=*.ts', '--include=*.tsx', '--include=*.js', '--include=*.jsx', '--exclude-dir=node_modules'],
        { encoding: 'utf-8', timeout: 5000 }
      ).trim();
      if (result) {
        const files = result.split('\n').filter(Boolean);
        reasons.push(`fetch: 在 ${files.length} 个文件中发现 fetch() 调用`);
      }
    } catch (_) { /* ignore */ }
  }

  // 3. 检查 manifest.json 中的 host_permissions
  // 首选探测位取调用方 --dist-path 解析出的 manifest（与 launch 侧加载的扩展目录同源）：
  // --dist-path 指向非 dist 命名目录（如 ./build）时，<root>/dist/manifest.json 不存在，
  // 下方 altPaths（根目录、public/）也都不命中，host_permissions 信号会静默失效，
  // Tier 2 可能因缺该信号而 triggered=false、验证被跳过（code-review item 7507866cc878）
  const manifestPath = distManifestPath || path.join(projectRoot, 'dist', 'manifest.json');
  if (!fs.existsSync(manifestPath)) {
    // 兼容回退：项目根目录与 public/ 下的 manifest
    const altPaths = [
      path.join(projectRoot, 'manifest.json'),
      path.join(projectRoot, 'public', 'manifest.json'),
    ];
    for (const p of altPaths) {
      if (fs.existsSync(p)) {
        checkManifestHostPermissions(p, reasons);
        break;
      }
    }
  } else {
    checkManifestHostPermissions(manifestPath, reasons);
  }

  return {
    triggered: reasons.length > 0,
    reasons,
  };
}

function checkManifestHostPermissions(manifestPath, reasons) {
  try {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    const hostPermissions = manifest.host_permissions || [];
    // 过滤掉通配符域名（如 <all_urls>），只检查具体的外部域名；
    // 回环豁免与采集侧 isLocalHostname 收敛为同一口径（code-review item
    // 5f5e0e726788）：解析 match pattern 的 host 段（scheme://host/path，去端口）
    // 后判定，避免 http://127.0.0.1/*、http://[::1]/* 这类纯本机权限被判为外部域名
    const externalHosts = hostPermissions.filter(h => {
      if (!h.includes('://') || h.includes('<all_urls>')) return false;
      // 非 http(s)/ws(s) scheme（file:、chrome-extension:、urn: 等）不指向外部域名；
      // scheme 为 * 的 match pattern（*://host/path，等价 http/https）仍按域名判定
      const scheme = h.split('://')[0].toLowerCase();
      if (scheme !== '*' && !/^(https?|wss?)$/.test(scheme)) return false;
      let host = (h.split('://')[1] || '').split('/')[0];
      if (host.startsWith('[')) {
        // [::1]:8080 形态取方括号内主机（isLocalHostname 自行去括号归一化）
        const end = host.indexOf(']');
        if (end >= 0) host = host.slice(0, end + 1);
      } else if (host.includes(':')) {
        // 普通主机去端口后再判定（localhost:8080、127.0.0.1:9944 等）
        host = host.slice(0, host.lastIndexOf(':'));
      }
      // 通配 host 段（file:///*、http://*/*、*://*/* 解析出的 *）不指向具体外部域名，
      // 显式排除，避免纯本地文件类扩展被落进 Tier 2 触发理由；*.example.com 等
      // 子域通配仍计为外部域名（方向保守，多验不漏验）
      if (host === '*') return false;
      return host.length > 0 && !isLocalHostname(host);
    });
    if (externalHosts.length > 0) {
      reasons.push(`host_permissions: ${externalHosts.join(', ')}`);
    }
  } catch (_) { /* ignore */ }
}

// ============================================================================
// 入口
// ============================================================================

async function main() {
  const opts = parseArgs();

  // 处理特殊命令（--detect 已在 parseArgs 注册并完成缺值校验，specDir 取自 opts.detect）
  if (opts.detect) {
    const absoluteDist = opts.distPath ? path.resolve(opts.distPath) : null;
    const projectRoot = absoluteDist ? path.dirname(absoluteDist) : process.cwd();
    // manifest 首选探测位与 launch 侧加载的扩展目录同源（同用 path.resolve(distPath) 解析）
    const result = detectTier2Trigger(
      opts.detect,
      projectRoot,
      absoluteDist ? path.join(absoluteDist, 'manifest.json') : null
    );
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  const result = await launchChromeExtension(opts.distPath, opts);

  // 输出
  const jsonOutput = JSON.stringify(result, null, 2);
  if (opts.output) {
    const outputPath = path.resolve(opts.output);
    const outputDir = path.dirname(outputPath);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    fs.writeFileSync(outputPath, jsonOutput, 'utf-8');
    console.log(`结果已写入: ${outputPath}`);
  } else {
    console.log(jsonOutput);
  }

  // 用 process.exitCode 而非 process.exit：stdout 为管道时写入是异步的，process.exit
  // 不等待待写缓冲排空即终止进程，大体积 JSON（含 networkLog）可能被截断致下游解析失败；
  // 设 exitCode 让进程自然排空缓冲后退出，退出码语义不变（--output 落盘分支是同步写入，不受影响）
  process.exitCode = result.success ? 0 : 1;
}

// 直接运行时执行 main（realpath 对比，兼容经改名软链调用）
let isMainModule = false;
if (process.argv[1]) {
  try {
    isMainModule = fs.realpathSync(process.argv[1]) === fs.realpathSync(__filename);
  } catch {
    isMainModule = false;
  }
}

if (isMainModule) {
  main().catch(err => {
    console.error(JSON.stringify({
      success: false,
      extensionLoaded: false,
      networkLog: [],
      anomalies: [],
      duration: 0,
      error: err.message || String(err),
    }, null, 2));
    process.exit(1);
  });
}
