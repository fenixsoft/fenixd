import { Button, Card, Form, InputNumber, Typography, message } from 'antd';
import { useEffect, useRef } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';

const { Text } = Typography;

interface MiscSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function MiscSettingsPanel({ config, onSave, project, onConfigSynced }: MiscSettingsPanelProps) {
  const [form] = Form.useForm();

  // 回填门控（code-review item 0a2bd3f20fcd，比照 AgentModelPanel 9f98edec21fa）：
  // 无条件 setFieldsValue 会在其它面板保存触发父组件 setConfig 时，用外部
  // config 覆盖本面板用户正在编辑、尚未保存的阈值。改为序列化比较，只在
  // 内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const next = { auto_threshold: config.archive?.auto_threshold ?? 50 };
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    form.setFieldsValue(next);
  }, [config.archive, form]);

  const handleSave = async () => {
    // 分离「表单校验」与「保存持久化」（code-review item 9125d4a7f7b4，比照
    // AgentModelPanel 3086b7e96c4f）：旧实现两者混在同一 try/catch 且静默吞掉，
    // onSave 拒绝（网络失败/500）时用户点击「保存」后无任何反馈。
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示，无需额外日志
      // （避免触发验证的 no_console_error 断言）。
      return;
    }
    try {
      await onSave({
        // add-spec-archive：自动归档阈值（0 = 禁用）
        archive: {
          auto_threshold: values.auto_threshold,
        },
      });
    } catch (error) {
      // 保存持久化失败：给用户显式反馈而非静默
      message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div>
      <h3>归档</h3>
      <Text type="secondary">SPEC 归档相关设置。</Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          {/* add-spec-archive：自动归档阈值置于面板首字段——验证场景以
              .ant-input-number input 定位首字段（引擎 .first），归档阈值须居前 */}
          <Form.Item
            name="auto_threshold"
            label={
              <>
                自动归档阈值<span className="label-note">（archive.auto_threshold）</span>
              </>
            }
            rules={[
              { required: true, message: '请输入自动归档阈值' },
              // 非负整数校验（0 = 禁用；负数/非整数被表单校验拦截，不写入配置）。
              // 注意：不能用 InputNumber 的 min 属性代替——min 会在 blur 时把 -5
              // 钳制回 0，用户永远看不到"非法输入被拦截"的表单错误提示。
              {
                type: 'number',
                min: 0,
                message: '阈值必须为非负整数（0 = 禁用）',
              },
            ]}
          >
            <InputNumber step={10} style={{ width: '100%' }} addonAfter="个" />
          </Form.Item>
          <Text type="secondary">
            默认 50。已完成（done/pushed）的 SPEC 数量超过此阈值时，自动将最久完成的归档到 archive 目录（保留 STATE.md 条目，可在「已归档」视图查看）。
            0 = 禁用。超过阈值时自动归档完成最久的 SPEC。保存后立即生效，无需重启 daemon。
          </Text>
        </Form>
      </Card>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="misc" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} data-testid="misc-save">
          保 存
        </Button>
      </div>
    </div>
  );
}
