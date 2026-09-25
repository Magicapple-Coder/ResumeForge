/** 岗位新增/编辑弹窗：手动添加、识别导入、备注图片与来源标注。 */
import { DeleteOutlined, FileSearchOutlined, PictureOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  DatePicker,
  Form,
  Image,
  Input,
  Modal,
  Select,
  Space,
  Typography,
  Upload,
} from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useEffect, useRef, useState } from "react";
import { createJob, parseJobsMultiple, updateJob } from "../api/jobs";
import { attachmentInputs, useRecognitionFiles } from "../hooks/useRecognitionFiles";
import { readAsDataUrl } from "../utils/attachments";
import MultiJobDraftList from "./jobs/MultiJobDraftList";
import RecognitionFileField from "./RecognitionFileField";
import RecognitionOutcome from "./RecognitionOutcome";
import type {
  Job,
  JobPayload,
  JobRecognitionSource,
  ParsedJobDraft,
  RecognitionSource,
} from "../types";

/** 与后端 MAX_JOB_NOTE_IMAGES / 图片体积上限一致（服务端仍是权威校验）。 */
const MAX_NOTE_IMAGES = 2;
const MAX_NOTE_IMAGE_BYTES = 2 * 1024 * 1024;

type RecognitionInputKind = "text" | "image" | "document";

