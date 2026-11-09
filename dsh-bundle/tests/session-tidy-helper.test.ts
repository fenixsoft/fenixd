/**
 * session-tidy-helper.test.ts — 归档 helper 单测 + 集成用例（task 2.3）。
 *
 * 单测：参数解析 / cookie 铸造（名字派生、键序、HMAC）/ 凭据解析（斜杠合并键
 * 与嵌套兼容形态）/ 退出码映射。
 *
 * 集成用例：dsh web 无独立可脚本化的单进程启动面（`dsh web` 是完整宿主栈），
 * 故以**最小 HTTP stub 复现 gateway invoke 面**（unary POST envelope +
 * BrowserAuth 验签同名 cookie）——与真实宿主的差异仅在于不跑完整 workspace
 * domain write chain；帧形状、cookie 名/签名、退出码映射均为真机探针
 * （auth-probe.test.ts 对真实 web）核实过的同一形状（probe-findings.md §7）。
 */
import { createHmac, createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse, type Server } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  EXIT_FATAL,
  EXIT_OK,
  EXIT_RETRYABLE,
  invokeArchiveSession,
  mintBrowserAuthCookie,
  browserAuthCookieName,
  parseArgs,
  parseBrowserSessionSecret,
  runCli,
} from "../src/session-tidy-helper.ts";

// ── 参数解析 ────────────────────────────────────────────────────────────────

describe("parseArgs", () => {
  it("全参解析：url/secret-file/session-id/timeout", () => {
    expect(
      parseArgs(["--url", "http://127.0.0.1:3080", "--secret-file", "/root/.dsh/.credentials.yaml", "--session-id", "s1", "--timeout", "5"]),
    ).toEqual({ url: "http://127.0.0.1:3080", secretFile: "/root/.dsh/.credentials.yaml", sessionId: "s1", timeoutSeconds: 5 });
  });

  it("timeout 缺省 10；未知参数/缺值/非法超时均拒绝", () => {
    expect(parseArgs(["--url", "u", "--secret-file", "f", "--session-id", "s"])?.timeoutSeconds).toBe(10);
    expect(parseArgs(["--url", "u", "--secret-file", "f"])).toBeNull(); // 缺 session-id
    expect(parseArgs(["--url", "u", "--secret-file", "f", "--session-id"])).toBeNull(); // 缺值
    expect(parseArgs(["--url", "u", "--secret-file", "f", "--session-id", "s", "--bogus", "x"])).toBeNull();
    expect(parseArgs(["--url", "u", "--secret-file", "f", "--session-id", "s", "--timeout", "0"])).toBeNull();
    expect(parseArgs(["--url", "u", "--secret-file", "f", "--session-id", "s", "--timeout", "abc"])).toBeNull();
  });
});

// ── cookie 铸造（BrowserAuth 同构）─────────────────────────────────────────

/** 测试用固定 32B secret（base64url）。 */
const SECRET_B64URL = Buffer.alloc(32, 7).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");

describe("mintBrowserAuthCookie", () => {
  it("名字派生：dsh-auth-<b64url(sha256(authority))>", () => {
    const authority = "127.0.0.1:3080";
    const expected = "dsh-auth-" + Buffer.from(createHash("sha256").update(authority).digest()).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
    expect(browserAuthCookieName(authority)).toBe(expected);
  });

  it("值形状：v1.<b64url(payload)>.<b64url(hmac)>，payload 键序 version→authority→issuedAt→expiresAt", () => {
    const now = 1_700_000_000_000;
    const cookie = mintBrowserAuthCookie(SECRET_B64URL, "127.0.0.1:3080", now, 3600_000);
    const [name, value] = cookie.split("=");
    expect(name).toBe(browserAuthCookieName("127.0.0.1:3080"));
    const [version, body, sig] = value.split(".");
    expect(version).toBe("v1");
    const secret = Buffer.from(SECRET_B64URL.replaceAll("-", "+").replaceAll("_", "/"), "base64");
    const expectedSig = createHmac("sha256", secret).update(body).digest().toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
    expect(sig).toBe(expectedSig);
    const padding = "=".repeat((4 - (body.length % 4)) % 4);
    const payload = JSON.parse(Buffer.from(body.replaceAll("-", "+").replaceAll("_", "/") + padding, "base64").toString("utf-8"));
    // JSON.parse 保留插入序：版本、authority、issuedAt、expiresAt（与宿主 decodeCookie 验签一致）。
    expect(Object.keys(payload)).toEqual(["version", "authority", "issuedAt", "expiresAt"]);
    expect(payload).toEqual({ version: 1, authority: "127.0.0.1:3080", issuedAt: now, expiresAt: now + 3600_000 });
  });

  it("secret 非 base64url 32B 即抛错", () => {
    expect(() => mintBrowserAuthCookie(Buffer.alloc(16).toString("base64url"), "a")).toThrow();
    expect(() => mintBrowserAuthCookie("not-base64url!!", "a")).toThrow();
  });
});

