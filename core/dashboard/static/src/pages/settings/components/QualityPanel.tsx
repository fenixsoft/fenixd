import { Alert, Button, Card, Form, Switch, Typography, message } from 'antd';
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
    });
  }, [config.verify, form]);

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
            ocr（bin/ocr_review.py）审查本次改动，逐条评估发现并自行修正真实问题
            （误报可驳回）。需要环境已安装 ocr，未安装时自动按 unavailable 降级跳过。
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
