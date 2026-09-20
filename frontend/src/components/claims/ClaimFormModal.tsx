/**
 * 台账条目的新建 / 编辑表单。
 *
 * 两个刻意的取舍：
 * 1. **日期用纯输入框**，不引 dayjs / DatePicker——项目其余部分（资料库的起止日期）
 *    就是纯文本 `YYYY-MM-DD`，格式由后端校验。多引一个日期库不值得。
 * 2. **列表型字段用「每行一条」的文本域或 tags 下拉**，而不是嵌套数组表单：证据来源
 *    有四个字段，用 Form.List 展开；而"决策 / 难点 / 验证"这种纯字符串列表，多行文本
 *    更快也更不容易点错。
 */
import { DeleteOutlined, PlusOutlined, SaveOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useEffect } from "react";
import { createClaim, updateClaim } from "../../api/claims";
import type { Claim, ClaimPayload, ClaimSource, SourceType } from "../../types";
import {
  CLAIM_CATEGORIES,
  RESPONSIBILITY_LEVELS,
  SOURCE_TYPES,
  SOURCE_TYPE_LABELS,
  VERIFICATION_STATUSES,
  VERIFICATION_STATUS_HINTS,
  emptyClaim,
} from "../../types";

/** 一句话讲清每个承担程度，用户不必猜"负责模块"和"主导交付"差在哪。 */
const RESPONSIBILITY_HINTS: Record<string, string> = {
  参与: "在他人安排下完成其中一部分工作",
  负责模块: "独立负责其中一个明确模块或方向",
  主导方案或交付: "方案由你定、交付由你推，其他人配合你",
  项目负责人: "对整个项目的结果负责",
};

const STATUS_OPTIONS = VERIFICATION_STATUSES.map((value) => ({
  value,
  label: `${value}——${VERIFICATION_STATUS_HINTS[value]}`,
}));

const RESPONSIBILITY_OPTIONS = RESPONSIBILITY_LEVELS.map((value) => ({
  value,
  label: `${value}——${RESPONSIBILITY_HINTS[value]}`,
}));

interface FormValues {
  title: string;
  category: string;
  subject: string;
  source_fact: string;
  candidate_wording: string;
  responsibility_level: string;
  verification_status: string;
  boundary: string;
  last_verified: string;
  allowed_uses: string[];
  risk_notes: string[];
  sources: ClaimSource[];
  decisions: string;
  difficulties: string;
  verification: string;
  result: string;
}

const EMPTY_VALUES: FormValues = {
  title: "",
  category: "项目经历",
  subject: "",
  source_fact: "",
  candidate_wording: "",
  responsibility_level: "参与",
  verification_status: "待确认",
  boundary: "",
  last_verified: "",
  allowed_uses: [],
  risk_notes: [],
  sources: [],
  decisions: "",
  difficulties: "",
  verification: "",
  result: "",
};

/** 多行文本 ↔ 字符串数组。空行丢掉，顺序保留。 */
function linesToText(lines: string[] | undefined): string {
  return (lines ?? []).join("\n");
}

