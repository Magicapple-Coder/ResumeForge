/** 岗位新增/编辑弹窗：手动添加岗位信息。 */
import { FileSearchOutlined } from "@ant-design/icons";
import { Alert, App, Button, Form, Input, Modal, Select } from "antd";
import { useEffect, useRef, useState } from "react";
import { createJob, parseJobText, updateJob } from "../api/jobs";
import { useImageStaging } from "../hooks/useImageStaging";
import ImageStagingField from "./ImageStagingField";
import RecognizedTextField from "./RecognizedTextField";
import type { Job, JobPayload } from "../types";

interface Props {
  open: boolean;
  /** 传入岗位表示编辑，null 表示新增 */
  initial: Job | null;
  onClose: () => void;
  onSaved: () => void;
}

const JOB_TYPE_OPTIONS = ["校招", "实习", "社招", "其他"].map((value) => ({ value, label: value }));
const STATUS_OPTIONS = ["开放中", "已截止", "已投递"].map((value) => ({ value, label: value }));

/** 判断"这次识别到底有没有读出东西"时只看这些字段：job_type 与 status 恒有默认值。 */
const RECOGNIZED_CONTENT_FIELDS = [
  "title",
  "company",
  "location",
  "salary",
  "description",
  "requirements",
  "additional_info",
  "source_url",
  "posted_at",
] as const;