// ── 凭据解析 ────────────────────────────────────────────────────────────────

describe("parseBrowserSessionSecret", () => {
  const secretValue = Buffer.alloc(32, 9).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");

  it("斜杠合并单键形态（本机凭据实测形态）", () => {
    const text = ["version: 1", "records:", "  client-connection/browser-session:", "    kind: grant", "    payload:", "      version: 1", `      secret: ${secretValue}`, "refs:", "  SOME_KEY: abc"].join("\n");
    expect(parseBrowserSessionSecret(text)).toBe(secretValue);
  });

  it("嵌套键形态兼容", () => {
    const text = ["records:", "  client-connection:", "    browser-session:", "      kind: grant", "      payload:", "        version: 1", `        secret: ${secretValue}`].join("\n");
    expect(parseBrowserSessionSecret(text)).toBe(secretValue);
  });

  it("缺记录/非 grant/secret 形态不符 → undefined", () => {
    expect(parseBrowserSessionSecret("records: {}")).toBeUndefined();
    expect(parseBrowserSessionSecret("not-yaml: [")).toBeUndefined();
    expect(
      parseBrowserSessionSecret(["records:", "  client-connection/browser-session:", "    kind: other", "    payload:", "      version: 1", `      secret: ${secretValue}`].join("\n")),
    ).toBeUndefined();
    expect(
      parseBrowserSessionSecret(["records:", "  client-connection/browser-session:", "    kind: grant", "    payload:", "      version: 1", "      secret: tooshort"].join("\n")),
    ).toBeUndefined();
  });
});

// ── 集成：最小 HTTP stub 复现 gateway invoke 面 ────────────────────────────

interface StubOptions {
  /** 响应策略：ok / session-active / not-found / 401 / 500 / envelope 破损 / rpcId 不匹配 / 慢响应。 */
  behavior: "ok" | "session-active" | "not-found" | "401" | "500" | "bad-envelope" | "rpc-id-mismatch" | "slow";
  /** 校验收到的请求形状（cookie 名/值形状、body envelope）。 */
  onRequest?: (req: IncomingMessage, body: string) => void;
}

