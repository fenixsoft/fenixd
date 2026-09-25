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
 *
 * 输出 JSON:
 *   {
 *     "success": true/false,
 *     "extensionLoaded": true/false,
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
    }
  }

  // 校验参数取值：--timeout 缺值/非数字会得 NaN、0 或负数会使剩余预算恒为 0 立即超时收卷，
  // 造成零验证假通过，故须为正数；带值选项缺值时静默得 undefined
  const usage = '用法: node launch-chrome-extension.js [--dist-path <path>] [--timeout <ms>] [--debug] [--headless] [--output <path>]';
  let invalidReason = null;
  if (!Number.isFinite(opts.timeout) || opts.timeout <= 0) invalidReason = '--timeout 需要正数参数（毫秒，须大于 0）';
  if (opts.distPath === undefined) invalidReason = '--dist-path 缺少取值';
  if (opts.output === undefined) invalidReason = '--output 缺少取值';
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
    host.startsWith('127.') ||
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
  if (!url.startsWith('http')) return false;
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
 */
function checkRequiredHeaders(url, headers) {
  const missing = [];
  const headerKeys = Object.keys(headers || {}).map(k => k.toLowerCase());

  // hq.sinajs.cn 需要 Referer 头
  if (url.includes('hq.sinajs.cn') || url.includes('sina.com.cn')) {
    if (!headerKeys.includes('referer')) {
      missing.push({
        header: 'Referer',
        severity: 'warning',
        suggestion: '建议添加 Referer: https://finance.sina.com.cn',
      });
    }
  }

  return missing;
}

/**
 * 根据状态码确定异常严重级别
 */
