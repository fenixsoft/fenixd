#!/usr/bin/env node
/**
 * mock-model-server.mjs — OpenAI 兼容假模型端点（dsh-bundle 探针与冒烟夹具）。
 *
 * 供 `dsh headless --json` 以自定义 provider 指向本服务：
 * - 响应序列经 --script 脚本化编排（text / tool_calls / mixed / error 各类）；
 * - 支持 stream（SSE chat.completion.chunk）与非 stream（chat.completion）两种形态；
 * - 每个请求以 NDJSON 追加进 --log（供断言请求形状：messages / tools / model）；
 * - 恒回 usage 三元（prompt_tokens / completion_tokens / total_tokens）——
 *   usage 形态探针（probe 1.3）依赖：服务端恒供，看 dsh 是否透传到 final 事件。
 *
 * 用法：
 *   node mock-model-server.mjs --port 18787 --script steps.json --log requests.jsonl
 *
 * 脚本步骤（JSON 数组，逐请求消费，耗尽后重复最后一步）：
 *   {"kind":"text","text":"ok"}
 *   {"kind":"tool_calls","toolCalls":[{"name":"TaskCreate","arguments":{"subject":"x"}}]}
 *   {"kind":"mixed","text":"先想一下","toolCalls":[{"name":"TaskList","arguments":{}}]}
 *   {"kind":"error","status":401,"body":{"error":{"message":"Authentication Fails","code":"AUTH"}}}
 */

import { createServer } from "node:http";
import { appendFileSync, readFileSync } from "node:fs";

// ── 参数解析 ────────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const args = { port: 18787, script: null, log: null, loop: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port") args.port = Number(argv[++i]);
    else if (a === "--script") args.script = argv[++i];
    else if (a === "--log") args.log = argv[++i];
    else if (a === "--no-loop") args.loop = false;
  }
  return args;
}

const ARGS = parseArgs(process.argv.slice(2));

function loadSteps() {
  if (!ARGS.script) {
    return [{ kind: "text", text: "ok" }];
  }
  const parsed = JSON.parse(readFileSync(ARGS.script, "utf8"));
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error(`script 必须为非空数组：${ARGS.script}`);
  }
  return parsed;
}

const STEPS = loadSteps();
let cursor = 0;

function nextStep() {
  if (cursor < STEPS.length) {
    return STEPS[cursor++];
  }
  if (ARGS.loop) {
    return STEPS[STEPS.length - 1];
  }
  return null;
}

function logRequest(entry) {
  if (!ARGS.log) return;
  appendFileSync(ARGS.log, JSON.stringify(entry) + "\n");
}

// ── OpenAI 兼容响应构造 ─────────────────────────────────────────────────────
const MOCK_USAGE = { prompt_tokens: 128, completion_tokens: 32, total_tokens: 160 };

function toolCallsOf(step) {
  return (step.toolCalls || []).map((tc, i) => ({
    id: `call_mock_${cursor}_${i}`,
    type: "function",
    index: i,
    function: {
      name: tc.name,
      // arguments 按协议是字符串（JSON 文本）
      arguments: typeof tc.arguments === "string" ? tc.arguments : JSON.stringify(tc.arguments ?? {}),
    },
  }));
}

function stepCompletionBody(step, model, stream) {
  const text = step.text ?? "";
  const calls = step.toolCalls ? toolCallsOf(step) : null;
  const finish = calls && calls.length > 0 ? "tool_calls" : "stop";
  if (!stream) {
    const message = { role: "assistant", content: text, refusal: null };
    if (calls && calls.length > 0) message.tool_calls = calls;
    return {
      id: `chatcmpl-mock-${Date.now()}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model,
      choices: [{ index: 0, message, logprobs: null, finish_reason: finish }],
      usage: MOCK_USAGE,
      service_tier: "default",
      system_fingerprint: "fp_mock",
    };
  }
  return null; // stream 由调用方分块组装
}

function* streamChunks(step, model, id, created) {
  const calls = step.toolCalls ? toolCallsOf(step) : null;
  const finish = calls && calls.length > 0 ? "tool_calls" : "stop";
  const base = { id, object: "chat.completion.chunk", created, model, service_tier: "default" };
  // 首块：role
  yield { ...base, choices: [{ index: 0, delta: { role: "assistant", content: "" }, logprobs: null, finish_reason: null }] };
  // 文本块
  const text = step.text ?? "";
  if (text) {
    yield { ...base, choices: [{ index: 0, delta: { content: text }, logprobs: null, finish_reason: null }] };
  }
  // 工具调用块（整参一次下发——arguments 分片对客户端解析是透明的）
  for (const tc of calls || []) {
    yield {
      ...base,
      choices: [{ index: 0, delta: { tool_calls: [{ index: tc.index, id: tc.id, type: "function", function: tc.function }] }, logprobs: null, finish_reason: null }],
    };
  }
  // 收尾块
  yield { ...base, choices: [{ index: 0, delta: {}, logprobs: null, finish_reason: finish }] };
  // usage 尾块（choices 空）——恒发，供 usage 形态探针
  yield { ...base, choices: [], usage: MOCK_USAGE };
}

// ── HTTP 服务 ───────────────────────────────────────────────────────────────
const server = createServer((req, res) => {
  const url = req.url || "";

  if (req.method === "GET" && (url === "/healthz" || url === "/healthz/")) {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, steps: STEPS.length, cursor }));
    return;
  }

  if (req.method !== "POST" || !(url === "/v1/chat/completions" || url === "/chat/completions")) {
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { message: `mock: no route ${req.method} ${url}`, code: "not_found" } }));
    return;
  }

  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    let body = {};
    try {
      body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
    } catch {
      body = {};
    }
    logRequest({
      ts: new Date().toISOString(),
      url,
      auth: req.headers.authorization ?? null,
      model: body.model ?? null,
      stream: body.stream ?? false,
      tools: (body.tools || []).map((t) => t?.function?.name).filter(Boolean),
      messageCount: Array.isArray(body.messages) ? body.messages.length : 0,
      lastMessage: Array.isArray(body.messages) ? body.messages[body.messages.length - 1] ?? null : null,
      // MOCK_DUMP_MESSAGES=1 时转储完整消息数组（验证 system-prompt 分区/指令注入用）
      ...(process.env.MOCK_DUMP_MESSAGES ? { messages: body.messages ?? [] } : {}),
    });

    const step = nextStep();
    if (!step) {
      res.writeHead(503, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: { message: "mock: script exhausted", code: "exhausted" } }));
      return;
    }

    if (step.kind === "error") {
      res.writeHead(step.status || 500, { "content-type": "application/json" });
      res.end(JSON.stringify(step.body ?? { error: { message: "mock error", code: "mock_error" } }));
      return;
    }

    const id = `chatcmpl-mock-${Date.now()}`;
    const created = Math.floor(Date.now() / 1000);
    const model = body.model || "mock-model";

    if (body.stream) {
      res.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      for (const chunk of streamChunks(step, model, id, created)) {
        res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      }
      res.write("data: [DONE]\n\n");
      res.end();
      return;
    }

    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(stepCompletionBody(step, model, false)));
  });
});

server.listen(ARGS.port, "127.0.0.1", () => {
  process.stdout.write(`mock-model-server listening on http://127.0.0.1:${ARGS.port} (steps=${STEPS.length})\n`);
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 500).unref();
  });
}
