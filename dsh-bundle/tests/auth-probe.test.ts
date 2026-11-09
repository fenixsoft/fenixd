/**
 * auth-probe.test.ts — dsh web 归档通道鉴权打通探针（task 2.1）。
 *
 * 以本机真实 dsh web（缺省 http://127.0.0.1:3080）核实握手精确形态：cookie
 * 名 / 签名 / authority 绑定均按 SDK 源码（dsh-client-connection BrowserAuth）
 * 实现（见 src/session-tidy-helper.ts 头注与 docs/probe-findings.md）。
 *
 * 安全纪律：对真实 web 只做**零变更调用**——archiveSession 目标取 registry
 * 已归档 id（宿主首检查 `archivedSessionIds.includes → no-op`，不落任何写）；
 * 断言响应集合 ⊇ 调前 registry 集合（未发生变更）。凭据与 registry 文件或
 * web 不可达时明确 skip 留痕（无真实环境的部署零噪音）。
 *
 * 探针目标与凭据可经 env 覆盖（FENIX_DSH_PROBE_URL / FENIX_DSH_PROBE_HOME），
 * 缺省对齐本部署（/root/.dsh、127.0.0.1:3080）。
 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { mintBrowserAuthCookie, parseBrowserSessionSecret } from "../src/session-tidy-helper.ts";

const DSH_HOME = process.env.FENIX_DSH_PROBE_HOME ?? "/root/.dsh";
const WEB_URL = process.env.FENIX_DSH_PROBE_URL ?? "http://127.0.0.1:3080";
const CREDENTIALS_FILE = join(DSH_HOME, ".credentials.yaml");
const REGISTRY_FILE = join(DSH_HOME, "storages", "workspace.json");

const filesPresent = existsSync(CREDENTIALS_FILE) && existsSync(REGISTRY_FILE);

/** 环境自检：文件齐备且 web 在线（401 门在位）才跑探针；否则 skip 留痕。 */
async function probeReady(): Promise<{ secret: string; authority: string; archivedIds: string[] } | null> {
  if (!filesPresent) return null;
  let online = false;
  try {
    const res = await fetch(`${WEB_URL}/`, { signal: AbortSignal.timeout(4000) });
    // 鉴权门在场（无 cookie 401）即视为 web 在线；200 也接受（未启用鉴权门
    // 的旧版 web 同样可探）。
    online = res.status === 401 || res.ok;
  } catch {
    online = false;
  }
  if (!online) return null;
  const secret = parseBrowserSessionSecret(readFileSync(CREDENTIALS_FILE, "utf-8"));
  if (secret === undefined) return null;
  const registry = JSON.parse(readFileSync(REGISTRY_FILE, "utf-8")) as {
    global?: { archivedSessionIds?: string[] };
  };
  const archivedIds = registry.global?.archivedSessionIds ?? [];
  return { secret, authority: new URL(WEB_URL).host, archivedIds };
}

const probe = await probeReady();

/** skip 原因留痕（探针组被跳过时由此组断言非空，证明是明确跳过而非漏跑）。 */
const skipReason = (() => {
  if (!filesPresent) {
    const missing = [!existsSync(CREDENTIALS_FILE) ? CREDENTIALS_FILE : null, !existsSync(REGISTRY_FILE) ? REGISTRY_FILE : null]
      .filter((p): p is string => p !== null);
    return `凭据/registry 文件缺失：${missing.join(", ")}`;
  }
  if (probe === null) return "web 不可达（探针自检未通过）或凭据形态不符";
  return "";
})();

describe.skipIf(probe === null)("dsh web 归档通道探针（真实 web）", () => {
  // describe 工厂体在 collection 期即执行（skip 判定不拦截工厂体），此处
  // 防御性早退避免 probe 为 null 时解引用崩溃。
  if (probe === null) return;
  const secret = probe.secret;
  const authority = probe.authority;
  const archivedIds = probe.archivedIds;
  const cookie = mintBrowserAuthCookie(secret, authority);

  it("鉴权门在位：无 cookie 访问 / 与归档端点均被 401 拒绝", async () => {
    const index = await fetch(`${WEB_URL}/`, { signal: AbortSignal.timeout(4000) });
    expect(index.status).toBe(401);
    const rpc = await fetch(`${WEB_URL}/api/workspace/archiveSession`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "client-request", rpcId: "probe-unauth", method: "workspace/archiveSession", payload: { args: { request: { sessionId: "probe" } } } }),
      signal: AbortSignal.timeout(4000),
    });
    expect(rpc.status).toBe(401);
  });

  it.skipIf(archivedIds.length === 0)("铸造 cookie 过鉴权：对已归档 id 调 archiveSession 幂等 no-op（零变更）", async () => {
    const rpcId = `probe-${Date.now()}`;
    const res = await fetch(`${WEB_URL}/api/workspace/archiveSession`, {
      method: "POST",
      headers: { "content-type": "application/json", cookie },
      body: JSON.stringify({
        type: "client-request",
        rpcId,
        method: "workspace/archiveSession",
        payload: { args: { request: { sessionId: archivedIds[0] } } },
      }),
      signal: AbortSignal.timeout(8000),
    });
    expect(res.status).toBe(200);
    const envelope = (await res.json()) as { type: string; rpcId: string; result: { ok: boolean; value?: { archivedSessionIds?: string[] } } };
    expect(envelope.type).toBe("server-response");
    expect(envelope.rpcId).toBe(rpcId);
    expect(envelope.result.ok).toBe(true);
    // 幂等佐证：响应归档集合 ⊇ 调前 registry 集合（零变更写），且含目标 id。
    const after = envelope.result.value?.archivedSessionIds ?? [];
    expect(after).toContain(archivedIds[0]);
    for (const id of archivedIds) expect(after).toContain(id);
  });

  it.skipIf(archivedIds.length === 0)("cookie 真被验签：签名被篡改即 401（排除「cookie 被忽略」假阳性）", async () => {
    const parts = cookie.split("=");
    const value = parts.slice(1).join("=");
    const segments = value.split(".");
    // 翻转签名段首字符（v1.<body>.<sig> 的 sig 首字符在 base64url 字母表内轮换）。
    const sig = segments[2];
    const flipped = sig[0] === "A" ? "B" : "A";
    const tampered = `${parts[0]}=${segments[0]}.${segments[1]}.${flipped}${sig.slice(1)}`;
    const res = await fetch(`${WEB_URL}/api/workspace/archiveSession`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        cookie: tampered,
      },
      body: JSON.stringify({
        type: "client-request",
        rpcId: "probe-tampered",
        method: "workspace/archiveSession",
        payload: { args: { request: { sessionId: archivedIds[0] } } },
      }),
      signal: AbortSignal.timeout(4000),
    });
    expect(res.status).toBe(401);
  });
});

describe.skipIf(probe !== null)("无真实探针环境（明确 skip 留痕）", () => {
  it("凭据/registry 文件缺失或 web 不可达，探针组跳过", () => {
    expect(skipReason).not.toBe("");
  });
});
