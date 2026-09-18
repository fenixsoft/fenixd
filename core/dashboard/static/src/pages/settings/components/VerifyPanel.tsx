import { Alert, Button, Card, Form, Input, Radio, Space, Switch, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useEffect } from 'react';
import type { ConfigData } from '@/services/dashboard';
import SyncFromUserButton, { SETTINGS_ACTIONS_ROW_STYLE } from './SyncFromUserButton';

const { Text } = Typography;

// 产物路径逐项前端校验（与后端 validate_build_artifact_paths 同口径，仅为即时报错；
// 写入权威仍在后端，非法项在 POST /api/config 被 400 拒绝）。
function artifactPathRule(rules: unknown, value: unknown): Promise<void> {
  const v = typeof value === 'string' ? value.trim() : '';
  if (!v) return Promise.reject(new Error('路径不能为空'));
  if (v.startsWith('/')) return Promise.reject(new Error('不能是绝对路径'));
  if (v.split('/').includes('..')) return Promise.reject(new Error("不能含 '..' 路径段"));
  if (!v.includes('*') && !v.endsWith('/'))
    return Promise.reject(new Error("目录前缀须以 '/' 结尾，或使用含 '*' 的通配"));
  return Promise.resolve();
}

interface VerifyPanelProps {
  config: ConfigData;
  onSave: (values: Partial<ConfigData>) => Promise<void>;
  /** 当前项目名；项目级作用域才显示「同步用户级设置」按钮，且产物路径可编辑 */
  project?: string;
  /** 同步成功后回填配置（父组件 setConfig 驱动表单刷新） */
  onConfigSynced?: (config: ConfigData) => void;
}

