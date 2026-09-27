import { Button, Card, Form, InputNumber, Switch, Typography, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import {
  knowledgeSectionFromSwitches,
  knowledgeSwitchDesc,
  knowledgeSwitchesFromConfig,
} from '../knowledgeSettings';

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
  // 用户编辑置脏：切页签/作用域前由 index 经 anyPanelDirty 弹丢弃确认
  // （code-review item 8a3eb01dc2b9）
  const { setDirty } = usePanelDirty();
  // 保存重入守卫（code-review item bbc939741560，比照 TokenBudgetPanel
  // 53b14fb31196）：onSave 是异步落盘 + 父组件重载，请求在飞期间连点「保存」
  // 会重复提交保存请求——saving 期间置 loading/disabled 并在入口短路。
  const [saving, setSaving] = useState(false);

  // 回填门控（code-review item 0a2bd3f20fcd，比照 AgentModelPanel 9f98edec21fa）：
  // 无条件 setFieldsValue 会在其它面板保存触发父组件 setConfig 时，用外部
  // config 覆盖本面板用户正在编辑、尚未保存的阈值。改为序列化比较，只在
  // 内容真变化时回填。
  const lastBackfillRef = useRef('');
  useEffect(() => {
    const kb = knowledgeSwitchesFromConfig(config.knowledge);
    const next = {
      auto_threshold: config.archive?.auto_threshold ?? 50,
      // add-knowledge-atlas：knowledge.enabled 开关回填（缺省 true，与后端缺省一致）
      knowledge_enabled: config.knowledge?.enabled ?? true,
      // add-knowledge-atlas-maintenance：维护车道开关回填（缺省 true，与后端缺省一致）
      audit_enabled: kb.auditEnabled,
      graph_enabled: kb.graphEnabled,
    };
    const key = JSON.stringify(next);
    if (key === lastBackfillRef.current) return;
    lastBackfillRef.current = key;
    form.setFieldsValue(next);
  }, [config.archive, config.knowledge, form]);

  const handleSave = async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    try {
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
          // add-knowledge-atlas：知识真相源总开关（false 时归档不派发蒸馏）
          // + add-knowledge-atlas-maintenance：维护车道开关——合并后同节三键共存，
          // 组装为单一 knowledge 键（对象字面量出现两个同名键会被后者整体覆盖）
          knowledge: {
            enabled: values.knowledge_enabled,
            ...knowledgeSectionFromSwitches({
              auditEnabled: values.audit_enabled,
              graphEnabled: values.graph_enabled,
            }).knowledge,
          },
        });
      } catch (error) {
        // 保存持久化失败：给用户显式反馈而非静默
        message.error(`保存失败：${error instanceof Error ? error.message : String(error)}`);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h3>归档</h3>
      <Text type="secondary">SPEC 归档与知识真相源维护设置。</Text>
      <Form form={form} layout="vertical" onValuesChange={() => setDirty(true)}>
        <Card style={{ marginTop: 12 }}>
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
                type: 'integer',
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
        </Card>
        {/* add-knowledge-atlas-maintenance 任务 1.2：知识真相源维护车道开关 */}
        <Card style={{ marginTop: 12 }}>
          <h3 style={{ marginTop: 0 }}>知识真相源维护</h3>
          <Text type="secondary">
            spec/knowledge/ 真相源的周期维护车道开关；关闭后对应车道静默跳过。
          </Text>
          <Form.Item
            name="audit_enabled"
            label={
              <>
                每日知识体检<span className="label-note">（knowledge.audit_enabled）</span>
              </>
            }
            valuePropName="checked"
            style={{ marginTop: 16 }}
          >
            <Switch data-testid="knowledge-audit-switch" />
          </Form.Item>
          <Text type="secondary">{knowledgeSwitchDesc('audit')}</Text>
          <Form.Item
            name="graph_enabled"
            label={
              <>
                知识关系图生成<span className="label-note">（knowledge.graph_enabled）</span>
              </>
            }
            valuePropName="checked"
            style={{ marginTop: 16 }}
          >
            <Switch data-testid="knowledge-graph-switch" />
          </Form.Item>
          <Text type="secondary">{knowledgeSwitchDesc('graph')}</Text>
        </Card>
      </Form>
      {/* add-knowledge-atlas：知识真相源总开关（knowledge.enabled）。
          关闭后归档照常完成、但不派发蒸馏 run，项目知识页签显示禁用占位。 */}
      <Card style={{ marginTop: 16 }} data-testid="knowledge-settings-card">
        <Form form={form} layout="vertical">
          <Form.Item
            name="knowledge_enabled"
            valuePropName="checked"
            // SSR/首帧缺省：useEffect 回填在服务端渲染不执行，initialValue 保证
            // 缺省（true）与后端缺省一致；挂载后 setFieldsValue 以 config 为准
            initialValue={config.knowledge?.enabled ?? true}
            style={{ marginBottom: 8 }}
          >
            <Switch data-testid="knowledge-enabled-switch" />
          </Form.Item>
          <Text strong>知识真相源</Text>
          <div>
            <Text type="secondary" data-testid="knowledge-enabled-desc">
              归档完成后自动派发蒸馏 run，把该 SPEC 的当前业务规则蒸馏进
              spec/knowledge/ 真相源（总目录 + 能力页 + ADR 索引）。
              关闭后归档照常完成，但不再派发蒸馏，项目知识页签显示「知识真相源已禁用」占位。
              保存后约 30s 配置热更新生效，无需重启 daemon。
            </Text>
          </div>
        </Form>
      </Card>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="misc" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="misc-save">
          保 存
        </Button>
      </div>
    </div>
  );
}
