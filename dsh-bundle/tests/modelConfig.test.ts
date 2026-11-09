/**
 * modelConfig.test.ts — 模型显式配置契约单测。
 * 覆盖：形态划界（config.model 整体缺席 → 回落形态标记；null/空串/缺要素
 * fail-fast，错误含「模型未显式配置」）、三要素校验、providers / 默认模型
 * 渲染段形状、版本钉扎 fail-fast、apply 装配面（回落 WARN 留痕 + 显式零噪音）。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import * as yaml from "js-yaml";
import { afterEach, describe, expect, it } from "vitest";

import { setMockDshRuntimeVersion } from "@deepseek-ai/dsh-app-boot";

import {
  apply as applyModelConfig,
  assertModelExplicit,
  buildDefaultModelSegment,
  buildProviderSegment,
  createModelConfigService,
} from "../src/modelConfig.ts";
import { apply as applyMain } from "../src/index.ts";

const VALID = {
  provider: "fenix-gateway",
  baseURL: "http://127.0.0.1:18787/v1",
  apiKeyEnv: "FENIX_LLM_API_KEY",
  model: "glm-5.3-flash",
};

afterEach(() => {
  setMockDshRuntimeVersion("0.2.2-rc.1");
});

describe("assertModelExplicit：形态划界", () => {
  it("config.model 整体缺席（undefined）→ 返回回落形态标记，不抛错", () => {
    expect(assertModelExplicit(undefined)).toBeNull();
  });

  it("config.model 显式为 null → 笔误形态仍 fail-fast（整体缺席才是回落）", () => {
    expect(() => assertModelExplicit(null)).toThrow(/模型未显式配置/);
  });

  it("model 非对象形态 → 「模型未显式配置」", () => {
    expect(() => assertModelExplicit("openai/gpt")).toThrow(/模型未显式配置/);
  });

  it("model 为空串/空白/非字符串 → 「模型未显式配置」（含铁律措辞）", () => {
    for (const bad of ["", "   ", 42, null]) {
      expect(() => assertModelExplicit({ ...VALID, model: bad as never })).toThrow(/模型未显式配置/);
    }
  });

  it("只含 baseurl/apikey 无 model → 「模型未显式配置」且不提默认档回退", () => {
    const seg = { baseURL: VALID.baseURL, apiKeyEnv: VALID.apiKeyEnv };
    expect(() => assertModelExplicit(seg)).toThrow(/模型未显式配置/);
    expect(() => assertModelExplicit(seg)).toThrow(/绝不回退 dsh 默认档/);
  });

  it("provider / baseURL / apiKeyEnv 任一缺失同样 fail-fast", () => {
    for (const key of ["provider", "baseURL", "apiKeyEnv"] as const) {
      const broken = { ...VALID } as Record<string, unknown>;
      delete broken[key];
      expect(() => assertModelExplicit(broken), `缺 ${key} 应抛错`).toThrow(/模型未显式配置/);
    }
  });

  it("三要素齐备且 model 显式 → 通过并原样返回", () => {
    expect(assertModelExplicit(VALID)).toEqual(VALID);
  });
});

describe("渲染段构造", () => {
  it("providers 段：OpenAI 兼容路由 + models 目录含显式 model", () => {
    const providers = buildProviderSegment(VALID) as Record<
      string,
      { api: string; baseURL: string; apiKeyEnv: string; models: Array<{ id: string; input: string[] }> }
    >;
    expect(Object.keys(providers)).toEqual(["fenix-gateway"]);
    const profile = providers["fenix-gateway"];
    expect(profile.api).toBe("openai-completions");
    expect(profile.baseURL).toBe(VALID.baseURL);
    expect(profile.apiKeyEnv).toBe("FENIX_LLM_API_KEY");
    expect(profile.models).toHaveLength(1);
    expect(profile.models[0].id).toBe("glm-5.3-flash");
  });

  it("默认模型段：provider+model 显式对", () => {
    expect(buildDefaultModelSegment(VALID)).toEqual({ provider: "fenix-gateway", model: "glm-5.3-flash" });
  });

  it("createModelConfigService：显式链聚合服务对象（mode=explicit）", () => {
    const service = createModelConfigService({ model: VALID });
    if (service.mode !== "explicit") throw new Error("预期显式形态");
    expect(service.provider).toBe("fenix-gateway");
    expect(service.model).toBe("glm-5.3-flash");
    expect(service.providers).toEqual(buildProviderSegment(VALID));
  });

  it("createModelConfigService：config.model 整体缺席 → 回落形态（不抛错）", () => {
    expect(createModelConfigService({})).toEqual({ mode: "fallback" });
    expect(createModelConfigService(undefined)).toEqual({ mode: "fallback" });
    expect(createModelConfigService(null)).toEqual({ mode: "fallback" });
  });

  it("createModelConfigService：config.model 残缺（null/缺要素对象）仍 fail-fast", () => {
    expect(() => createModelConfigService({ model: null })).toThrow(/模型未显式配置/);
    expect(() =>
      createModelConfigService({ model: { baseURL: VALID.baseURL, apiKeyEnv: VALID.apiKeyEnv } }),
    ).toThrow(/模型未显式配置/);
  });
});

describe("版本钉扎 fail-fast", () => {
  it("运行时版本 ≠ 0.2.0-rc.2 → apply 抛明确版本错误", () => {
    setMockDshRuntimeVersion("0.2.0-rc.3");
    const provided: Record<string, unknown> = {};
    const ctx = { reflect: { provide: (name: string, value: unknown) => (provided[name] = value) } };
    expect(() => applyModelConfig(ctx, { model: VALID })).toThrow(/版本钉扎不满足/);
    expect(provided["fenixModelConfig"]).toBeUndefined();
  });

  it("主插件 apply 同样拒绝版本不符", () => {
    setMockDshRuntimeVersion("0.1.9");
    expect(() => applyMain({ tools: { register: () => {} }, on: () => {}, get: () => undefined })).toThrow(
      /版本钉扎不满足/,
    );
  });
});

describe("apply 装配面", () => {
  it("fenix-model-config：provide fenixModelConfig 服务", () => {
    const provided: Record<string, unknown> = {};
    applyModelConfig({ reflect: { provide: (name, value) => (provided[name] = value) } }, { model: VALID });
    expect(Object.keys(provided)).toEqual(["fenixModelConfig"]);
  });

  it("无 config 启动（无 patch 回落形态）→ 提供回落服务且不抛 StartupError，WARN 留痕", () => {
    const provided: Record<string, unknown> = {};
    const warns: string[] = [];
    applyModelConfig(
      {
        reflect: { provide: (name, value) => (provided[name] = value) },
        logger: { warn: (msg: string) => warns.push(msg) },
      },
      undefined,
    );
    expect(provided["fenixModelConfig"]).toEqual({ mode: "fallback" });
    expect(warns).toHaveLength(1);
    expect(warns[0]).toContain("config.model 缺席，回落 dsh 默认档");
  });

  it("显式链形态 → 提供显式服务且零 WARN（不误报回落）", () => {
    const provided: Record<string, unknown> = {};
    const warns: string[] = [];
    applyModelConfig(
      {
        reflect: { provide: (name, value) => (provided[name] = value) },
        logger: { warn: (msg: string) => warns.push(msg) },
      },
      { model: VALID },
    );
    expect(provided["fenixModelConfig"]).toMatchObject({ mode: "explicit", provider: "fenix-gateway" });
    expect(warns).toEqual([]);
  });

  it("残缺 config.model → fail-fast 不提供服务（笔误防护不变）", () => {
    const provided: Record<string, unknown> = {};
    expect(() =>
      applyModelConfig(
        { reflect: { provide: (name, value) => (provided[name] = value) } },
        { model: { provider: "p" } },
      ),
    ).toThrow(/模型未显式配置/);
    expect(provided["fenixModelConfig"]).toBeUndefined();
  });

  it("主插件：注册恰好四工具 + pre-execute 守卫 + 审批校验 + AGENTS.md 分区", () => {
    const registered: Array<{ name: string }> = [];
    const events: Array<{ event: string; options?: { prepend?: boolean } }> = [];
    const injected: string[][] = [];
    applyMain({
      tools: { register: (d) => registered.push(d as { name: string }) },
      on: (event: string, _listener: unknown, options?: { prepend?: boolean }) => {
        events.push({ event, options });
        return undefined;
      },
      get: () => ({ policy: "never" }),
      inject: (deps: string[], _fn: (scope: unknown) => void) => {
        injected.push(deps);
        return undefined;
      },
    });
    expect(registered.map((t) => t.name)).toEqual(["TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]);
    expect(events).toEqual([{ event: "tools/pre-execute", options: { prepend: true } }]);
    expect(injected).toEqual([["systemPrompt"]]);
  });

  it("主插件：审批策略非 never 时启动期抛错", () => {
    expect(() =>
      applyMain({
        tools: { register: () => {} },
        on: () => {},
        get: () => ({ policy: "ask" }),
        inject: () => {},
      }),
    ).toThrow(/无人值守零交互阻塞/);
  });
});

// ── cordis.patch.yml 原生行零触碰装配结构锁（真对称回落，D1 机理修正版）──────

/** 与 dsh-app-boot 同构的条目清单方言（!!js → {__jsExpr}），装配结构断言用。 */
const JsExpr = new yaml.Type("tag:yaml.org,2002:js", {
  kind: "scalar",
  resolve: (data: unknown) => typeof data === "string",
  construct: (data: string) => ({ __jsExpr: data }),
});
const entryListSchema = yaml.JSON_SCHEMA.extend([JsExpr]);

