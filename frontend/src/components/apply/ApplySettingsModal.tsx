/**
 * 投递设置弹窗：间隔、上限、熔断阈值、默认招呼语与专用浏览器端口。
 *
 * 除了必填校验，每个字段都回显**出厂默认值**——用户改乱了设置后需要知道"原来的值是什么"，
 * 否则只能去翻文档或重装。
 */
import {
  Button,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  Typography,
  App,
} from "antd";
import { useEffect, useState } from "react";
import { getApplyConfig, listSites, updateApplyConfig } from "../../api/apply";
import { useApi } from "../../hooks/useApi";
import {
  BROWSER_CHOICE_META,
  type ApplyConfig,
  type ApplyConfigOut,
  type BrowserChoice,
  type SiteList,
} from "../../types";

const BROWSER_CHOICE_OPTIONS = (Object.keys(BROWSER_CHOICE_META) as BrowserChoice[]).map(
  (value) => ({
    value,
    label: BROWSER_CHOICE_META[value].label,
  }),
);

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved?: (config: ApplyConfigOut) => void;
}

function defaultsHint(value: string | number | boolean): string {
  return `出厂默认：${typeof value === "boolean" ? (value ? "开启" : "关闭") : value}`;
}

function ApplySettingsForm({ onClose, onSaved }: Omit<Props, "open">) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ApplyConfig>();
  const { data, loading, error } = useApi<ApplyConfigOut>(getApplyConfig, []);
  // 站点清单来自后端接口，前端不写死站点名；将来后端加站点这里自动多出选项。
  const { data: siteList } = useApi<SiteList>(listSites, []);
  const [saving, setSaving] = useState(false);
  const defaults = data?.defaults;
  // 只有选了「自定义路径」才需要填路径。
  const browserChoice = Form.useWatch("browser_choice", form);
  const siteOptions = (siteList?.sites ?? []).map((site) => ({
    value: site.key,
    label: site.display_name,
  }));

  useEffect(() => {
    if (data) form.setFieldsValue(data);
  }, [data, form]);

  const submit = async () => {
    let values: ApplyConfig;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      const saved = await updateApplyConfig(values);
      message.success("投递设置已保存");
      onSaved?.(saved);
      onClose();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存投递设置失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }
  if (error && !data) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text type="danger">{error}</Typography.Text>
        <Button onClick={onClose}>关闭</Button>
      </Space>
    );
  }

  return (
    <Form form={form} layout="vertical" onFinish={() => void submit()}>
      <Typography.Paragraph type="secondary">
        这些设置决定投递的节奏与安全网：岗位之间会随机等待，连续失败会自动暂停， 每日上限只统计
        <Typography.Text strong>成功投递</Typography.Text>的数量。
      </Typography.Paragraph>

      <Space size={16} wrap>
        <Form.Item
          name="interval_seconds"
          label="岗位间隔（秒）"
          extra={defaults && defaultsHint(defaults.interval_seconds)}
          rules={[{ required: true, message: "请填写岗位间隔" }]}
        >
          <InputNumber min={1} max={600} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item
          name="interval_jitter_seconds"
          label="随机抖动（秒）"
          extra={defaults && defaultsHint(defaults.interval_jitter_seconds)}
        >
          <InputNumber min={0} max={300} style={{ width: 160 }} />
        </Form.Item>
      </Space>

      <Space size={16} wrap>
        <Form.Item
          name="daily_limit"
          label="每日上限（成功数）"
          extra={defaults && defaultsHint(defaults.daily_limit)}
          rules={[{ required: true, message: "请填写每日上限" }]}
        >
          <InputNumber min={1} max={1000} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item
          name="per_task_limit"
          label="单批上限"
          extra={defaults && defaultsHint(defaults.per_task_limit)}
        >
          <InputNumber min={1} max={200} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item
          name="breaker_threshold"
          label="连续失败熔断阈值"
          extra={defaults && defaultsHint(defaults.breaker_threshold)}
        >
          <InputNumber min={1} max={20} style={{ width: 160 }} />
        </Form.Item>
      </Space>

      <Form.Item
        name="default_greeting"
        label="默认招呼语"
        extra="队列条目没有单独填写招呼语时使用；投递前可逐岗位预览并修改。"
      >
        <Input.TextArea rows={2} maxLength={1000} showCount />
      </Form.Item>

      <Divider plain style={{ margin: "4px 0 16px" }} />

      <Form.Item
        name="site_key"
        label="当前招聘网站"
        extra="目前仅支持一个招聘网站，后续会陆续增加；新增站点无需你手动配置。"
      >
        <Select options={siteOptions} style={{ maxWidth: 280 }} placeholder="使用默认站点" />
      </Form.Item>

      <Divider plain style={{ margin: "4px 0 16px" }} />

      <Space size={16} wrap>
        <Form.Item
          name="browser_choice"
          label="投递台使用的浏览器"
          extra={browserChoice ? BROWSER_CHOICE_META[browserChoice]?.hint : undefined}
        >
          <Select options={BROWSER_CHOICE_OPTIONS} style={{ width: 220 }} />
        </Form.Item>
        <Form.Item
          name="browser_path"
          label="自定义浏览器路径"
          extra="仅在「自定义路径」时生效；必须是真实存在的可执行文件。"
        >
          <Input
            placeholder="例如：C:\\Program Files\\MyBrowser\\browser.exe"
            disabled={browserChoice !== "custom"}
            style={{ width: 320 }}
          />
        </Form.Item>
      </Space>

      <Form.Item
        name="browser_port"
        label="投递专用浏览器调试端口"
        extra={defaults && defaultsHint(defaults.browser_port)}
      >
        <InputNumber min={1024} max={65535} style={{ width: 160 }} />
      </Form.Item>

      <Form.Item
        name="skip_same_company"
        label="同公司只投一个岗位"
        valuePropName="checked"
        // 光写"同公司只投一个岗位"会被读成全历史：用户会以为投过百度就永远不能再投百度的
        // 其他岗位。**作用域就是本批**，必须写在这里——开关的语义只能由它的说明来界定。
        extra={
          <>
            只在本批内生效：同一批里同一家公司的多个岗位只投最先的那个，其余标为「已跳过」
            并写明原因；换一批再遇到这家公司仍会投。判断忽略公司名的空格与大小写，
            失败的那次也算「投过」（招呼语可能已经发出去了）。
            {defaults && <div>{defaultsHint(defaults.skip_same_company)}</div>}
          </>
        }
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="confirm_real_gap"
        label="默认允许「真实缺口」岗位直接入队"
        valuePropName="checked"
        extra="默认关闭：命中真实缺口的岗位需要你逐条确认；开启后仍会在记录里标注。"
      >
        <Switch />
      </Form.Item>

      <Space>
        <Button onClick={onClose}>取消</Button>
        <Button type="primary" loading={saving} onClick={() => void submit()}>
          保存设置
        </Button>
      </Space>
    </Form>
  );
}

export default function ApplySettingsModal({ open, onClose, onSaved }: Props) {
  return (
    <Modal
      title="投递设置"
      open={open}
      onCancel={onClose}
      footer={null}
      width={620}
      destroyOnHidden
    >
      {open && <ApplySettingsForm onClose={onClose} onSaved={onSaved} />}
    </Modal>
  );
}
