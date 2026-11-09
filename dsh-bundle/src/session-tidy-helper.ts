/**
 * session-tidy-helper.ts — dsh web 会话归档 CLI helper
 * （spec: add-dsh-session-title-archive；design D2：daemon 以子进程调用，
 * 不手搓 WS 帧协议）。
 *
 * 协议面（2026-11-09 以安装版 SDK 源码逐行核实，探针实测见
 * docs/probe-findings.md「session-tidy 归档通道」章）：
 * - **Unary RPC 走 HTTP POST 而非 WebSocket**：SDK 浏览器 caller
 *   （dsh-client-connection createWebConnectionRpc）把每次 unary 调用发为
 *   `POST <base>/api/<namespace>/<method>`，body 为官方 envelope
 *   `{type:"client-request", rpcId, method, payload:{args}}`；返回
 *   `{type:"server-response", rpcId, result:{ok,value|error}}`。
 *   `/api/remote.mux` WebSocket 只承载 stream 方法；archiveSession 是 unary
 *   （dsh-api-workspace-controller typert.host.js 描述符），走 POST 即官方
 *   传输形态——零 Typert 帧编解码、零 cordis 客户端栈引导。
 * - **鉴权 = 浏览器签名 cookie**：dsh-client-connection BrowserAuth 以
 *   `.credentials.yaml` 的 `records.client-connection/browser-session`
 *   grant（base64url 32B secret）为签名密钥；cookie 名
 *   `dsh-auth-<base64url(sha256(authority))>`，值 `v1.<b64url(payload)>.<b64url(HMAC)>`，
 *   payload `{version:1, authority, issuedAt, expiresAt}`（键序敏感）。
 *   daemon 同主机可读凭据文件，helper 本地铸短 TTL cookie（1h，落在任何
 *   合法 cookieMaxAgeDays 配置的校验窗内），无需浏览器与 launch token。
 *   「The HTTP carrier accepts no query token outside the root exchange and
 *   no Authorization-header token」——cookie 是唯一程序化接入面。
 * - **幂等**：宿主 workspaceRegistry.archiveSession 对已归档 id 直接 no-op
 *   返回（源码首检查 `archivedSessionIds.includes → return`），helper 按
 *   成功退出 0。`session/not-found`（live+持久化均无此会话，明确 miss）与
 *   `workspace/session-active`（活动工作在身）为宿主仅有的两类拒绝。
 *
 * 退出码三分类（design D2）：
 *   0 = 成功（含已归档幂等）；outcome "archived"
 *   2 = 可重试（连接失败 / 超时 / workspace-session-active / 5xx）；outcome "retryable"
 *   1 = 致命（凭据缺失或不可读 / 鉴权被拒 / 协议错 / session-not-found）；outcome "fatal"
 *
 * stdout 恒为单行 JSON：`{ok, session_id, outcome, detail}`（供 daemon 侧
 * 解析留痕；诊断细节一律走 detail，不写 stderr 之外的通道）。
 */

import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import yaml from "js-yaml";

/** 退出码：成功（含幂等）。 */
export const EXIT_OK = 0;
/** 退出码：致命（凭据缺失/鉴权被拒/协议错/session-not-found——重试无意义）。 */
export const EXIT_FATAL = 1;
/** 退出码：可重试（连接失败/超时/session-active/5xx）。 */
export const EXIT_RETRYABLE = 2;

/** 浏览器会话 cookie 前缀与 payload 版本（BrowserAuth 常量，逐字对齐）。 */
const COOKIE_PREFIX = "dsh-auth-";
const COOKIE_PAYLOAD_VERSION = 1;
const SECRET_BYTES = 32;

/** 宿主端点（dsh-api-workspace-controller#workspace/archiveSession）。 */
const ENDPOINT = "workspace/archiveSession";

/** helper 结果（stdout 单行 JSON 形状）。 */
export interface TidyResult {
  ok: boolean;
  session_id: string;
  outcome: "archived" | "retryable" | "fatal";
  detail: string;
}

// ── base64url（形态对齐 BrowserAuth encodeBase64Url/decodeBase64Url）───────

