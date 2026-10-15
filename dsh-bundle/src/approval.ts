/**
 * approval.ts — 非交互审批策略（等价 claude --permission-mode bypassPermissions）。
 *
 * dsh 的审批面由两块组成（dsh-base 组合）：
 * - sandbox-policy.mode —— danger-full-access 时工具不触发沙箱升级询问；
 * - approval.policy —— 'never' 表示无人被询问（每个 ask 确定性 resolve rejected）。
 * 两者同时成立才是「全放行」：headless 无人值守下任何工具调用都不产生交互确认
 * 等待（'ask' 策略在 headless 无 answerer 时 fail-closed 拒绝，反而寸步难行）。
 *
 * 落地形态：cordis.patch.yml 以两条 patch（sandbox-policy / approval）写入配置，
 * 本模块是策略的字面单一来源——patch 条目由 approvalPatchEntries() 生成，测试
 * 对照 patch 文件断言一致；assertUnattendedSafe / assertSandboxModeSafe 供装配
 * 与测试分别校验审批策略与沙箱模式。
 *
 * 启动期可断言面只有 approval：dsh 插件 apply 期 ctx.get("sandbox-policy")
 * 实测不可读（服务未以该名暴露，2026-10-14 端到端冒烟实证），且插件启动期
 * 任何 stderr 输出都会作为流首行污染 headless run 流（acceptance 首行契约
 * fail-loud）——沙箱面由 patch 写死期望值 + assertSandboxModeSafe 供能读到
 * mode 的装配方与测试校验，apply 不做启动期读取。
 *
 * 三守卫挂在 tools/pre-execute（先于审批裁决），拦截路径不受全放行影响。
 *
 * 纯逻辑与 dsh 装配分离：单测零 dsh 依赖。
 */

// ── 纯逻辑：策略常量与校验 ─────────────────────────────────────────────────

/** 审批策略：永不询问（等价 bypassPermissions 的审批面）。 */
export const EXPECTED_APPROVAL_POLICY = "never";

/** 沙箱模式：全放行（等价 bypassPermissions 的沙箱面）。 */
export const EXPECTED_SANDBOX_MODE = "danger-full-access";

/**
 * 生成 cordis.patch.yml 中两条策略 patch 的等价对象（config-as-code 单一来源）。
 * 测试以自定义 !!js tag 解析 patch 文件（!!js 表达式按 dsh 的惰性表示
 * {__jsExpr: <表达式文本>} 构造）并与本函数输出做全等断言，防止两处漂移。
 */
export function approvalPatchEntries(): Array<Record<string, unknown>> {
  return [
    {
      id: "sandbox-policy",
      config: { mode: EXPECTED_SANDBOX_MODE, workspaceRoot: { __jsExpr: "process.cwd()" } },
    },
    {
      id: "approval",
      config: { policy: EXPECTED_APPROVAL_POLICY },
    },
  ];
}

/** 校验审批策略处于无人值守安全值；不满足抛错（零交互阻塞的构造性保证）。 */
export function assertUnattendedSafe(policy: string): string {
  if (policy !== EXPECTED_APPROVAL_POLICY) {
    throw new Error(
      `fenix-dsh-bundle 要求审批策略为 "${EXPECTED_APPROVAL_POLICY}"（无人值守零交互阻塞），` +
        `收到 "${policy}"。交互确认会阻塞 headless 运行，禁止以 ask 策略挂载本 Bundle。`,
    );
  }
  return policy;
}

/** 校验沙箱模式处于无人值守安全值；不满足抛错（与 assertUnattendedSafe 对称的构造性保证）。 */
export function assertSandboxModeSafe(mode: string): string {
  if (mode !== EXPECTED_SANDBOX_MODE) {
    throw new Error(
      `fenix-dsh-bundle 要求沙箱模式为 "${EXPECTED_SANDBOX_MODE}"（无人值守零升级询问），` +
        `收到 "${mode}"。受限沙箱会让工具触发沙箱升级询问并阻塞 headless 运行，` +
        `禁止以受限沙箱模式挂载本 Bundle。`,
    );
  }
  return mode;
}

// ── dsh 装配：启动期校验 ───────────────────────────────────────────────────

export const name = "fenix-approval";

/**
 * 插件入口：读取组合后的审批策略（approval.policy）并断言无人值守安全值。
 * 策略由本 bundle 的 cordis.patch.yml（approvalPatchEntries 的落盘形态）设置
 * 为 never；若上层 --patch 覆盖成 ask，这里在启动期即抛错（而非让会话中途
 * 阻塞/被拒）。policy 不可读（服务形态变化）时不在启动期硬拦，降级为
 * 宿主 logger 通道的 warning 诊断（非 stderr，见 warnUnreadable）——patch
 * 已写死 never，7.1 端到端冒烟对「写入不阻塞」的演示是行为面兜底。
 *
 * 沙箱面（sandbox-policy.mode）不在此读取：apply 期 ctx.get("sandbox-policy")
 * 实测不可读（见文件头注），无从校验——沙箱期望值由 patch 写死，校验走
 * assertSandboxModeSafe。
 */
export function apply(ctx: {
  get(name: string): unknown;
  /** 宿主诊断通道（cordis LoggerService）：降级 warning 走这里，不写 stderr。 */
  logger?: { warn(...args: unknown[]): unknown };
}): void {
  const approval = ctx.get("approval") as { policy?: string; config?: { policy?: string } } | undefined;
  const policy =
    typeof approval?.policy === "string"
      ? approval.policy
      : typeof approval?.config?.policy === "string"
        ? approval.config.policy
        : undefined;
  if (policy !== undefined) {
    assertUnattendedSafe(policy);
  } else {
    warnUnreadable(ctx.logger);
  }
}

/**
 * 审批策略不可读时的降级诊断：不在启动期硬拦，但留下可事后归因的 warning。
 * 经宿主 logger 通道输出——cordis LoggerService 的默认 exporter 只落内存
 * 环形 buffer（启动失败时随 StartupError 诊断留存），不写 stderr；头注的
 * 「启动期任何 stderr 输出都会污染 headless run 流首行」约束因此不被本路径
 * 破坏。通道不可得（裸 ctx 的单测/异常装配）时宁可舍弃诊断也不写 stderr。
 */
function warnUnreadable(logger?: { warn(...args: unknown[]): unknown }): void {
  logger?.warn(
    `[fenix-dsh-bundle] 无法读取 approval 服务的 policy（服务形态变化？），` +
      `已跳过启动期无人值守校验；期望值由 cordis.patch.yml 写死，请核对实际策略是否被 --patch 覆盖。`,
  );
}