/** 起最小 stub（localhost 随机端口）：POST /api/workspace/archiveSession 按脚本响应（回显请求 rpcId，rpc-id-mismatch 例外）。 */
async function startStub(options: StubOptions): Promise<{ server: Server; url: string; seen: { cookie: string | undefined; body: string } }> {
  const seen: { cookie: string | undefined; body: string } = { cookie: undefined, body: "" };
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    let chunks = "";
    req.on("data", (c: Buffer) => void (chunks += c.toString("utf-8")));
    req.on("end", () => {
      seen.cookie = req.headers.cookie;
      seen.body = chunks;
      options.onRequest?.(req, chunks);
      const respond = (status: number, payload: unknown): void => {
        res.writeHead(status, { "content-type": "application/json" });
        res.end(JSON.stringify(payload));
      };
      // 真实宿主回显请求 rpcId；stub 同构（rpc-id-mismatch 行为除外）。
      let requestRpcId = "";
      try {
        requestRpcId = String((JSON.parse(chunks) as { rpcId?: unknown }).rpcId ?? "");
      } catch {
        requestRpcId = "";
      }
      switch (options.behavior) {
        case "ok":
          respond(200, { type: "server-response", rpcId: requestRpcId, result: { ok: true, value: { archivedSessionIds: ["s1"] } } });
          break;
        case "session-active":
          respond(200, { type: "server-response", rpcId: requestRpcId, result: { ok: false, error: { code: "workspace/session-active", message: "turn in flight", details: {} } } });
          break;
        case "not-found":
          respond(200, { type: "server-response", rpcId: requestRpcId, result: { ok: false, error: { code: "session/not-found", message: "no such session", details: {} } } });
          break;
        case "401":
          res.writeHead(401, { "content-type": "text/plain" });
          res.end("dsh web authentication required");
          break;
        case "500":
          respond(500, { error: "boom" });
          break;
        case "bad-envelope":
          respond(200, { hello: "world" });
          break;
        case "rpc-id-mismatch":
          respond(200, { type: "server-response", rpcId: `other-${requestRpcId}`, result: { ok: true, value: {} } });
          break;
        case "slow":
          // 10s 后才响应：任何 ≤5s 超时都会先触发 abort。
          setTimeout(() => respond(200, { type: "server-response", rpcId: requestRpcId, result: { ok: true, value: {} } }), 10_000);
          break;
      }
    });
  });
  await new Promise<void>((resolve) => void server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const port = typeof address === "object" && address !== null ? address.port : 0;
  return { server, url: `http://127.0.0.1:${port}`, seen };
}

/** 集成桩共用的临时凭据文件（斜杠合并键形态）。 */
const STUB_SECRET = Buffer.alloc(32, 11).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");