function encodeBase64Url(value: Buffer): string {
  return value.toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function decodeBase64Url(value: string): Buffer | undefined {
  if (!/^[A-Za-z0-9_-]*$/u.test(value) || value.length % 4 === 1) return undefined;
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const decoded = Buffer.from(value.replaceAll("-", "+").replaceAll("_", "/") + padding, "base64");
  return encodeBase64Url(decoded) === value ? decoded : undefined;
}

// ── 凭据与 cookie（BrowserAuth 同面机制）────────────────────────────────────

/**
 * 从 `.credentials.yaml` 文本提取 browser-session grant secret（base64url 32B）。
 * 记录键为 credentialKey 产物的斜杠合并形态 `"client-connection/browser-session"`
 * （dsh-credentials credentialKey(scope, id)；2026-11-09 本机凭据文件实测），
 * 兼容嵌套 records["client-connection"]["browser-session"] 形态。
 * 凭据文件可能含任意键名（API key refs 等），整文件 YAML 解析后按已知路径
 * 取值，不做行级正则匹配。形态不符（缺记录/非 grant/secret 非 32B）返回
 * undefined——调用方按致命失败处置并 WARN 留痕（spec：凭据缺失入队 + WARN）。
 */
export function parseBrowserSessionSecret(text: string): string | undefined {
  let doc: unknown;
  try {
    doc = yaml.load(text);
  } catch {
    return undefined;
  }
  const records = (doc as { records?: Record<string, unknown> } | null | undefined)?.records;
  if (records === undefined) return undefined;
  const flat = records["client-connection/browser-session"] as
    | { kind?: unknown; payload?: { version?: unknown; secret?: unknown } }
    | undefined;
  const nested = (records["client-connection"] as Record<string, unknown> | undefined)?.["browser-session"] as
    | { kind?: unknown; payload?: { version?: unknown; secret?: unknown } }
    | undefined;
  const record = flat ?? nested;
  if (record?.kind !== "grant") return undefined;
  const payload = record.payload;
  if (payload?.version !== 1 || typeof payload.secret !== "string") return undefined;
  const secret = decodeBase64Url(payload.secret);
  if (secret === undefined || secret.byteLength !== SECRET_BYTES) return undefined;
  return payload.secret;
}

/** cookie 名（BrowserAuth.cookieName：`dsh-auth-<b64url(sha256(authority))>`）。 */
export function browserAuthCookieName(authority: string): string {
  return COOKIE_PREFIX + encodeBase64Url(createHash("sha256").update(authority).digest());
}

/**
 * 铸造浏览器会话 cookie（BrowserAuth encodeCookie 同构）：HMAC-SHA256 以
 * grant secret（原始 32B）签 base64url(JSON payload)；payload 键序
 * version→authority→issuedAt→expiresAt 与宿主验签逐字一致。TTL 缺省 1h——
 * 宿主校验 `expiresAt-issuedAt <= cookieMaxAgeDays`，任何合法配置（≥1 天）
 * 均在窗内。
 */
export function mintBrowserAuthCookie(
  secretB64Url: string,
  authority: string,
  now = Date.now(),
  ttlMilliseconds = 3600_000,
): string {
  const secret = decodeBase64Url(secretB64Url);
  if (secret === undefined || secret.byteLength !== SECRET_BYTES) {
    throw new Error("browser-session secret 不是 base64url 32B 形态");
  }
  const payload = {
    version: COOKIE_PAYLOAD_VERSION,
    authority,
    issuedAt: now,
    expiresAt: now + ttlMilliseconds,
  };
  const body = encodeBase64Url(Buffer.from(JSON.stringify(payload), "utf8"));
  const signature = createHmac("sha256", secret).update(body).digest();
  return `${browserAuthCookieName(authority)}=v1.${body}.${encodeBase64Url(signature)}`;
}

// ── 归档 RPC（unary HTTP POST，官方 client-request envelope）───────────────

export interface ArchiveInvocation {
  /** dsh web 基址（如 http://127.0.0.1:3080）。 */
  url: string;
  /** browser-session grant secret（base64url 32B）。 */
  secret: string;
  /** 待归档 dsh 会话 id。 */
  sessionId: string;
  /** 单次调用超时（毫秒）。 */
  timeoutMilliseconds: number;
}

export interface ArchiveOutcome {
  exitCode: typeof EXIT_OK | typeof EXIT_FATAL | typeof EXIT_RETRYABLE;
  result: TidyResult;
}

/**
 * 经 dsh web HTTP API 调 `workspace/archiveSession`。绝不抛异常：一切失败
 * 折进退出码 + TidyResult（daemon 侧按子进程退出码分类处置）。
 */
export async function invokeArchiveSession(invocation: ArchiveInvocation): Promise<ArchiveOutcome> {
  const { sessionId } = invocation;
  const done = (exitCode: ArchiveOutcome["exitCode"], outcome: TidyResult["outcome"], detail: string): ArchiveOutcome => ({
    exitCode,
    result: { ok: exitCode === EXIT_OK, session_id: sessionId, outcome, detail },
  });
  let base: URL;
  try {
    base = new URL(invocation.url);
  } catch {
    return done(EXIT_FATAL, "fatal", `--url 非法：${JSON.stringify(invocation.url)}`);
  }
  if (base.pathname !== "/" && base.pathname !== "") {
    return done(EXIT_FATAL, "fatal", `--url 不应携带路径（收到 ${base.pathname}）`);
  }
  const origin = base.origin;
  // authority = 宿主看到的 Host 头（fetch 由 URL 取 host:port），cookie 名与
  // 签名 audience 均绑定它（BrowserAuth requestAuthority）。
  const authority = base.host;
  let cookie: string;
  try {
    cookie = mintBrowserAuthCookie(invocation.secret, authority);
  } catch (err) {
    return done(EXIT_FATAL, "fatal", `cookie 铸造失败：${err instanceof Error ? err.message : String(err)}`);
  }
  // envelope 形状 = createWebConnectionRpc.call 逐字对齐；args 键名取
  // typert 描述符 parameters[0].name === "request"。
  const rpcId = randomUUID();
  const message = {
    type: "client-request",
    rpcId,
    method: ENDPOINT,
    payload: { args: { request: { sessionId } } },
  };
  const controller = new AbortController();
  const timer = setTimeout(() => void controller.abort(new Error("timeout")), Math.max(1, invocation.timeoutMilliseconds));
  let response: Response;
  try {
    response = await fetch(`${origin}/api/${ENDPOINT}`, {
      method: "POST",
      headers: { "content-type": "application/json", cookie },
      body: JSON.stringify(message),
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    const aborted = controller.signal.aborted;
    return done(
      EXIT_RETRYABLE,
      "retryable",
      aborted ? `连接超时（>${invocation.timeoutMilliseconds}ms）` : `连接失败：${err instanceof Error ? err.message : String(err)}`,
    );
  }
  clearTimeout(timer);
  if (!response.ok) {
    // 401/403：鉴权被拒（凭据被轮换/形态不符）——重试同样被拒，按致命。
    // 404：端点不在场（web 版本漂移/反代错位）——按致命。5xx：宿主瞬态。
    if (response.status >= 500) {
      return done(EXIT_RETRYABLE, "retryable", `HTTP ${response.status}（宿主瞬态，稍后重试）`);
    }
    return done(EXIT_FATAL, "fatal", `HTTP ${response.status}（${response.status === 401 || response.status === 403 ? "鉴权被拒" : "请求被拒"}）`);
  }
  let envelope: { type?: unknown; rpcId?: unknown; result?: { ok?: unknown; value?: unknown; error?: { code?: unknown; message?: unknown } } };
  try {
    envelope = JSON.parse(await response.text());
  } catch {
    return done(EXIT_FATAL, "fatal", "响应非 JSON（协议错）");
  }
  if (
    envelope?.type !== "server-response" ||
    typeof envelope.rpcId !== "string" ||
    envelope.rpcId !== rpcId ||
    typeof envelope.result !== "object" ||
    envelope.result === null
  ) {
    return done(EXIT_FATAL, "fatal", "响应非 server-response envelope / rpcId 不匹配（协议错）");
  }
  const result = envelope.result;
  if (result.ok === true) {
    return done(EXIT_OK, "archived", "已归档（含已归档幂等 no-op）");
  }
  const code = typeof result.error?.code === "string" ? result.error.code : "";
  const errorMessage = typeof result.error?.message === "string" ? result.error.message : "";
  // workspace/session-active：宿主拒绝（活动工作在身；run 已终态时为短暂
  // 竞态窗）——按 spec「稍后重试」。session/not-found：live+持久化均无此
  // 会话（明确 miss， retention 清理后常见）——重试永不成功，按致命。
  // 其余未知码一律致命（重试预算不该为未知语义空转）。
  if (code === "workspace/session-active") {
    return done(EXIT_RETRYABLE, "retryable", `workspace/session-active：${errorMessage}`);
  }
  return done(EXIT_FATAL, "fatal", code ? `${code}：${errorMessage}` : `宿主错误（无码）：${errorMessage}`);
}

// ── CLI（design D2：daemon 子进程调用面）───────────────────────────────────

export interface CliOptions {
  url: string;
  secretFile: string;
  sessionId: string;
  timeoutSeconds: number;
}

/** 参数解析：缺参/缺值返回 null（main 按致命处置并输出 usage）。 */
export function parseArgs(argv: readonly string[]): CliOptions | null {
  const values = new Map<string, string>();
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const aliases: Record<string, string> = {
      "--url": "url",
      "--secret-file": "secretFile",
      "--session-id": "sessionId",
      "--timeout": "timeoutSeconds",
    };
    const key = aliases[arg];
    if (key === undefined) return null;
    const value = argv[i + 1];
    if (value === undefined || value.startsWith("--")) return null;
    values.set(key, value);
    i += 1;
  }
  const url = values.get("url");
  const secretFile = values.get("secretFile");
  const sessionId = values.get("sessionId");
  if (!url || !secretFile || !sessionId) return null;
  const timeoutSeconds = Number(values.get("timeoutSeconds") ?? "10");
  if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) return null;
  return { url, secretFile, sessionId, timeoutSeconds };
}

const USAGE =
  "用法: node session-tidy-helper.mjs --url <web基址> --secret-file <dsh_home>/.credentials.yaml --session-id <id> [--timeout <秒>]";

/**
 * CLI 主体：读凭据 → 铸 cookie → 调 archiveSession → stdout 单行 JSON +
 * 退出码。永不抛异常（daemon 侧契约：退出码三分类 + 单行 JSON）。
 */
export async function runCli(argv: readonly string[]): Promise<number> {
  const options = parseArgs(argv);
  if (options === null) {
    process.stdout.write(`${JSON.stringify({ ok: false, session_id: "", outcome: "fatal", detail: USAGE })}\n`);
    return EXIT_FATAL;
  }
  let text: string;
  try {
    text = readFileSync(options.secretFile, "utf-8");
  } catch (err) {
    process.stdout.write(
      `${JSON.stringify({
        ok: false,
        session_id: options.sessionId,
        outcome: "fatal",
        detail: `凭据不可读 ${options.secretFile}：${err instanceof Error ? err.message : String(err)}`,
      })}\n`,
    );
    return EXIT_FATAL;
  }
  const secret = parseBrowserSessionSecret(text);
  if (secret === undefined) {
    process.stdout.write(
      `${JSON.stringify({
        ok: false,
        session_id: options.sessionId,
        outcome: "fatal",
        detail: `凭据形态不符：${options.secretFile} 缺 records.client-connection.browser-session grant（或 secret 非 base64url 32B）`,
      })}\n`,
    );
    return EXIT_FATAL;
  }
  const outcome = await invokeArchiveSession({
    url: options.url,
    secret,
    sessionId: options.sessionId,
    timeoutMilliseconds: options.timeoutSeconds * 1000,
  });
  process.stdout.write(`${JSON.stringify(outcome.result)}\n`);
  return outcome.exitCode;
}

/** CLI 直跑入口（dist/session-tidy-helper.mjs；被 import 时不执行）。 */
export async function main(argv: readonly string[] = process.argv.slice(2)): Promise<number> {
  const code = await runCli(argv);
  process.exitCode = code;
  return code;
}

// 以 `node <path>/session-tidy-helper.mjs` 直跑时自执行（vitest/daemon import 本
// 模块复用纯函数面时不触发；dist 下 .js/.mjs 双产物各自与 argv[1] 精确匹配）。
if (
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  void main();
}
