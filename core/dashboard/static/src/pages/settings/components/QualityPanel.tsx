import { Alert, Button, Card, Form, InputNumber, Select, Switch, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import { getOcrStatus, installOcr } from '@/services/dashboard';
import type { OcrStatus } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

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
  // ocr 环境探测状态：null=加载中；未安装时开关置灰并给出「一键安装」
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    form.setFieldsValue({
      impl_code_review: config.verify?.impl_code_review === true,
      // add-impl-code-review-tuning：三运行参数回填缺省（600/2/low——后端
      // read_config / read_effective_config 恒回显缺省，前端回填与之一致；
      // 既有开关「缺省不回显」约定不变：impl_code_review 缺席仍为关）
      impl_code_review_timeout_sec: config.verify?.impl_code_review_timeout_sec ?? 600,
      impl_code_review_concurrency: config.verify?.impl_code_review_concurrency ?? 2,
      impl_code_review_effort: config.verify?.impl_code_review_effort ?? 'low',
      // 周期性代码审查（2026-09-19 从项目页「代码审查」分面迁来）：
      // 开关是项目级配置（admin.code_review.enabled），归设置页而非项目页
      code_review_enabled: config.code_review?.enabled === true,
      // add-test-regression-tab：周期性全量回归开关（admin.regression.enabled）
      // 缺省 false；分面只读展示 + 手动触发，配置归设置页「质量」页签
      regression_enabled: config.regression?.enabled === true,
    });
  }, [config.verify, config.code_review, config.regression, form]);

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
      });
    } catch (err) {
      // 区分「校验失败」与「保存失败」（code-review item d91325bb73dd）：旧实现
      // 单一裸 catch 把 onSave 的网络/500 失败一并静默吞掉，用户得不到任何提示。
      message.error(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // 环境门控：ocr 未安装（或探测失败）时开关不可用——避免开启一个运行期必然
  // 降级跳过的开关。探测未返回（加载中）时同样置灰，避免先开后关的闪变。
  const ocrReady = ocr?.installed === true;

  return (
    <div>
      <h3>代码质量</h3>
      <Text type="secondary">实现阶段的代码质量门相关设置。</Text>
      {/* 统一 Form 包裹全部三个卡片（fix-verify-bug 2026-09-21）：旧实现把
          周期代码审查 / 周期全量回归两个开关放在 <Form> 外的 <div> 容器里，
          rc-field-form 的 Form.Item 只在 <form> 内注册字段——validateFields()
          不返回脱管字段，handleSave 恒提交 enabled:false（视觉开启但后端未
          持久化，api-regression-config-persisted 验证实测确证）。 */}
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Card style={{ marginTop: 12 }}>
          {/* 环境状态行：已装 → 绿色提示；未装 → 橙色提示 + 一键安装按钮 */}
          {ocr === null ? (
            <Text type="secondary">正在检测 open-code-review 环境…</Text>
          ) : ocr.installed ? (
            <Alert
              type="success"
              showIcon
              message="已安装 open-code-review"
              description={ocr.version || ocr.bin || '检测到 ocr 可执行文件'}
              data-testid="ocr-installed-alert"
            />
          ) : (
            <Alert
              type="warning"
              showIcon
              message="未检测到 open-code-review"
              description="代码质量审查依赖 ocr（@alibaba-group/open-code-review）。未安装时该开关不可用，运行期也会按 unavailable 降级跳过。"
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
          )}
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row） */}
          <div className="switch-inline-row">
            <Form.Item name="impl_code_review" valuePropName="checked" noStyle>
              <Switch data-testid="impl-code-review-switch" disabled={!ocrReady} />
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
              缺省回填 600 / 2 / low（后端 read_config / read_effective_config 恒回显缺省）。 */}
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
              data-testid="impl-code-review-concurrency"
            />
          </Form.Item>
          <Text type="secondary">
            默认 2。ocr 并发子任务上限（--concurrency）：实测 8 路并发同时打同一
            provider 网关会把首字节延迟放大到撞穿超时线；降到 2 以吞吐换稳定。
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
        </Card>
        <Card style={{ marginTop: 12 }}>
          {/* 与上方质量卡片共用同一 Form 实例（code-review item a7f58be138e4）：
              add-test-regression-tab 修复验证打回 BUG-01 的根因：旧实现中
              code_review_enabled / regression_enabled 两个开关 Form.Item 位于
              首个 Card 内 <Form> 之外（第二、三 Card 用 <div> 承载），
              rc-field-form 的 Form.Item 只在 <form> 内注册字段——
              validateFields() 不返回脱管字段，handleSave 恒提交 enabled:false
              （视觉开启但后端未持久化）。修复：统一 <Form> 包裹全部三个 Card
              （见首个 Card 上方注释），开关 Form.Item 在 <Form> 内部注册字段，
              validateFields() 才能返回 code_review_enabled / regression_enabled。 */}
          <div>
            {/* 周期性代码审查开关（2026-09-19 从项目页「代码审查」分面迁到本页签）：
                它是项目级配置（admin.code_review.enabled），与手动触发按钮的性质不同
                ——分面负责「看结果 + 手动触发」，配置归设置页统一管理。
                注：本条改动在 merge-back 中两次因「先 stash 后 merge」被丢弃，本卡片
                由 admin 处置（stash_pop_conflict）从 stash 找回，见 admin_disposition。 */}
            <div className="switch-inline-row">
              <Form.Item name="code_review_enabled" valuePropName="checked" noStyle>
                <Switch data-testid="code-review-enabled-switch" />
              </Form.Item>
              <span className="switch-inline-label">
                周期性代码审查
                <span className="label-note">（admin.code_review.enabled）</span>
              </span>
            </div>
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              开启后与每日自省同周期（admin.self_review.run_at 时点）自动派发
              code-review agent，审查窗口内开发 SPEC 的产品代码质量，问题沉淀到
              .fenix/code-review/items.jsonl 台账，供项目页「代码审查」分面展示与消费。
              需要环境已安装 ocr（未安装时审查仍以 LLM 逐文件执行，仅少了扫描加速）。
              手动触发（全仓库审查 / 当期提交审查）不受本开关约束。
            </Text>
          </div>
        </Card>
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
