/**
 * modelConfig.test.ts — 模型显式配置契约单测。
 * 覆盖：model 缺失/为空 fail-fast（错误含「模型未显式配置」）、三要素校验、
 * providers / 默认模型渲染段形状、版本钉扎 fail-fast、apply 装配面。
 */
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
  setMockDshRuntimeVersion("0.2.0-rc.2");
});

describe("assertModelExplicit：缺 model 即拒绝启动", () => {
  it("config.model 整段缺失 → 「模型未显式配置」", () => {
    expect(() => assertModelExplicit(undefined)).toThrow(/模型未显式配置/);
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

  it("createModelConfigService：聚合服务对象；缺 model 抛「模型未显式配置」", () => {
    const service = createModelConfigService({ model: VALID });
    expect(service.provider).toBe("fenix-gateway");
    expect(service.model).toBe("glm-5.3-flash");
    expect(service.providers).toEqual(buildProviderSegment(VALID));
    expect(() => createModelConfigService({})).toThrow(/模型未显式配置/);
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

  it("主插件：注册恰好四工具 + pre-execute 守卫 + 审批校验", () => {
    const registered: Array<{ name: string }> = [];
    const events: Array<{ event: string; options?: { prepend?: boolean } }> = [];
    applyMain({
      tools: { register: (d) => registered.push(d as { name: string }) },
      on: (event: string, _listener: unknown, options?: { prepend?: boolean }) => {
        events.push({ event, options });
        return undefined;
      },
      get: () => ({ policy: "never" }),
    });
    expect(registered.map((t) => t.name)).toEqual(["TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]);
    expect(events).toEqual([{ event: "tools/pre-execute", options: { prepend: true } }]);
  });

  it("主插件：审批策略非 never 时启动期抛错", () => {
    expect(() =>
      applyMain({
        tools: { register: () => {} },
        on: () => {},
        get: () => ({ policy: "ask" }),
      }),
    ).toThrow(/无人值守零交互阻塞/);
  });
});