function loadPatchDoc(): Array<Record<string, unknown>> {
  const text = readFileSync(fileURLToPath(new URL("../cordis.patch.yml", import.meta.url)), "utf-8");
  return yaml.load(text, { schema: entryListSchema }) as Array<Record<string, unknown>>;
}

describe("cordis.patch.yml 原生行零触碰装配结构锁", () => {
  const doc = loadPatchDoc();
  const insertBlock = doc.find((r) => "insert" in r) as { insert: Array<Record<string, unknown>> };

  it("bundle 零触碰 dsh-base 原生 agent-default-model 行（patch 面无该 id 条目）", () => {
    // 机理注记（cordis.patch.yml）：disabled !!js 求值先于 inject 服务绑定，
    // 形态分流不可放在 disabled 表达式上 → bundle 对原生行不 inject、不改
    // config、不 disabled；两形态由原生行常开供 agentDefaultModel。
    const patchTargets = doc
      .filter((r) => !("insert" in r))
      .map((r) => r.id);
    expect(patchTargets).not.toContain("agent-default-model");
    const insertIds = insertBlock.insert.map((r) => r.id);
    expect(insertIds).not.toContain("agent-default-model");
    expect(insertIds).not.toContain("fenix-agent-default-model");
  });

  it("fenix-model-config 插入行在场（形态划界与回落供数的承载插件）", () => {
    const row = insertBlock.insert.find((r) => r.id === "fenix-model-config");
    expect(row).toBeDefined();
    expect((row as Record<string, unknown>).name).toBe("fenix-dsh-bundle/modelConfig");
  });

  it("llm-pi-ai 行：providers 由 fenixModelConfig 插值（回落形态 undefined → schema 缺省 {}）", () => {
    const row = doc.find((r) => r.id === "llm-pi-ai") as Record<string, unknown>;
    expect(row.inject).toEqual(["fenixModelConfig"]);
    const config = row.config as Record<string, { __jsExpr?: string }>;
    expect(config.providers.__jsExpr).toContain("ctx.fenixModelConfig.providers");
  });

  it("headless-runner 行：追加注入 fenixModelConfig 不变（回落形态服务恒提供）", () => {
    const row = doc.find((r) => r.id === "headless-runner") as Record<string, unknown>;
    expect(row.inject).toEqual(["headlessStartup", "fenixModelConfig"]);
  });
});