export default function JobFormModal({ open, initial, onClose, onSaved }: Props) {
  const [form] = Form.useForm<JobPayload>();
  const { message } = App.useApp();
  const [rawText, setRawText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [parseWarnings, setParseWarnings] = useState<string[]>([]);
  const [recognizedText, setRecognizedText] = useState("");
  const { images, reading, addFiles, removeImage, clear, onPaste } = useImageStaging();
  const parseRequestId = useRef(0);
  const submittingRef = useRef(false);
  const isEdit = !!initial;

  // 打开时回填编辑数据（或重置为默认值）
  useEffect(() => {
    parseRequestId.current += 1;
    setParsing(false);
    setSubmitting(false);
    submittingRef.current = false;
    if (!open) return;
    if (initial) {
      form.setFieldsValue(initial);
    } else {
      form.resetFields();
      setRawText("");
      setParseWarnings([]);
      setRecognizedText("");
      clear();
    }
  }, [open, initial, form, clear]);

  const parseImport = async () => {
    if (submittingRef.current) return;
    const value = rawText.trim();
    if (!value && images.length === 0) {
      message.warning("请先粘贴招聘信息或添加截图");
      return;
    }

    setParsing(true);
    const requestId = ++parseRequestId.current;
    try {
      const {
        warnings,
        recognition_source: recognitionSource,
        recognized_text: recognized,
        ...draft
      } = await parseJobText({
        text: value,
        images: images.map(({ name, mime_type, data }) => ({ name, mime_type, data })),
      });
      if (requestId !== parseRequestId.current) return;
      // 没有任何识别内容时（图片识别失败时的本地草稿就是这样）不要回填：无条件写入
      // 会把用户已经手填的标题、公司一起抹掉。判定只看**内容字段**——job_type 和
      // status 永远有默认值，把它们算进去会让这个判断恒为真。有内容时仍然全量覆盖，
      // 避免残留上一次识别的字段。
      if (RECOGNIZED_CONTENT_FIELDS.some((field) => draft[field].trim())) {
        form.setFieldsValue(draft);
      } else {
        message.warning("没有识别到内容，表单未改动");
      }
      setParseWarnings(warnings);
      setRecognizedText(recognized ?? "");
      message.success(
        `${recognitionSource === "ai" ? "已使用 AI" : "已使用本地规则"}识别并填入表单，请核对后再保存`,
      );
    } catch (err) {
      if (requestId !== parseRequestId.current) return;
      setParseWarnings([]);
      setRecognizedText("");
      message.error(err instanceof Error ? err.message : "识别招聘信息失败");
    } finally {
      if (requestId === parseRequestId.current) setParsing(false);
    }
  };

  const close = (force = false) => {
    if (submittingRef.current && !force) return;
    parseRequestId.current += 1;
    setParsing(false);
    onClose();
  };

  const submit = async () => {
    if (submittingRef.current || parsing) return;
    submittingRef.current = true;
    setSubmitting(true);
    let values: JobPayload;
    try {
      values = await form.validateFields();
    } catch {
      submittingRef.current = false;
      setSubmitting(false);
      return;
    }

    try {
      if (isEdit && initial) {
        await updateJob(initial.id, values);
        message.success("岗位已更新");
      } else {
        await createJob(values);
        message.success("岗位已添加");
      }
      onSaved();
      close(true);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={isEdit ? "编辑岗位" : "手动添加岗位"}
      open={open}
      onOk={() => void submit()}
      onCancel={() => close()}
      okText="保存"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: parsing || submitting }}
      cancelButtonProps={{ disabled: submitting }}
      maskClosable={!submitting}
      closable={!submitting}
      width={720}
      styles={{ body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto", paddingRight: 8 } }}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        disabled={submitting}
        initialValues={{ job_type: "校招", status: "开放中" }}
      >
        {!isEdit && (
          <>
            <Form.Item label="完整招聘信息">
              <Input.TextArea
                aria-label="完整招聘信息"
                value={rawText}
                disabled={parsing}
                onPaste={onPaste}
                onChange={(event) => {
                  setRawText(event.target.value);
                  setParseWarnings([]);
                  setRecognizedText("");
                }}
                placeholder="粘贴职位名称、地点、职位描述、职位要求等完整招聘信息，或按 Ctrl+V 直接贴招聘截图"
                style={{ height: 220, resize: "none" }}
              />
            </Form.Item>
            <ImageStagingField
              images={images}
              reading={reading}
              disabled={parsing}
              onAddFiles={(files) => void addFiles(files)}
              onRemove={removeImage}
            />
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: -12,
                marginBottom: 16,
              }}
            >
              <Button
                type="primary"
                icon={<FileSearchOutlined />}
                loading={parsing}
                onClick={() => void parseImport()}
              >
                识别并填充
              </Button>
            </div>
            <RecognizedTextField text={recognizedText} />
            {parseWarnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={parseWarnings.join("；")}
                style={{ marginBottom: 16 }}
              />
            )}
          </>
        )}
        <Form.Item
          name="title"
          label="职位名称"
          rules={[{ required: true, message: "请填写职位名称" }]}
        >
          <Input placeholder="如：后端开发工程师（校招）" />
        </Form.Item>
        <Form.Item name="company" label="公司名称">
          <Input placeholder="如：字节跳动" />
        </Form.Item>
        <Form.Item name="location" label="工作地点">
          <Input placeholder="如：北京" />
        </Form.Item>
        <Form.Item name="salary" label="薪资范围">
          <Input placeholder="如：25-40K·15薪" />
        </Form.Item>
        <Form.Item name="job_type" label="岗位类型">
          <Select options={JOB_TYPE_OPTIONS} />
        </Form.Item>
        <Form.Item name="status" label="状态">
          <Select options={STATUS_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="source_url"
          label="投递链接"
          rules={[{ type: "url", message: "请输入合法的 URL" }]}
        >
          <Input placeholder="招聘官网投递链接（选填）" />
        </Form.Item>
        <Form.Item name="posted_at" label="发布时间（选填）">
          <Input placeholder="如：2026-08-15" />
        </Form.Item>
        <Form.Item
          name="description"
          label="职位描述（JD）"
          rules={[{ required: true, message: "请填写职位描述" }]}
        >
          <Input.TextArea rows={7} placeholder="粘贴完整 JD，生成简历时 AI 会据此定制内容" />
        </Form.Item>
        <Form.Item name="requirements" label="任职要求（选填）">
          <Input.TextArea rows={3} placeholder="可单独填写任职要求，没有可留空" />
        </Form.Item>
        <Form.Item name="additional_info" label="其他招聘信息（选填）">
          <Input.TextArea
            rows={4}
            placeholder="如：公司与团队介绍、职位编号、福利待遇、工作安排、申请或面试流程"
          />
        </Form.Item>
        <Form.Item name="note" label="备注（选填）">
          <Input.TextArea
            rows={3}
            maxLength={2000}
            showCount
            placeholder="记录投递进展、内推联系人、面试安排等"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
