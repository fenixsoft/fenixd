import { Button, Card, Form, InputNumber, Switch, Typography } from 'antd';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton from './SyncFromUserButton';
import { SETTINGS_ACTIONS_ROW_STYLE } from '../styles';
import { usePanelDirty } from '../panelDirty';
import { useGatedFormPanel } from '../useGatedFormPanel';
import {
  knowledgeSectionFromSwitches,
  knowledgeSwitchDesc,
  knowledgeSwitchesFromConfig,
} from '../knowledgeSettings';

const { Text } = Typography;

// 表单值的单一构建来源（code-review item 10c30b44ba75，比照 ParallelSettingsPanel
// 3f4e251a395c 范式）：initialValues 与回填门控此前是两份逐字段重复的字面量
// （knowledge_enabled 还另有 initialValue 第三来源），Form 首帧无初值——
// auto_threshold 空输入框、audit_enabled 显示关，需等 paint 后的回填 effect 才
// 显示真实配置，且同卡两开关缺省来源不一致。收敛为单个纯函数供两处共用。
const buildFormValues = (cfg: ConfigData) => {
  const kb = knowledgeSwitchesFromConfig(cfg.knowledge);
  return {
    auto_threshold: cfg.archive?.auto_threshold ?? 50,
    // add-knowledge-atlas：knowledge.enabled 开关（缺省 true，与后端缺省一致）
    knowledge_enabled: cfg.knowledge?.enabled ?? true,
    // add-knowledge-atlas-maintenance：维护车道开关（缺省 true，与后端缺省一致）
    audit_enabled: kb.auditEnabled,
  };
};

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
  // 表单脚手架统一走 useGatedFormPanel（code-review item 5c5a259b8443）：
  // savingRef 重入守卫（原 item bbc939741560 / ab90b32016f3）、序列化比较回填
  // 门控（原 item 0a2bd3f20fcd）、校验/持久化分离的 handleSave（原 item
  // 9125d4a7f7b4）由 hook 承载；本面板保留字段映射（buildFormValues）与保存
  // 载荷组装。
  const { saving, initialValues, handleSave } = useGatedFormPanel({
    form,
    buildValues: () => buildFormValues(config),
    backfillDeps: [config.archive, config.knowledge],
    onSave,
    buildPayload: (values): Partial<ConfigData> => ({
      // add-spec-archive：自动归档阈值（0 = 禁用）
      archive: {
        auto_threshold: values.auto_threshold,
      },
      // add-knowledge-atlas：知识真相源总开关（false 时归档不派发蒸馏）
      // + add-knowledge-atlas-maintenance：维护车道开关——合并后同节两键共存，
      // 组装为单一 knowledge 键（对象字面量出现两个同名键会被后者整体覆盖；
      // graph_enabled 已随 graphify 生成功能取消而下线，不再由本页读写，
      // 后端逐键合并，配置文件中的存量键原样保留）
      knowledge: {
        enabled: values.knowledge_enabled,
        ...knowledgeSectionFromSwitches({
          auditEnabled: values.audit_enabled,
        }).knowledge,
      },
    }),
  });

  return (
    <div>
      <h3>归档</h3>
      <Text type="secondary">SPEC 归档与知识真相源维护设置。</Text>
      <Form form={form} initialValues={initialValues} layout="vertical" onValuesChange={() => setDirty(true)}>
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
        {/* 真相源：标题与说明置于卡片外，与上方「归档」节同构
            （VerifyPanel「构建产物路径」节同款）。graphify 生成功能已取消
            （2026-09-29 用户定调），graph_enabled 开关随之移除。 */}
        <h3 style={{ marginTop: 32 }}>真相源</h3>
        <Text type="secondary">
          spec/knowledge/ 真相源的周期维护车道开关；关闭后对应车道静默跳过。
        </Text>
        {/* add-knowledge-atlas：知识真相源总开关（knowledge.enabled）+ 维护车道
            开关（knowledge.audit_enabled）同卡共存。本卡必须留在上方唯一 Form 内
            （code-review item 0dddde607278）：rc-field-form 在 render 期无条件
            setCallbacks，同一 form 实例被两个 <Form> 连接时后渲染者整体覆盖前者，
            单独再开一个 Form 会把 onValuesChange 置脏回调冲掉，导致整个面板脏
            标记失效。 */}
        <Card style={{ marginTop: 12 }} data-testid="knowledge-settings-card">
          {/* 总开关居卡内首项；关闭后归档照常完成、但不派发蒸馏 run，
              项目知识页签显示禁用占位。开关行内联样式（.switch-inline-row），
              与全站设置页一致：开关在前、名称紧随同行。 */}
          <div className="switch-inline-row">
            <Form.Item name="knowledge_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="knowledge-enabled-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              知识真相源<span className="label-note">（knowledge.enabled）</span>
            </span>
          </div>
          <Text type="secondary" data-testid="knowledge-enabled-desc">
            归档完成后自动派发蒸馏 run，把该 SPEC 的当前业务规则蒸馏进
            spec/knowledge/ 真相源（总目录 + 能力页 + ADR 索引）。
            关闭后归档照常完成，但不再派发蒸馏，项目知识页签显示「知识真相源已禁用」占位。
            保存后约 30s 配置热更新生效，无需重启 daemon。
          </Text>
          {/* add-knowledge-atlas-maintenance 任务 1.2：知识真相源维护车道开关 */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="audit_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="knowledge-audit-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              每日知识体检<span className="label-note">（knowledge.audit_enabled）</span>
            </span>
          </div>
          <Text type="secondary">{knowledgeSwitchDesc()}</Text>
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="misc" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} loading={saving} disabled={saving} data-testid="misc-save">
          保存
        </Button>
      </div>
    </div>
  );
}