function severityFromStatus(status) {
  if (status >= 500) return 'external-service';  // 外部服务异常，不计为代码缺陷
  if (status === 403) return 'high';              // 403 通常是配置问题
  if (status === 401) return 'high';
  if (status === 404) return 'medium';
  if (status >= 400) return 'high';
  return 'low';
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

      anomalies.push({
        type: 'request-failure',
        severity: 'high',
        url: entry.url,
        method: entry.method || 'GET',
        error: entry.error,
        timestamp: entry.timestamp,
        category: isCors ? 'cors' : 'network',
        description: isCors
          ? 'CORS 错误 — 浏览器拦截了跨域请求'
          : `请求失败: ${entry.error}`,
        suggestion: isCors
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

    // 在所有已有页面上设置监听 — 必须在任何等待/开页之前挂载，
    // 否则扩展初始加载窗口内的请求（最关键的外部 API 调用）会漏采
    for (const page of browserContext.pages()) {
      setupNetworkLogging(page, networkLog);
    }

    // 新页面自动添加监听
    browserContext.on('page', (page) => {
      setupNetworkLogging(page, networkLog);
    });

    // ========================================================================
    // 网络采集 + UI 测试 — 受 --timeout 总预算约束，超时后提前收卷已有 networkLog
    // ========================================================================

    let timedOut = false;
    const collectAndTest = async () => {
      // 等待扩展加载 — 扩展接管 newtab 后会自动打开一个新标签页
      // 给扩展一些时间加载
      await new Promise(resolve => setTimeout(resolve, 3000));

      // 无已有页面时兜底开一页（新页面经 browserContext 'page' 事件自动挂网络监听）
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

    const raced = await Promise.race([collectAndTest(), timeoutPromise]);
    clearTimeout(timeoutTimer);
    const uiResults = raced === null ? [] : raced;

    // ========================================================================
    // 收集结果
    // ========================================================================

    const endTime = Date.now();
    const anomalies = detectAnomalies(networkLog);
    const hasCriticalAnomalies = anomalies.some(a =>
      a.severity === 'high' || a.severity === 'critical'
    );

    const result = {
      success: !hasCriticalAnomalies,
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
    return {
      success: false,
      extensionLoaded: false,
      manifestPath,
      networkLog,
      anomalies: detectAnomalies(networkLog),
      duration: endTime - startTime,
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

function setupNetworkLogging(page, networkLog) {
  page.on('request', (req) => {
    if (isExternalUrl(req.url())) {
      networkLog.push({
        type: 'request',
        url: req.url(),
        method: req.method(),
        headers: req.headers(),
        timestamp: Date.now(),
      });
    }
  });

  page.on('response', (res) => {
    if (isExternalUrl(res.url())) {
      networkLog.push({
        type: 'response',
        url: res.url(),
        // 直接从 response 关联的 request 对象取 method：同 URL 并发时按 url 扫描会取错条目，且长采集下为 O(n^2)
        method: res.request().method() || 'GET',
        status: res.status(),
        statusText: res.statusText(),
        headers: res.headers(),
        timestamp: Date.now(),
      });
    }
  });

  page.on('requestfailed', (req) => {
    if (isExternalUrl(req.url())) {
      networkLog.push({
        type: 'failure',
        url: req.url(),
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
    try {
      const panels = await page.$$('[class*="panel"], [class*="widget"], [data-panel]');
      results.push({
        test: '面板渲染',
        status: panels.length > 0 ? 'pass' : 'fail',
        detail: panels.length > 0
          ? `发现 ${panels.length} 个面板`
          : '未发现面板元素',
      });
    } catch (e) {
      results.push({ test: '面板渲染', status: 'error', detail: e.message });
    }

    // 测试 3: 按钮可交互
    try {
      const buttons = await page.$$('button');
      let clickableCount = 0;
      for (const btn of buttons.slice(0, 10)) {
        const isVisible = await btn.isVisible();
        if (isVisible) clickableCount++;
      }
      results.push({
        test: '按钮交互',
        status: buttons.length > 0 ? 'pass' : 'warn',
        detail: buttons.length > 0
          ? `${buttons.length} 个按钮 (${clickableCount} 个可见)`
          : '未发现按钮',
      });
    } catch (e) {
      results.push({ test: '按钮交互', status: 'error', detail: e.message });
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
  // codeDefects 与 success 判定同口径：只计 high/critical（即 hasCriticalAnomalies 的判定范围）
  const codeAnomalies = anomalies.filter(a => a.severity === 'high' || a.severity === 'critical');
  // warning 级问题（如 missing-header）单列，不混入 codeDefects
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
 * @returns {{ triggered: boolean, reasons: string[] }}
 */
export function detectTier2Trigger(specDir, projectRoot) {
  const reasons = [];

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
        ['-rl', 'fetch\\s*(', srcDir, '--include=*.ts', '--include=*.tsx', '--include=*.js', '--include=*.jsx', '--exclude-dir=node_modules'],
        { encoding: 'utf-8', timeout: 5000 }
      ).trim();
      if (result) {
        const files = result.split('\n').filter(Boolean);
        reasons.push(`fetch: 在 ${files.length} 个文件中发现 fetch() 调用`);
      }
    } catch (_) { /* ignore */ }
  }

  // 3. 检查 manifest.json 中的 host_permissions
  const manifestPath = path.join(projectRoot, 'dist', 'manifest.json');
  if (!fs.existsSync(manifestPath)) {
    // 尝试从项目根目录查找
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
    // 过滤掉通配符域名（如 <all_urls>），只检查具体的外部域名
    const externalHosts = hostPermissions.filter(h =>
      h.includes('://') &&
      !h.includes('<all_urls>') &&
      !h.includes('localhost')
    );
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

  // 处理特殊命令
  if (process.argv.includes('--detect')) {
    const specDir = process.argv[process.argv.indexOf('--detect') + 1];
    // --detect 为末位参数时缺第二参数，specDir 为 undefined 会让 path.join 抛 TypeError 落入兜底 catch
    if (specDir === undefined) {
      console.error('错误: --detect 缺少取值\n用法: node launch-chrome-extension.js --detect <spec-dir>');
      process.exit(1);
    }
    const projectRoot = opts.distPath ? path.dirname(path.resolve(opts.distPath)) : process.cwd();
    const result = detectTier2Trigger(specDir, projectRoot);
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

  process.exit(result.success ? 0 : 1);
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
