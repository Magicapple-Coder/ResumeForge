import { Form, Input, Modal } from "antd";
import { useEffect } from "react";
import type { OfficialSite, OfficialSitePayload } from "../../types";

interface Props {
  open: boolean;
  site?: OfficialSite | null;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: OfficialSitePayload) => Promise<void>;
}

/** 添加与编辑共用的公司源表单；识别动作仍由页面层负责。 */
export default function OfficialSiteEditorModal({
  open,
  site,
  submitting,
  onCancel,
  onSubmit,
}: Props) {
  const [form] = Form.useForm<OfficialSitePayload>();
  const editing = site !== null && site !== undefined;

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      company: site?.company ?? "",
      careers_url: site?.careers_url ?? "",
      homepage_url: site?.homepage_url ?? "",
    });
  }, [form, open, site]);

  const handleOk = async () => {
    const values = await form.validateFields();
    await onSubmit(values);
    form.resetFields();
  };

  return (
    <Modal
      title={editing ? "编辑公司信息" : "添加公司"}
      open={open}
      onCancel={onCancel}
      onOk={() => void handleOk()}
      confirmLoading={submitting}
      okText={editing ? "保存并重新识别" : "添加并识别"}
      cancelText="取消"
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="company"
          label="公司名称"
          rules={[{ required: true, message: "请填写公司名称" }]}
        >
          <Input placeholder="例如：示例科技有限公司" maxLength={128} />
        </Form.Item>
        <Form.Item name="careers_url" label="招聘页地址" extra="填了这一项识别最准">
          <Input placeholder="例如：https://boards.example.com/company" maxLength={512} />
        </Form.Item>
        <Form.Item name="homepage_url" label="官网地址" extra="至少填一个">
          <Input placeholder="例如：https://www.example.com" maxLength={512} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