function textToLines(text: string | undefined): string[] {
  return (text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function toValues(claim: Claim): FormValues {
  const details = claim.interview_details ?? {};
  return {
    ...EMPTY_VALUES,
    title: claim.title,
    category: claim.category,
    subject: claim.subject,
    source_fact: claim.source_fact,
    candidate_wording: claim.candidate_wording,
    responsibility_level: claim.responsibility_level,
    verification_status: claim.verification_status,
    boundary: claim.boundary,
    last_verified: claim.last_verified,
    allowed_uses: claim.allowed_uses,
    risk_notes: claim.risk_notes,
    sources: claim.sources,
    decisions: linesToText(details.decisions),
    difficulties: linesToText(details.difficulties),
    verification: linesToText(details.verification),
    result: details.result ?? "",
  };
}

function toPayload(values: FormValues): ClaimPayload {
  return {
    ...emptyClaim(),
    title: values.title.trim(),
    category: values.category as ClaimPayload["category"],
    subject: values.subject.trim(),
    source_fact: values.source_fact.trim(),
    candidate_wording: values.candidate_wording.trim(),
    responsibility_level: values.responsibility_level as ClaimPayload["responsibility_level"],
    verification_status: values.verification_status as ClaimPayload["verification_status"],
    boundary: values.boundary.trim(),
    last_verified: values.last_verified.trim(),
    allowed_uses: values.allowed_uses ?? [],
    risk_notes: values.risk_notes ?? [],
    sources: (values.sources ?? []).map((source) => ({
      type: source.type,
      location: (source.location ?? "").trim(),
      public: Boolean(source.public),
      note: (source.note ?? "").trim(),
    })),
    interview_details: {
      decisions: textToLines(values.decisions),
      difficulties: textToLines(values.difficulties),
      verification: textToLines(values.verification),
      result: values.result.trim() || null,
    },
  };
}

interface Props {
  open: boolean;
  claim: Claim | null;
  onClose: () => void;
  onSaved: (claim: Claim) => void;
}

export default function ClaimFormModal({ open, claim, onClose, onSaved }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const editing = claim !== null;

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue(claim ? toValues(claim) : EMPTY_VALUES);
  }, [open, claim, form]);

  const submit = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // 校验失败时 antd 已在字段旁给出提示
    }
    const payload = toPayload(values);
    try {
      const saved = editing ? await updateClaim(claim.id, payload) : await createClaim(payload);
      message.success(editing ? "已保存" : "已加入台账");
      onSaved(saved);
      onClose();
    } catch (error) {
      // 「已确认却还留着【待补】」这类自相矛盾由后端挡下，原样把中文原因显示出来，
      // 否则用户只会看到一个说得不清不楚的 422。
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  return (
    <Modal
      open={open}
      title={editing ? "编辑台账条目" : "新建台账条目"}
      onCancel={onClose}
      width={760}
      destroyOnClose
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={() => void submit()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" initialValues={EMPTY_VALUES}>
        {/* 这里刻意用普通 div 而不是 antd 的 Space：Space 会给每个子项再包一层
            `.ant-space-item`，flex 宽度落在内层 Form.Item 上、管不到真正的 flex 子项，
            结果就是窄列被挤成一条竖排文字。 */}
        <div className="claim-form-row">
          <Form.Item name="title" label="标题" className="claim-form-grow">
            <Input placeholder="便于检索的名字，例如「校园检索平台的检索接口」" maxLength={200} />
          </Form.Item>
          <Form.Item name="category" label="分类" className="claim-form-fixed">
            <Select options={CLAIM_CATEGORIES.map((value) => ({ value, label: value }))} />
          </Form.Item>
        </div>

        <Form.Item
          name="subject"
          label="主体"
          extra="这条主张关于谁：公司名 / 项目名 / 学校名 / 技能名。生成简历时据此回指到对应经历。"
        >
          <Input placeholder="例如「校园知识检索平台」" maxLength={200} />
        </Form.Item>

        <Form.Item
          name="source_fact"
          label="原始事实"
          extra="照实写，不做包装。它是之后核对一切表述的基准。"
          rules={[{ required: true, message: "请写清原始事实" }]}
        >
          <Input.TextArea
            rows={3}
            maxLength={8000}
            showCount
            placeholder="我实际做了什么、做到了什么程度"
          />
        </Form.Item>

        <Form.Item
          name="candidate_wording"
          label="简历表述"
          extra="准备写进简历的版本。不得比原始事实更强；还没核实的内容请用【待补：缺什么】标记。"
        >
          <Input.TextArea rows={2} maxLength={8000} placeholder="例如「实现检索接口并联调上线」" />
        </Form.Item>

        <div className="claim-form-row">
          <Form.Item name="responsibility_level" label="承担程度" className="claim-form-grow">
            <Select options={RESPONSIBILITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="verification_status" label="核实状态" className="claim-form-grow">
            <Select options={STATUS_OPTIONS} />
          </Form.Item>
          {/* 日期用固定宽度；DatePicker 值走 Dayjs，表单里仍存 YYYY-MM-DD 字符串（E12）。 */}
          <Form.Item
            name="last_verified"
            label="最近核实"
            className="claim-form-date"
            getValueProps={(value: string) => ({ value: value ? dayjs(value) : null })}
            normalize={(value: Dayjs | null) => (value ? value.format("YYYY-MM-DD") : "")}
          >
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
        </div>

        <Form.Item
          name="boundary"
          label="个人边界"
          extra="团队做了什么、你做了什么。已确认的条目会进正式简历，这句就是面试时的防线。"
        >
          <Input.TextArea
            rows={2}
            maxLength={1000}
            placeholder="例如「接口由本人实现，检索算法由另一位同学负责」"
          />
        </Form.Item>

        <Form.Item name="allowed_uses" label="可用范围">
          <Select
            mode="tags"
            placeholder="回车添加，例如「AI 岗简历」「HR 开场白」。留空表示不限。"
            open={false}
            suffixIcon={null}
          />
        </Form.Item>

        <Typography.Text type="secondary" className="claim-form-section">
          证据来源（只记去哪儿能找到，不要粘贴内容）
        </Typography.Text>
        <Form.List name="sources">
          {(fields, { add, remove }) => (
            <div className="claim-source-list">
              {fields.map((field) => (
                <Space key={field.key} size={8} align="start" className="claim-source-row">
                  <Form.Item name={[field.name, "type"]} initialValue="link" noStyle>
                    <Select
                      className="claim-source-type"
                      options={SOURCE_TYPES.map((value: SourceType) => ({
                        value,
                        label: SOURCE_TYPE_LABELS[value],
                      }))}
                    />
                  </Form.Item>
                  <Form.Item name={[field.name, "location"]} noStyle>
                    <Input
                      className="claim-source-location"
                      placeholder="链接、文件名或「导师证明可提供」"
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, "public"]}
                    valuePropName="checked"
                    initialValue={false}
                    noStyle
                  >
                    <Switch checkedChildren="公开" unCheckedChildren="不公开" />
                  </Form.Item>
                  <Button
                    type="text"
                    icon={<DeleteOutlined />}
                    onClick={() => remove(field.name)}
                    aria-label="删除这条证据"
                  />
                </Space>
              ))}
              <Button
                type="dashed"
                icon={<PlusOutlined />}
                onClick={() => add({ type: "link", public: false })}
              >
                添加证据来源
              </Button>
            </div>
          )}
        </Form.List>

        <Typography.Text type="secondary" className="claim-form-section">
          面试细节（能答上追问的部分；强主张尤其要填）
        </Typography.Text>
        <div className="claim-form-row">
          <Form.Item
            name="decisions"
            label="做过的决策"
            className="claim-form-grow"
            extra="每行一条"
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="difficulties" label="难点" className="claim-form-grow" extra="每行一条">
            <Input.TextArea rows={3} />
          </Form.Item>
        </div>
        <div className="claim-form-row">
          <Form.Item
            name="verification"
            label="怎么验证"
            className="claim-form-grow"
            extra="每行一条"
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="result" label="结果" className="claim-form-grow">
            <Input.TextArea rows={3} placeholder="没有可靠数字时写定性结果，不要编造" />
          </Form.Item>
        </div>

        <Form.Item name="risk_notes" label="风险备注" extra="面试里可能被追问什么、哪里还站不住。">
          <Select
            mode="tags"
            placeholder="回车添加，例如「指标口径未说明」"
            open={false}
            suffixIcon={null}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