const tempDirs: string[] = [];
function tempCredentialsFile(): string {
  const dir = mkdtempSync(join(tmpdir(), "tidy-helper-"));
  tempDirs.push(dir);
  const file = join(dir, ".credentials.yaml");
  writeFileSync(
    file,
    ["version: 1", "records:", "  client-connection/browser-session:", "    kind: grant", "    payload:", "      version: 1", `      secret: ${STUB_SECRET}`].join("\n"),
  );
  return file;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("invokeArchiveSession（最小 gateway stub）", () => {
  it("成功：envelope 形状正确、cookie 在场、退出码 0", async () => {
    const assertions: { cookie: boolean; bodyShape: boolean } = { cookie: false, bodyShape: false };
    const { server, url, seen } = await startStub({
      behavior: "ok",
      onRequest: (_req, body) => {
        // cookie 名 = dsh-auth-<b64url(sha256(authority))>；值形状 v1.x.y。
        assertions.cookie = (seen.cookie ?? "").startsWith(browserAuthCookieName(new URL(url).host) + "=v1.");
        const message = JSON.parse(body);
        assertions.bodyShape =
          message.type === "client-request" &&
          typeof message.rpcId === "string" &&
          message.method === "workspace/archiveSession" &&
          message.payload?.args?.request?.sessionId === "s1";
      },
    });
    try {
      const outcome = await invokeArchiveSession({ url, secret: STUB_SECRET, sessionId: "s1", timeoutMilliseconds: 3000 });
      expect(outcome.exitCode).toBe(EXIT_OK);
      expect(outcome.result).toEqual({ ok: true, session_id: "s1", outcome: "archived", detail: expect.any(String) });
      expect(assertions.cookie).toBe(true);
      expect(assertions.bodyShape).toBe(true);
    } finally {
      server.close();
    }
  });

  it("session-active → 2 retryable；not-found → 1 fatal", async () => {
    const a = await startStub({ behavior: "session-active" });
    try {
      const outcome = await invokeArchiveSession({ url: a.url, secret: STUB_SECRET, sessionId: "s1", timeoutMilliseconds: 3000 });
      expect(outcome.exitCode).toBe(EXIT_RETRYABLE);
      expect(outcome.result.outcome).toBe("retryable");
      expect(outcome.result.detail).toContain("workspace/session-active");
    } finally {
      a.server.close();
    }
    const b = await startStub({ behavior: "not-found" });
    try {
      const outcome = await invokeArchiveSession({ url: b.url, secret: STUB_SECRET, sessionId: "s2", timeoutMilliseconds: 3000 });
      expect(outcome.exitCode).toBe(EXIT_FATAL);
      expect(outcome.result.detail).toContain("session/not-found");
    } finally {
      b.server.close();
    }
  });

  it("401/协议错 → 1 fatal；500 → 2 retryable", async () => {
    const a = await startStub({ behavior: "401" });
    try {
      expect((await invokeArchiveSession({ url: a.url, secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 3000 })).exitCode).toBe(EXIT_FATAL);
    } finally {
      a.server.close();
    }
    const b = await startStub({ behavior: "500" });
    try {
      expect((await invokeArchiveSession({ url: b.url, secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 3000 })).exitCode).toBe(EXIT_RETRYABLE);
    } finally {
      b.server.close();
    }
    const c = await startStub({ behavior: "bad-envelope" });
    try {
      expect((await invokeArchiveSession({ url: c.url, secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 3000 })).exitCode).toBe(EXIT_FATAL);
    } finally {
      c.server.close();
    }
    const d = await startStub({ behavior: "rpc-id-mismatch" });
    try {
      expect((await invokeArchiveSession({ url: d.url, secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 3000 })).exitCode).toBe(EXIT_FATAL);
    } finally {
      d.server.close();
    }
  });

  it("超时 → 2 retryable；连接拒绝 → 2 retryable", async () => {
    const a = await startStub({ behavior: "slow" });
    try {
      const outcome = await invokeArchiveSession({ url: a.url, secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 300 });
      expect(outcome.exitCode).toBe(EXIT_RETRYABLE);
      expect(outcome.result.detail).toContain("超时");
    } finally {
      a.server.close();
    }
    const outcome = await invokeArchiveSession({ url: "http://127.0.0.1:9", secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 2000 });
    expect(outcome.exitCode).toBe(EXIT_RETRYABLE);
    expect(outcome.result.detail).toContain("连接失败");
  });

  it("非法 url → 1 fatal（不发起请求）", async () => {
    const outcome = await invokeArchiveSession({ url: "not-a-url", secret: STUB_SECRET, sessionId: "s", timeoutMilliseconds: 1000 });
    expect(outcome.exitCode).toBe(EXIT_FATAL);
    expect(outcome.result.detail).toContain("--url 非法");
  });
});

describe("runCli（CLI 契约：单行 JSON + 退出码）", () => {
  it("成功路径：stdout 单行 JSON、exit 0", async () => {
    const { server, url } = await startStub({ behavior: "ok" });
    const file = tempCredentialsFile();
    const writes: string[] = [];
    const originalWrite = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string | Uint8Array) => {
      writes.push(String(chunk));
      return true;
    }) as typeof process.stdout.write;
    let code = -1;
    try {
      code = await runCli(["--url", url, "--secret-file", file, "--session-id", "s1", "--timeout", "3"]);
    } finally {
      process.stdout.write = originalWrite;
      server.close();
    }
    expect(code).toBe(EXIT_OK);
    expect(writes).toHaveLength(1);
    const parsed = JSON.parse(writes[0]) as { ok: boolean; session_id: string; outcome: string };
    expect(parsed).toMatchObject({ ok: true, session_id: "s1", outcome: "archived" });
  });

  it("凭据缺失：fatal + usage 单行 JSON", async () => {
    const writes: string[] = [];
    const originalWrite = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string | Uint8Array) => {
      writes.push(String(chunk));
      return true;
    }) as typeof process.stdout.write;
    let code = -1;
    try {
      code = await runCli(["--url", "http://127.0.0.1:3080", "--secret-file", "/nonexistent/credentials.yaml", "--session-id", "s"]);
    } finally {
      process.stdout.write = originalWrite;
    }
    expect(code).toBe(EXIT_FATAL);
    expect(JSON.parse(writes[0])).toMatchObject({ ok: false, outcome: "fatal" });
    expect(JSON.parse(writes[0]).detail).toContain("凭据不可读");
  });
});
