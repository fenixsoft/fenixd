import { Alert, Button, Card, Descriptions, Form, InputNumber, Select, Switch, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { autodraftRegression, getOcrStatus, getRegressionConfig, installOcr } from '@/services/dashboard';
import type { OcrStatus, RegressionConfigStatus } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

/** regression.cmd 可为 str（shell）或 list（argv）；展示统一成可读串 */
function formatCmd(cmd: string | string[]): string {
  return Array.isArray(cmd) ? cmd.join(' ') : cmd;
}

interface QualityPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function QualityPanel({ config, onSave, project, onConfigSynced }: QualityPanelProps) {
  const [form] = Form.useForm();
  // 环境门只拦「开启」不拦「关闭」（code-review item 1bcde4921884）：ocr 未
  // 就绪时若把开关一律禁用，已配 verify.impl_code_review:true 的项目从此无法
  // 在 UI 关掉该 gate（禁用开关不可切换，handleSave 还会原样重提 true）。
  const implCodeReviewOn = Form.useWatch('impl_code_review', form) === true;
  // ocr 环境探测状态：null=加载中；未安装时开关置灰并给出「一键安装」
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  // 项目作用域：verify.yaml regression 段配置状态（null=加载中/未加载）
  const [regressionCfg, setRegressionCfg] = useState<RegressionConfigStatus | null>(null);
  const [regressionCfgError, setRegressionCfgError] = useState<string | null>(null);
  const [regressionDrafting, setRegressionDrafting] = useState(false);
  // 补段请求同步防重入锁（同 ProjectProfilePanel 的 autodraftInFlight 约定：loading
  // 渲染生效存在调度间隙，useRef 写读同帧原子）
  const regressionDraftInFlight = useRef(false);

  useEffect(() => {
    form.setFieldsValue({
      impl_code_review: config.verify?.impl_code_review === true,
      // add-impl-code-review-tuning：三运行参数回填缺省（600/4/low——后端
      // read_config / read_effective_config 恒回显缺省，前端回填与之一致；
      // 既有开关「缺省不回显」约定不变：impl_code_review 缺席仍为关）
      impl_code_review_timeout_sec: config.verify?.impl_code_review_timeout_sec ?? 600,
      // add-impl-ocr-parallel-lane（任务 1.2）：后端缺省 2→4，回填与之一致
      impl_code_review_concurrency: config.verify?.impl_code_review_concurrency ?? 4,
      impl_code_review_effort: config.verify?.impl_code_review_effort ?? 'low',
      // add-impl-ocr-parallel-lane：join 双档模式回填缺省 gate（后端恒回显，
      // 前端回填与之一致）
      impl_code_review_mode: config.verify?.impl_code_review_mode ?? 'gate',
      // 周期性代码审查（2026-09-19 从项目页「代码审查」分面迁来）：
      // 开关是项目级配置（admin.code_review.enabled），归设置页而非项目页
      code_review_enabled: config.code_review?.enabled === true,
      // add-test-regression-tab：周期性全量回归开关（admin.regression.enabled）
      // 缺省 false；分面只读展示 + 手动触发，配置归设置页「质量」页签
      regression_enabled: config.regression?.enabled === true,
      // add-code-review-auto-fix：自动修复开关 + 批大小（回填缺省 false/20）
      code_review_fix_enabled: config.code_review_fix?.enabled === true,
      code_review_fix_batch_size: config.code_review_fix?.batch_size ?? 20,
    });
  }, [config.verify, config.code_review, config.code_review_fix, config.regression, form]);

  useEffect(() => {
    let alive = true;
    getOcrStatus()
      .then((s) => {
        if (alive) setOcr(s);
      })
      .catch(() => {
        if (alive) setOcr({ installed: false, bin: null, version: null });
      });
    return () => {
      alive = false;
    };
  }, []);

  // 项目作用域：拉取 verify.yaml 的 regression 段配置状态（切换项目重拉；
  // alive 守卫丢弃被取代的旧响应）
  useEffect(() => {
    if (!project) {
      setRegressionCfg(null);
      setRegressionCfgError(null);
      return;
    }
    let alive = true;
    setRegressionCfg(null);
    setRegressionCfgError(null);
    getRegressionConfig(project)
      .then((d) => {
        if (alive) setRegressionCfg(d);
      })
      .catch((e) => {
        if (alive) setRegressionCfgError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [project]);

  const handleInstall = async () => {
    setInstalling(true);
    try {
      // 1) 安装调用（code-review item 52c15fcd9bc1）：必须先检查 res.ok——
      // 旧实现不看返回值，ok===false/version===null 时仍提示「安装成功」。
      let res;
      try {
        res = await installOcr();
      } catch (err) {
        message.error(`安装失败：${err instanceof Error ? err.message : String(err)}`);
        return;
      }
      if (!res.ok) {
        message.error(`安装失败：${res.error || 'npm 安装未成功'}`);
        return;
      }
      message.success(
        res.version ? `open-code-review 安装成功：${res.version}` : 'open-code-review 安装成功',
      );
      // 2) 安装成功后重新探测（独立 try）：探测失败不应把已成功的安装误报为失败、
      // 也不应让 ocr 停在 stale（否则开关永久置灰）。
      try {
        const fresh = await getOcrStatus();
        setOcr(fresh);
      } catch {
        // 探测失败：乐观标记为已安装（版本未知），至少解锁开关
        setOcr({ installed: true, bin: null, version: res.version ?? null });
      }
    } finally {
      setInstalling(false);
    }
  };

  // 「使用 AI 生成」：请求 Administrator 补写 regression 段（写信号，巡检分钟级消费）
  const handleRegressionAutodraft = async () => {
    if (!project || regressionDraftInFlight.current) return;
    regressionDraftInFlight.current = true;
    setRegressionDrafting(true);
    try {
      const res = await autodraftRegression(project);
      if (res.status === 'skipped') {
        message.info(res.message || 'regression 段已配置，无需补写');
      } else {
        message.success(res.message || '已提交 AI 补写 regression 段请求');
      }
    } catch (err) {
      message.error(`AI 生成失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      regressionDraftInFlight.current = false;
      setRegressionDrafting(false);
    }
  };

  const handleSave = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：antd 已在表单内渲染提示，无需额外日志
      // （避免触发验证的 no_console_error 断言）。
      return;
    }
    try {
      await onSave({
        // add-impl-code-review-gate：收尾代码质量审查开关（键路径不变，仅移至质量页签）
        verify: {
          impl_code_review: values.impl_code_review === true,
          // add-impl-code-review-tuning：三运行参数序列化（表单回填后恒有值；
          // 正整数/枚举由表单校验先行把关，后端 write_config 再权威兜底）
          impl_code_review_timeout_sec: values.impl_code_review_timeout_sec,
          impl_code_review_concurrency: values.impl_code_review_concurrency,
          impl_code_review_effort: values.impl_code_review_effort,
          // add-impl-ocr-parallel-lane：join 双档模式序列化（表单回填后恒有值，
          // 白名单枚举由表单校验先行把关，后端 write_config 再权威兜底）
          impl_code_review_mode: values.impl_code_review_mode,
        },
        // add-code-review-agent-and-quality-tab：周期性代码审查开关
        // （2026-09-19 从项目页「代码审查」分面迁到设置页「质量」页签）
        code_review: {
          enabled: values.code_review_enabled === true,
        },
        // add-test-regression-tab：周期性全量回归开关（admin.regression.enabled，
        // 缺省 false；与 code_review 同周期：admin.self_review.run_at 时点）
        regression: {
          enabled: values.regression_enabled === true,
        },
        // add-code-review-auto-fix：自动修复开关 + 批大小（与开关同处一个
        // <Form> 实例内，validateFields 恒返回两字段；1–1000 由表单校验把关，
        // 后端 write_config 权威兜底）
        code_review_fix: {
          enabled: values.code_review_fix_enabled === true,
          batch_size: values.code_review_fix_batch_size,
        },
      });
    } catch (err) {
      // 当前接线下此 catch 实际不可达（code-review item 330164f11711）：父级
      // handleSave（settings/index.tsx）已把 saveConfig 包 try/catch、自显
      // 「保存失败」提示并以 resolve(false) 结束——子层观察不到保存失败，
      // 上方「校验失败」与「保存失败」的区分并不成立。保留兜底捕获：未来
      // 父组件改为透传失败时，保存失败不致被静默吞掉。
      message.error(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // 环境门控：ocr 未安装（或探测失败）时阻止「开启」——避免开启一个运行期必然
  // 降级跳过的开关。探测未返回（加载中）时对关闭态同样置灰，避免先开后关的
  // 闪变；已开启的 gate 不禁用，保证关闭路径始终可用（见上方 useWatch 注释）。
  const ocrReady = ocr?.installed === true;

  // ocr 环境状态行（code-review item 2f3f9bd1b013）：旧实现嵌套三元违反前端
  // 规则，抽 helper 以 if/else 表达「加载中 / 已装 / 未装」三分支。
  const renderOcrStatus = () => {
    if (ocr === null) {
      return <Text type="secondary">正在检测 open-code-review 环境…</Text>;
    }
    if (ocr.installed) {
      return (
        <Alert
          type="success"
          showIcon
          message="已安装 open-code-review"
          description={ocr.version || ocr.bin || '检测到 ocr 可执行文件'}
          // 下边距与卡片 body 上内边距（24px）对齐：Alert 自身无默认外边距，
          // 否则它会紧贴下方开关行，视觉上「上松下紧」。
          style={{ marginBottom: 24 }}
          data-testid="ocr-installed-alert"
        />
      );
    }
    return (
      <Alert
        type="warning"
        showIcon
        message="未检测到 open-code-review"
        description="代码质量审查依赖 ocr（@alibaba-group/open-code-review）。未安装时该开关不可开启，运行期也会按 unavailable 降级跳过。"
        action={
          <Button
            type="primary"
            size="small"
            loading={installing}
            onClick={handleInstall}
            data-testid="ocr-install-btn"
          >
            一键安装
          </Button>
        }
        data-testid="ocr-missing-alert"
      />
    );
  };

  return (
    <div>
      <h3>代码质量</h3>
      <Text type="secondary">实现阶段的代码质量门相关设置。</Text>
      {/* 统一 Form 包裹全部卡片（fix-verify-bug 2026-09-21）：旧实现把
          周期代码审查 / 周期全量回归两个开关放在 <Form> 外的 <div> 容器里，
          rc-field-form 的 Form.Item 只在 <form> 内注册字段——validateFields()
          不返回脱管字段，handleSave 恒提交 enabled:false（视觉开启但后端未
          持久化，api-regression-config-persisted 验证实测确证）。 */}
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Card style={{ marginTop: 12 }}>
          {/* 环境状态行：已装 → 绿色提示；未装 → 橙色提示 + 一键安装按钮
              （渲染逻辑抽 renderOcrStatus，见其注释） */}
          {renderOcrStatus()}
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row） */}
          <div className="switch-inline-row">
            <Form.Item name="impl_code_review" valuePropName="checked" noStyle>
              <Switch
                data-testid="impl-code-review-switch"
                disabled={!ocrReady && !implCodeReviewOn}
              />
            </Form.Item>
            <span className="switch-inline-label">
              收尾代码质量审查
              <span className="label-note">（verify.impl_code_review）</span>
            </span>
          </div>
          {!ocrReady && ocr !== null && (
            <Text type="warning" style={{ display: 'block', marginBottom: 8 }}>
              请先安装 open-code-review 后再开启此项。
            </Text>
          )}
          <Text type="secondary">
            开启后实现者会在全部 tasks.md 任务完成、提交之后、写结果文件之前调用
            ocr（bin/ocr_review.py）scan 全文件扫描本次改动，逐条评估发现并自行修正
            真实问题（误报可驳回）。需要环境已安装 ocr，未安装时自动按 unavailable
            降级跳过。
          </Text>

          {/* add-impl-code-review-tuning：三运行参数编辑控件（超时秒 / 并发 / 力度）。
              与 ocr 参数对应：timeout_sec 写入 run 级 ocr provider 配置（确定性生效）；
              --concurrency / --effort 经提示词命令示例承载（软约束，实现者须照抄命令串）。
              缺省回填 600 / 4 / low（后端 read_config / read_effective_config 恒回显缺省）。 */}
          <Form.Item
            name="impl_code_review_timeout_sec"
            label={
              <>
                审查超时<span className="label-note">（verify.impl_code_review_timeout_sec）</span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: number | undefined | null) =>
                  v != null && Number.isInteger(v) && v > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为正整数')),
              },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              style={{ width: '100%' }}
              addonAfter="秒"
              data-testid="impl-code-review-timeout"
            />
          </Form.Item>
          <Text type="secondary">
            默认 600。ocr LLM 单请求超时（秒，含等待响应头）：不配置时 ocr 走其内置
            300s 默认，实测 8 路并发 + 300s 单请求超时会撞穿首字节等待导致大面积
            文件级 timeout。写入 run 级 ocr 配置（custom_providers.fenix-impl.timeout_sec），
            确定性生效。
          </Text>

          <Form.Item
            name="impl_code_review_concurrency"
            label={
              <>
                审查并发<span className="label-note">（verify.impl_code_review_concurrency）</span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: number | undefined | null) =>
                  v != null && Number.isInteger(v) && v > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为正整数')),
              },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              style={{ width: '100%' }}
              addonAfter="个"
              data-testid="impl-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            默认 4。ocr 并发子任务上限（--concurrency）：实测 8 路并发同时打同一
            provider 网关会把首字节延迟放大到撞穿超时线；add-impl-ocr-parallel-lane
            由 2 上调至 4（审查转异步车道后不再卡实现者收工，吞吐优先）。
            经提示词命令示例承载，实现者须照抄命令串才生效。
          </Text>

          <Form.Item
            name="impl_code_review_effort"
            label={
              <>
                审查力度<span className="label-note">（verify.impl_code_review_effort）</span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: string | undefined | null) =>
                  v && ['low', 'medium', 'high'].includes(v)
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为 low/medium/high')),
              },
            ]}
            style={{ marginTop: 24 }}
          >
            <Select data-testid="impl-code-review-effort">
              <Select.Option value="low">low</Select.Option>
              <Select.Option value="medium">medium</Select.Option>
              <Select.Option value="high">high</Select.Option>
            </Select>
          </Form.Item>
          <Text type="secondary">
            默认 low。ocr 审查力度预设（--effort）：low 更快更省但 recall 偏低
            （precision 优先的刻意取舍），medium 为 ocr 官方默认，high 深度审查。
            经提示词命令示例承载，实现者须照抄命令串才生效。
          </Text>

          {/* add-impl-ocr-parallel-lane：join 双档模式选择（gate/advisory）。
              车道在实现分支合并后异步跑 ocr，tester 判定 verified 时 join 裁决：
              gate 档非 rejected findings 打回修复轮（上限 1 轮，超限转台账）；
              advisory 档 findings 一律写 code-review 台账、join 永不打回。 */}
          <Form.Item
            name="impl_code_review_mode"
            label={
              <>
                车道裁决模式<span className="label-note">（verify.impl_code_review_mode）</span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: string | undefined | null) =>
                  v && ['gate', 'advisory'].includes(v)
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为 gate/advisory')),
              },
            ]}
            style={{ marginTop: 24 }}
          >
            <Select data-testid="impl-code-review-mode">
              <Select.Option value="gate">gate（打回修复）</Select.Option>
              <Select.Option value="advisory">advisory（仅台账）</Select.Option>
            </Select>
          </Form.Item>
          <Text type="secondary">
            默认 gate。实现分支合并后异步 ocr 车道的发现如何参与验证收口：gate
            档发现非 rejected findings 时把 spec 打回修复轮（最多 1 轮，超限全部
            转 code-review 台账后放行）；advisory 档 findings 只写台账、永不打回。
          </Text>

          {/* 周期性代码审查开关（2026-09-19 从项目页「代码审查」分面迁到本页签）：
              它是项目级配置（admin.code_review.enabled），与手动触发按钮的性质不同
              ——分面负责「看结果 + 手动触发」，配置归设置页统一管理。
              与「收尾代码质量审查」同属代码质量范畴，故并入本卡片而非独立成卡。
              注：本条改动在 merge-back 中两次因「先 stash 后 merge」被丢弃，本卡片
              由 admin 处置（stash_pop_conflict）从 stash 找回，见 admin_disposition。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="code_review_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="code-review-enabled-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              周期性代码审查
              <span className="label-note">（admin.code_review.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            开启后与每日自省同周期（admin.self_review.run_at 时点）自动派发
            code-review agent，审查窗口内开发 SPEC 的产品代码质量，问题沉淀到
            .fenix/code-review/items.jsonl 台账，供项目页「代码审查」分面展示与消费。
            需要环境已安装 ocr（未安装时审查仍以 LLM 逐文件执行，仅少了扫描加速）。
            手动触发（全仓库审查 / 当期提交审查）不受本开关约束。
          </Text>

          {/* 自动修复代码问题（add-code-review-auto-fix，task 9.2）：2026-09-22
              自独立卡片并入本卡，位于「周期性代码审查」之后（spec code-fix-config
              位置约束同步改为「同卡其后」）。同一 <Form> 实例内（脱管字段
              validateFields 不返回 → 恒提交缺省，见上方统一 Form 注释）。 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="code_review_fix_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="code-review-fix-enabled-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              自动修复代码问题
              <span className="label-note">（admin.code_review_fix.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            开启后把审查台账 open 条目按批（每批 batch_size 条，缺省 20）派
            code-fix agent 在独立 worktree 内修复并提交，每批必过全量回归
            （verify.yaml regression 段）才合回主树并把条目置 resolved；回归
            未通过自动重试一次，仍失败则保留现场待人工。无有效 regression 段时
            fail-closed 不合回。关闭（缺省）= 全链路零动作。进度见项目页
            「代码审查」分面。
          </Text>
          {/* 批大小与「审查超时/并发」同形态：整宽 + addonAfter 单位。旧实现
              maxWidth:240 会把 inline-flex label 里的裸文本节点压到 min-content
              （一字一行竖排，机制见 global.less 移动端 label 修复注释）。 */}
          <Form.Item
            name="code_review_fix_batch_size"
            label={
              <>
                每批条目数
                <span className="label-note">（admin.code_review_fix.batch_size）</span>
              </>
            }
            rules={[
              {
                validator: (_: unknown, v: number | undefined | null) =>
                  v !== null && v !== undefined && Number.isInteger(v) && v >= 1 && v <= 1000
                    ? Promise.resolve()
                    : Promise.reject(new Error('须为 1–1000 的整数')),
              },
            ]}
            style={{ marginTop: 24 }}
          >
            <InputNumber
              min={1}
              max={1000}
              precision={0}
              style={{ width: '100%' }}
              addonAfter="条"
              data-testid="code-review-fix-batch-size"
            />
          </Form.Item>
        </Card>
        {/* 回归测试：标题与说明置于卡片外，与上方「代码质量」节同构 */}
        <h3 style={{ marginTop: 32 }}>回归测试</h3>
        <Text type="secondary">周期性全量回归的执行相关设置。</Text>
        {/* add-test-regression-tab：周期性全量回归开关（admin.regression.enabled）。
            与 code_review 同层同形态：开关归设置页，项目页「测试回归」分面只读
            展示 + 手动触发。开启前提 = 项目 .fenix/verify.yaml 有有效 regression 段
            （无段时周期检查点跳过、不派发空跑）；长耗时阈值归 verify.yaml 声明
            （regression.long_test_threshold_seconds 缺省 10），本卡片只读说明其来源，
            MUST NOT 另开第二个阈值写入路径（双写会让阈值来源分叉，design R4）——
            编辑入口复用既有 GET/POST /api/verify-yaml（项目设置「项目简介」面板）。 */}
        <Card style={{ marginTop: 12 }}>
          <div>
            <div className="switch-inline-row">
              <Form.Item name="regression_enabled" valuePropName="checked" noStyle>
                <Switch data-testid="regression-enabled-switch" />
              </Form.Item>
              <span className="switch-inline-label">
                周期性全量回归
                <span className="label-note">（admin.regression.enabled）</span>
              </span>
            </div>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              开启后与每日自省同周期（admin.self_review.run_at 时点）自动执行一次
              全量回归（需项目 .fenix/verify.yaml 配置 regression 段），结果落到
              .fenix/regression/last-run.json，供项目页「测试回归」分面展示。
              同一自然日防重；与 implementer 收尾的全量套件互斥（主机级锁）。
              手动触发（项目页「立即执行全量回归」）不受本开关约束。
            </Text>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              长耗时用例阈值来自 verify.yaml 的 regression.long_test_threshold_seconds
              （缺省 10 秒），属项目测试体系声明——请在「项目简介」面板的
              verify.yaml 编辑入口中调整，本卡片不提供第二个写入路径。
            </Text>

            {/* 项目作用域专属：verify.yaml regression 段配置状态（只读）+ AI 补段。
                用户级作用域不显示（verify.yaml 是项目级文件）。
                判定走后端 load_verify_contract（前端无 yaml 解析库，正则判段不可靠）。 */}
            {project && (
              <div style={{ marginTop: 16 }} data-testid="regression-config-section">
                {regressionCfgError ? (
                  <Alert
                    type="error"
                    showIcon
                    message="读取 verify.yaml regression 段失败"
                    description={regressionCfgError}
                  />
                ) : regressionCfg === null ? (
                  <Text type="secondary">正在读取 verify.yaml 的 regression 段…</Text>
                ) : regressionCfg.regression ? (
                  <>
                    <Text type="secondary">已配置回归段（.fenix/verify.yaml）：</Text>
                    <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
                      <Descriptions.Item label="执行命令">
                        <Text code>{formatCmd(regressionCfg.regression.cmd)}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="结果文件">
                        <Text code>{regressionCfg.regression.output}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="硬超时">
                        {regressionCfg.regression.timeout_seconds} 秒
                      </Descriptions.Item>
                      <Descriptions.Item label="长耗时阈值">
                        {regressionCfg.regression.long_test_threshold_seconds} 秒
                      </Descriptions.Item>
                    </Descriptions>
                  </>
                ) : !regressionCfg.exists ? (
                  <Alert
                    type="info"
                    showIcon
                    message="项目尚无 verify.yaml，未配置 regression 段"
                    description="开启周期性全量回归不会实际执行。点「使用 AI 生成」将引导 Administrator 起草验证契约（有测试体系时一并生成 regression 段）。"
                  />
                ) : (
                  <Alert
                    type="warning"
                    showIcon
                    message="未配置 regression 段"
                    description=".fenix/verify.yaml 存在但没有有效的 regression 段，开启周期性全量回归不会实际执行。点「使用 AI 生成」由 Administrator 探测测试体系后补写（不改动契约其它内容）。"
                  />
                )}
                <div style={{ marginTop: 12 }}>
                  <Button
                    onClick={handleRegressionAutodraft}
                    loading={regressionDrafting}
                    data-testid="regression-autodraft-btn"
                  >
                    使用 AI 生成
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="quality" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} data-testid="quality-save">
          保存
        </Button>
      </div>
    </div>
  );
}
