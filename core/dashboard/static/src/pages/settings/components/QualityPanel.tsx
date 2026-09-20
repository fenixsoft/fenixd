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
    });
  }, [config.verify, config.code_review, form]);

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
      const res = await installOcr();
      // 安装成功后重新探测，解锁开关
      const fresh = await getOcrStatus();
      setOcr(fresh);
      message.success(
        res.version ? `open-code-review 安装成功：${res.version}` : 'open-code-review 安装成功',
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`安装失败：${msg}`);
    } finally {
      setInstalling(false);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
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
      });
    } catch {
      // 校验失败：antd 已在表单内渲染提示，无需额外日志
      // （避免触发验证的 no_console_error 断言）。
    }
  };

  // 环境门控：ocr 未安装（或探测失败）时开关不可用——避免开启一个运行期必然
  // 降级跳过的开关。探测未返回（加载中）时同样置灰，避免先开后关的闪变。
  const ocrReady = ocr?.installed === true;

  return (
    <div>
      <h3>代码质量</h3>
      <Text type="secondary">实现阶段的代码质量门相关设置。</Text>
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
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
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
        </Form>
      </Card>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
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
        </Form>
      </Card>
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