export default function VerifyPanel({ config, onSave, project, onConfigSynced }: VerifyPanelProps) {
  const [form] = Form.useForm();
  // 产物路径为项目级键：用户级作用域下只读展示（无 project 即用户级）
  const artifactEditable = Boolean(project);

  useEffect(() => {
    form.setFieldsValue({
      static_scope: config.verify?.static_scope || 'main',
      deps_mode: config.verify?.deps_mode || 'hardlink',
      serving_reclaim_enabled: config.verify?.serving_reclaim?.enabled ?? true,
      impl_code_review: config.verify?.impl_code_review === true,
      build_artifact_paths: (config.worktree?.build_artifact_paths || []).map(
        (p) => ({ path: p }),
      ),
    });
  }, [config.verify, config.worktree, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload: Partial<ConfigData> = {
        verify: {
          static_scope: values.static_scope,
          deps_mode: values.deps_mode,
          serving_reclaim: { enabled: values.serving_reclaim_enabled },
          impl_code_review: values.impl_code_review === true,
        },
      };
      // 产物路径仅项目级可写（用户级作用域下该卡片只读，不提交该键）
      if (artifactEditable) {
        payload.worktree = {
          build_artifact_paths: (values.build_artifact_paths || [])
            .map((row: { path?: string }) => (row?.path || '').trim())
            .filter((p: string) => p.length > 0),
        };
      }
      await onSave(payload);
    } catch (error) {
      console.error('Validation failed:', error);
    }
  };

  return (
    <div>
      <h3>验证契约</h3>
      <Text type="secondary">
        静态验证契约（.fenix/verify.yaml）的被测实例服务范围。两种范围都会在
        每轮验证前执行契约的 prepare 构建步骤，并把验证场景 URL 全量改写到本次启动的实例。
      </Text>
      {/* 单一 Form 承载两张卡片：产物路径卡片的 Form.List 必须处于 Form 上下文内，
          否则 add/remove 会落到 rc-field-form 的默认空上下文（warning 桩），
          点击「添加产物路径」静默无反应。 */}
      <Form form={form} layout="vertical">
        <Card style={{ marginTop: 12 }}>
          <Form.Item
            name="static_scope"
            label={
              <>
                验证实例范围<span className="label-note">（verify.static_scope）</span>
              </>
            }
            rules={[{ required: true, message: '请选择服务范围' }]}
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="main">
                  <strong>main</strong> — 在 main 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在主树构建并启动被测实例。实现合并进主树后产物必然新鲜，
                      与现有运行实例共享，资源占用最小。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="worktree">
                  <strong>worktree</strong> — 在 worktree 起服务进行验证
                  <div>
                    <Text type="secondary">
                      在专用 serving worktree 内构建并启动服务，与主树运行实例
                      完全隔离（验证流量不影响主实例）。每次 HEAD 变化自动重建
                      worktree 与产物。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="deps_mode"
            label={
              <>
                依赖供给模式<span className="label-note">（verify.deps_mode）</span>
              </>
            }
            rules={[{ required: true, message: '请选择依赖供给模式' }]}
            extra="设置 worktree 中 node_modules 的引用方式，仅使用 node.js 的项目需要设置此选项"
          >
            <Radio.Group>
              <div style={{ display: 'block', marginBottom: 16 }}>
                <Radio value="prefer-offline">
                  <strong>prefer-offline</strong> — npm 缓存安装
                  <div>
                    <Text type="secondary">
                      在 worktree 内 npm ci --prefer-offline（锁文件严格安装、
                      走用户级 npm 缓存），失败回退 npm install。无共享 inode，
                      最安全；首次安装约数十秒。
                    </Text>
                  </div>
                </Radio>
              </div>
              <div style={{ display: 'block' }}>
                <Radio value="hardlink">
                  <strong>hardlink</strong> — 主树硬链接副本（默认）
                  <div>
                    <Text type="secondary">
                      秒级完成、共享 inode 不占双倍空间。npm 更新包 = 重新解包
                      （新 inode），主树不受影响；但构建缓存等 in-place 写入会
                      穿透共享 inode——避免主树与 worktree 并发构建。
                    </Text>
                  </div>
                </Radio>
              </div>
            </Radio.Group>
          </Form.Item>
          {/* 开关行与其它设置页一致：开关在前、名称紧随同行（.switch-inline-row），
              开关控件不带「开/关」文字（与其余开关统一） */}
          <div className="switch-inline-row">
            <Form.Item name="serving_reclaim_enabled" valuePropName="checked" noStyle>
              <Switch data-testid="serving-reclaim-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              serving 目录自动回收
              <span className="label-note">（verify.serving_reclaim.enabled）</span>
            </span>
          </div>
          <Text type="secondary">
            daemon 启动时与周期清扫对 .fenix/verify-serving/ 下无主 worktree（spec 不在
            changes/archive、未登记、无活进程、超宽限期）执行 git worktree remove --force +
            prune，并按同判据回收 &lt;spec&gt;-boot.log。关闭后不再自动回收（存量目录需人工清理）。
          </Text>
          {/* 收尾代码质量审查：沿用同款开关行（add-impl-code-review-gate 3.2 的
              impl_code_review 键在主树已入库，重构时保留，仅改呈现形态） */}
          <div className="switch-inline-row" style={{ marginTop: 24 }}>
            <Form.Item name="impl_code_review" valuePropName="checked" noStyle>
              <Switch data-testid="impl-code-review-switch" />
            </Form.Item>
            <span className="switch-inline-label">
              收尾代码质量审查
              <span className="label-note">（verify.impl_code_review）</span>
            </span>
          </div>
          <Text type="secondary">
            开启后实现者会在全部 tasks.md 任务完成、提交之后、写结果文件之前调用
            ocr（bin/ocr_review.py）审查本次改动，逐条评估发现并自行修正真实问题
            （误报可驳回）。需要环境已安装 ocr（npm install -g
            @alibaba-group/open-code-review），未安装时自动按 unavailable 降级跳过。
          </Text>
        </Card>

        {/* 构建产物路径：标题与说明置于卡片外，与上方「验证契约」节同构 */}
        <h3 style={{ marginTop: 32 }}>构建产物路径</h3>
        <Text type="secondary">
          worktree.build_artifact_paths —— 声明项目的构建产物路径，供 merge-back WIP
          重叠检查把产物与语义内容区分处理（产物对齐 HEAD、不进入 stash，避免 pop
          冲突与误报告警）。支持目录前缀（如 dist/，须以 / 结尾）与文件通配（如
          release-*.zip，含 *）；留空时回退框架默认仅在 core/dashboard/static 内判定。
        </Text>
        <Card style={{ marginTop: 12 }} data-testid="artifact-paths-card">
          {artifactEditable ? (
            <Form.List name="build_artifact_paths">
              {(fields, { add, remove }) => (
                <>
                  {fields.map((field) => (
                    <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                      <Form.Item
                        name={[field.name, 'path']}
                        rules={[{ validator: artifactPathRule }]}
                        style={{ marginBottom: 0, minWidth: 280 }}
                      >
                        <Input placeholder="例如 dist/ 或 release-*.zip" data-testid="artifact-path-input" />
                      </Form.Item>
                      <Button
                        type="text"
                        danger
                        icon={<MinusCircleOutlined />}
                        aria-label="删除此行"
                        onClick={() => remove(field.name)}
                      />
                    </Space>
                  ))}
                  <Button
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() => add({ path: '' })}
                    data-testid="artifact-path-add"
                  >
                    添加产物路径
                  </Button>
                </>
              )}
            </Form.List>
          ) : (
            <>
              <Alert
                type="info"
                showIcon
                message="构建产物路径为项目级设置，用户级作用域下不可编辑。请在页面右上角把「作用域」切换到对应项目后添加或修改。"
                data-testid="artifact-paths-scope-hint"
              />
              {config.worktree?.build_artifact_paths?.length ? (
                <ul style={{ margin: '12px 0 0', paddingLeft: 20 }}>
                  {config.worktree.build_artifact_paths.map((p, i) => (
                    <li key={i}>
                      <code>{p}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
                  未配置（使用框架默认判定集合）
                </Text>
              )}
            </>
          )}
        </Card>
      </Form>
      <div style={project ? SETTINGS_ACTIONS_ROW_STYLE : { textAlign: 'right', marginTop: 24 }}>
        {project && onConfigSynced && (
          <SyncFromUserButton project={project} page="verify" onSynced={onConfigSynced} />
        )}
        <Button type="primary" onClick={handleSave} data-testid="verify-save">
          保存
        </Button>
      </div>
    </div>
  );
}
