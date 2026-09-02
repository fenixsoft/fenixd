import { Button, Card, Form, InputNumber, Typography } from 'antd';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';

const { Text } = Typography;

interface MiscSettingsPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
}

export default function MiscSettingsPanel({ config, onSave }: MiscSettingsPanelProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      keep: config.runs?.keep ?? 50,
      auto_threshold: config.archive?.auto_threshold ?? 50,
    });
  }, [config.runs, config.archive, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      await onSave({
        runs: {
          keep: values.keep,
        },
        // add-spec-archive：自动归档阈值（0 = 禁用）
        archive: {
          auto_threshold: values.auto_threshold,
        },
      });
    } catch {
      // 校验失败：antd 已在表单内渲染 explain-error 提示，无需额外日志
      // （避免触发验证的 no_console_error 断言）。
    }
  };

  return (
    <div>
      <h3>其他</h3>
      <Text type="secondary">不属于其它分类的杂项设置。</Text>
      <Card style={{ marginTop: 12 }}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="keep"
            label={
              <>
                运行产物保留数量<span className="label-note">（runs.keep）</span>
              </>
            }
            rules={[{ required: true, message: '请输入保留数量' }]}
          >
            <InputNumber min={1} step={10} style={{ width: '100%' }} />
          </Form.Item>
          <Text type="secondary">
            默认 50。每个项目保留的最近运行产物文件数；超出的产物自动移入{' '}
            <code>.fenix/runs/archive/</code> 归档（不删除），运行时间轴、运行历史与耗时统计仍可回看归档记录。保存后立即生效。
          </Text>

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
            style={{ marginTop: 24 }}
          >
            <InputNumber step={10} style={{ width: '100%' }} />
          </Form.Item>
          <div>
            <Text type="secondary">
              默认 50。已完成（done/pushed）的 SPEC 数量超过此阈值时，自动将最久完成的归档到 archive 目录（保留 STATE.md 条目，可在「已归档」视图查看）。
              0 = 禁用。超过阈值时自动归档完成最久的 SPEC。保存后立即生效，无需重启 daemon。
            </Text>
          </div>
        </Form>
      </Card>
      <div style={{ textAlign: 'right', marginTop: 24 }}>
        <Button type="primary" onClick={handleSave} data-testid="misc-save">
          保 存
        </Button>
      </div>
    </div>
  );
}