interface Props {
  open: boolean;
  /** 传入岗位表示编辑，null 表示新增 */
  initial: Job | null;
  /** 从备选岗位导入时预填的招聘原文（只用于新增）。 */
  presetRawText?: string;
  /**
   * 从备选岗位导入时预填的**结构化字段**（只用于新增）。
   *
   * 与 ``presetRawText`` 并存而不是取而代之：手工粘贴的候选只有原文，**采集来的候选恰恰相反**
   * ——它的内容在 ``description`` / ``requirements`` / ``location`` 这些列里，``raw_text`` 是空的。
   * 只填原文那一条路的话，从备选岗位导入一条采集来的岗位会打开一个**全空的表单**，
   * 用户看到的就是"导入进来什么都没有"。
   */
  presetJob?: Partial<JobPayload>;
  /** 从备选岗位导入时的来源标注；不填则按识别输入自动判定。 */
  presetSource?: JobRecognitionSource;
  onClose: () => void;
  /** 保存成功回调；新建时带上新岗位 id（备选岗位导入用它标记） 。 */
  onSaved: (jobId?: number) => void;
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

export default function JobFormModal({
  open,
  initial,
  presetRawText,
  presetJob,
  presetSource,
  onClose,
  onSaved,
}: Props) {
  const [form] = Form.useForm<JobPayload>();
  const { message } = App.useApp();
  const [rawText, setRawText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [parseWarnings, setParseWarnings] = useState<string[]>([]);
  const [recognizedText, setRecognizedText] = useState("");
  const [recognitionSource, setRecognitionSource] = useState<RecognitionSource | null>(null);
  // 这次识别是用什么输入的：保存时据此把「图片识别 / 文档识别 / 粘贴文本识别」写进溯源字段。
  const [inputKind, setInputKind] = useState<RecognitionInputKind>("text");
  const [noteImages, setNoteImages] = useState<string[]>([]);
  // 一次粘贴里识别出多份招聘信息时，先在这里存下来让用户确认，不直接覆盖表单。
  const [drafts, setDrafts] = useState<ParsedJobDraft[]>([]);
  const [draftsEngine, setDraftsEngine] = useState<RecognitionSource>("local");
  const [savingDrafts, setSavingDrafts] = useState(false);
  const { files, reading, addFiles, removeFile, clear, onPaste } = useRecognitionFiles();
  const parseRequestId = useRef(0);
  const submittingRef = useRef(false);
  const isEdit = !!initial;

  // 打开时回填编辑数据（或重置为默认值）
  useEffect(() => {
    parseRequestId.current += 1;
    setParsing(false);
    setSubmitting(false);
    submittingRef.current = false;
    // 每次打开都从干净状态开始：上次留下的多份草稿不该出现在这一次的弹窗里。
    setDrafts([]);
    setSavingDrafts(false);
    if (!open) return;
    if (initial) {
      form.setFieldsValue(initial);
      setNoteImages(initial.note_images ?? []);
    } else {
      form.resetFields();
      // 先把结构化字段铺上，再放原文（见 ``presetJob`` 的说明）。
      // **只写有值的那些**：把空串显式写进表单会让"这个字段是空的"与"这个字段没被填过"变得
      // 无法区分，而后面按字段判断"要不要再识别一次"的路径依赖这个区别。
      if (presetJob) {
        form.setFieldsValue(
          Object.fromEntries(
            Object.entries(presetJob).filter(([, value]) => value !== "" && value != null),
          ),
        );
      }
      setRawText(presetRawText ?? "");
      setParseWarnings([]);
      setRecognizedText("");
      setRecognitionSource(null);
      setInputKind("text");
      setNoteImages([]);
      clear();
    }
  }, [open, initial, presetRawText, presetJob, form, clear]);

  const addNoteImage = async (file: File) => {
    if (file.size > MAX_NOTE_IMAGE_BYTES) {
      message.error("单张图片不能超过 2 MB");
      return;
    }
    if (noteImages.length >= MAX_NOTE_IMAGES) {
      message.warning(`备注最多放 ${MAX_NOTE_IMAGES} 张图片`);
      return;
    }
    try {
      const dataUrl = await readAsDataUrl(file);
      setNoteImages((current) => [...current, dataUrl]);
    } catch {
      message.error("读取图片失败，请重试");
    }
  };

  // 至少两份才算"多份"：只有一份时走原来的回填表单流程，不打断用户。
  const multiMode = drafts.length > 1;

  const parseImport = async () => {
    if (submittingRef.current) return;
    const value = rawText.trim();
    if (!value && files.length === 0) {
      message.warning("请先粘贴招聘信息，或添加截图、上传文档");
      return;
    }

    setParsing(true);
    const requestId = ++parseRequestId.current;
    // 记录这次识别用的是什么输入，保存时写进「来源」字段。
    const hasImages = files.some((file) => file.kind === "image");
    const hasDocuments = files.some((file) => file.kind === "document");
    setInputKind(hasImages ? "image" : hasDocuments ? "document" : "text");
    try {
      const result = await parseJobsMultiple({
        text: value,
        images: attachmentInputs(files, "image"),
        documents: attachmentInputs(files, "document"),
      });
      if (requestId !== parseRequestId.current) return;
      if (result.items.length > 1) {
        // 多份：交给确认面板。这里**不**回填表单——回填只会显示最后一份，用户看不见
        // 其它几份，也看不出拆分对不对。
        setDrafts(result.items);
        setDraftsEngine(result.parse_engine);
        setParseWarnings(result.warnings ?? []);
        message.success(`识别出 ${result.items.length} 份招聘信息，请确认后保存`);
        return;
      }
      const {
        warnings,
        parse_engine: recognitionSource,
        recognized_text: recognized,
        ...draft
      } = result.items[0];
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
      // 提示条几秒后就没了，但"是 AI 还是本地规则"要一直留在表单上。
      setRecognitionSource(recognitionSource);
      message.success(
        `${recognitionSource === "ai" ? "已使用 AI" : "已使用本地规则"}识别并填入表单，请核对后再保存`,
      );
    } catch (err) {
      if (requestId !== parseRequestId.current) return;
      setParseWarnings([]);
      setRecognizedText("");
      setRecognitionSource(null);
      message.error(err instanceof Error ? err.message : "识别招聘信息失败");
    } finally {
      if (requestId === parseRequestId.current) setParsing(false);
    }
  };

  /** 多份草稿批量保存：逐条创建，成功的计数、失败的列出原因。 */
  const saveDrafts = async (chosen: ParsedJobDraft[]) => {
    if (submittingRef.current || chosen.length === 0) return;
    submittingRef.current = true;
    setSavingDrafts(true);
    const failures: string[] = [];
    let created = 0;
    for (const draft of chosen) {
      try {
        await createJob({
          title: draft.title.trim() || "待补充岗位",
          company: draft.company,
          location: draft.location,
          salary: draft.salary,
          job_type: draft.job_type,
          description: draft.description,
          requirements: draft.requirements,
          additional_info: draft.additional_info,
          source_url: draft.source_url,
          posted_at: draft.posted_at,
          status: draft.status,
          recognition_source: sourceForInputKind(inputKind),
        });
        created += 1;
      } catch (err) {
        failures.push(
          `${draft.title.trim() || "未命名岗位"}：${err instanceof Error ? err.message : "保存失败"}`,
        );
      }
    }
    submittingRef.current = false;
    setSavingDrafts(false);
    if (created > 0) {
      message.success(`已保存 ${created} 个岗位`);
      onSaved();
    }
    if (failures.length > 0) {
      // 部分失败时留在面板上，用户能看到哪几条没成功、原文也还在。
      message.error(`有 ${failures.length} 条未保存：${failures[0]}`);
      return;
    }
    close(true);
  };

  /** 从多份里挑一份填进表单继续编辑。 */
  const editSingleDraft = (draft: ParsedJobDraft) => {
    const { warnings, parse_engine, recognized_text, ...fields } = draft;
    void warnings;
    void recognized_text;
    form.setFieldsValue(fields);
    setDrafts([]);
    setRecognitionSource(parse_engine);
    setInputKind("text");
  };

  /** 输入方式 → 溯源标注（多份导入时也要按同一套规则标注）。 */
  const sourceForInputKind = (kind: RecognitionInputKind): JobRecognitionSource => {
    if (kind === "image") return "图片识别";
    if (kind === "document") return "文档识别";
    return "粘贴文本识别";
  };

  /** 按"这次识别用了什么输入"决定溯源标注；没做过识别就是手动填写。 */
  const recognitionSourceValue = (): JobRecognitionSource => {
    if (!recognitionSource) return "手动填写";
    return sourceForInputKind(inputKind);
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

    // 录入方式：从备选岗位导入时用指定值，识别过的按输入类型标注，没识别过就是手动填写；
    // 编辑时沿用原值。
    const recognitionSource: JobRecognitionSource = isEdit
      ? (initial?.recognition_source ?? "")
      : (presetSource ?? recognitionSourceValue());
    const payload: JobPayload = {
      ...values,
      note_images: noteImages,
      recognition_source: recognitionSource,
    };

    try {
      if (isEdit && initial) {
        await updateJob(initial.id, payload);
        message.success("岗位已更新");
        onSaved(initial.id);
      } else {
        const created = await createJob(payload);
        message.success("岗位已添加");
        onSaved(created.id);
      }
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
      title={multiMode ? "确认要导入的招聘信息" : isEdit ? "编辑岗位" : "手动添加岗位"}
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
      styles={{
        body: {
          maxHeight: "calc(100vh - 200px)",
          overflowY: "auto",
          overflowX: "hidden",
          paddingRight: 8,
        },
      }}
      // 多份确认面板自带操作按钮，保留默认的「保存/取消」会让用户以为要点弹窗底部。
      footer={multiMode ? null : undefined}
      destroyOnHidden
    >
      {multiMode ? (
        <MultiJobDraftList
          drafts={drafts}
          saving={savingDrafts}
          engineLabel={draftsEngine === "ai" ? "AI 拆分" : "按分隔符拆分"}
          onSave={(chosen) => void saveDrafts(chosen)}
          onEditSingle={editSingleDraft}
          onCancel={() => setDrafts([])}
        />
      ) : (
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
                    // 内容改了，上一次识别的来源与抄录都不再对应当前内容。
                    setRawText(event.target.value);
                    setParseWarnings([]);
                    setRecognizedText("");
                    setRecognitionSource(null);
                  }}
                  placeholder="粘贴职位名称、地点、职位描述、职位要求等完整招聘信息，或按 Ctrl+V 直接贴招聘截图（也可以上传 pdf/docx 招聘文档）"
                  style={{ height: 220, resize: "none" }}
                />
              </Form.Item>
              <RecognitionFileField
                files={files}
                reading={reading}
                disabled={parsing}
                onAddFiles={(incoming) => void addFiles(incoming)}
                onRemove={removeFile}
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
              <RecognitionOutcome source={recognitionSource} text={recognizedText} />
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
            <Input placeholder="如：市场营销专员（校招）" />
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
          <Form.Item
            name="posted_at"
            label="发布时间（选填）"
            // DatePicker 值走 Dayjs，但 JobPayload.posted_at 是字符串：getValueProps 把存的
            // 字符串转成 Dayjs 给控件，normalize 再把 Dayjs 转回 YYYY-MM-DD 存进表单。
            getValueProps={(value: string) => ({ value: value ? dayjs(value) : null })}
            normalize={(value: Dayjs | null) => (value ? value.format("YYYY-MM-DD") : "")}
          >
            <DatePicker style={{ width: "100%" }} />
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
              placeholder="记录投递进展、内推联系人、面试安排等；保存时会自动补一行「来源：…」"
            />
          </Form.Item>
          <Form.Item label={`备注图片（选填，最多 ${MAX_NOTE_IMAGES} 张）`}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <Space wrap>
                <Upload
                  accept="image/jpeg,image/png,image/webp"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    void addNoteImage(file as File);
                    return Upload.LIST_IGNORE;
                  }}
                >
                  <Button icon={<PictureOutlined />}>添加图片</Button>
                </Upload>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  招聘截图、内推码等，每张不超过 2 MB
                </Typography.Text>
              </Space>
              {noteImages.length > 0 && (
                <Space wrap>
                  {noteImages.map((source, index) => (
                    <div key={`${index}-${source.slice(-16)}`} className="job-note-image-item">
                      <Image src={source} alt={`备注图片 ${index + 1}`} width={96} />
                      <Button
                        type="text"
                        size="small"
                        danger
                        aria-label={`移除备注图片 ${index + 1}`}
                        icon={<DeleteOutlined />}
                        onClick={() =>
                          setNoteImages((current) => current.filter((_, i) => i !== index))
                        }
                      />
                    </div>
                  ))}
                </Space>
              )}
            </Space>
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
