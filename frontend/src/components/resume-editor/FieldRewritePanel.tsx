/**
 * 「让 AI 按我的要求改这一栏」：用户在预览里点中某一栏后，用一句话让 AI 重写它。
 *
 * 两种粒度，都可以在这里选：
 * - **这一条**：只改点中的那一条要点（`projects.0.description.1`）；
 * - **整段**：改这一整段内容（`projects.0.description`，该项目的全部要点）。
 *   用户说的"重新生成实习工作中的工作内容""重写校园经历的经历描述"就是后者——
 *   只给单条用的话，四条要点要重复四次同样的要求。
 *
 * 三个刻意的行为：
 * 1. **只改这一栏**：模型拿到的上下文里有"这是哪一栏、属于哪条经历"，所以能听懂
 *    "这条要点补上数字"这类针对具体位置的指令。
 * 2. **不自动写入**：结果先并排显示，用户点「填入」才进表单，再点弹窗的保存才落库。
 *    AI 静默改用户已经导出过的内容是最不能接受的一种"自动化"。
 * 3. **保留原值可回退**：填入之后如果后悔，点「还原」拿回原来的文本。
 */
import { ThunderboltOutlined } from "@ant-design/icons";
import { App, Button, Input, Radio, Space, Typography } from "antd";
import { useState } from "react";
import { rewriteResumeField } from "../../api/resumeWriting";
import type { ResumeContent } from "../../types";
import {
  describeResumeFieldPath,
  isLineListPath,
  readResumeFieldByPath,
  readResumeLinesByPath,
  toWholeSegmentPath,
  writeResumeValueByPath,
} from "../../utils/resumeFieldPath";

interface Props {
  resumeId: number;
  content: ResumeContent;
  /** 用户点中的那一栏（`data-resume-path` 写法）。 */
  path: string;
  /** 用改写后的内容替换整份内容（父组件持有表单）。 */
  onChange: (content: ResumeContent) => void;
}

/** 「当前内容」收起时最多显示几行（超出折叠，不用滚动条）。 */
const VISIBLE_ORIGINAL_LINES = 4;
/**
 * 判定"要不要折叠"的字符数：个人总结这类**单条长文本**按长度判，不按条数。
 *
 * 取 110 是照面板里的排版估的（12px 字号、约 560px 宽 → 一行约 46 个汉字），
 * 也就是"超过约两行半就折叠"。用户反馈的那份简历个人总结正是这个量级：
 * 在面板里排到四行、原来带一根滚动条，现在折成四行 + 「展开全文」。
 */
const COLLAPSE_CHAR_THRESHOLD = 110;

const EXAMPLES = [
  "更短一点，只留最关键的一条",
  "补上具体数字，别写得太空",
  "突出增长相关的经验",
  "换成更专业的说法，去掉形容词",
];

export default function FieldRewritePanel({ resumeId, content, path, onChange }: Props) {
  const { message } = App.useApp();
  const [instruction, setInstruction] = useState("");
  const [running, setRunning] = useState(false);
  const [suggestion, setSuggestion] = useState<string[]>([]);
  /** 点中单条要点时，可以把它扩成"整段"：`…description.1` → `…description`。 */
  const [wholeSegment, setWholeSegment] = useState(false);
  const [applied, setApplied] = useState<string[] | null>(null);
  // 「当前内容」默认收起：内容长时靠"展开全文"看全，而不是给一个滚动条。
  const [showAllOriginal, setShowAllOriginal] = useState(false);

  const segmentPath = toWholeSegmentPath(path);
  const canChooseGranularity = segmentPath !== path;
  const targetPath = wholeSegment && canChooseGranularity ? segmentPath : path;
  const wholeSegmentTarget = isLineListPath(targetPath);

  const label = describeResumeFieldPath(targetPath, content);
  const original =
    applied ??
    (wholeSegmentTarget
      ? readResumeLinesByPath(content, targetPath)
      : [readResumeFieldByPath(content, targetPath)]);

  // 空行不算内容，但保留在 original 里会给"共 N 条"的计数添乱。
  const originalLines = original.filter(Boolean);
  // 折叠按**字符长度**判：个人总结是一条几百字的长文本（条数只有 1），
  // 而项目要点是若干短条——只看条数会漏掉前者。
  const collapsible =
    originalLines.length > VISIBLE_ORIGINAL_LINES ||
    originalLines.join("").length > COLLAPSE_CHAR_THRESHOLD;
  const collapsed = collapsible && !showAllOriginal;

  const run = async () => {
    if (!instruction.trim()) {
      message.warning("先写一句你想怎么改");
      return;
    }
    setRunning(true);
    try {
      const response = await rewriteResumeField(resumeId, targetPath, instruction.trim());
      const lines = response.lines ?? [];
      setSuggestion(lines.length > 0 ? lines : [response.result]);
      setApplied(null);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "改写这一栏失败");
    } finally {
      setRunning(false);
    }
  };

  const apply = () => {
    if (suggestion.length === 0) return;
    // 记下应用前的值，供「还原」使用——表单里此时已经是新值了。
    setApplied(original);
    onChange(
      writeResumeValueByPath(content, targetPath, wholeSegmentTarget ? suggestion : suggestion[0]),
    );
    setSuggestion([]);
  };

  const revert = () => {
    if (applied === null) return;
    onChange(
      writeResumeValueByPath(
        content,
        targetPath,
        wholeSegmentTarget ? applied : (applied[0] ?? ""),
      ),
    );
    setApplied(null);
    message.success("已还原为改写前的文本");
  };

  return (
    <div className="resume-field-rewrite">
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text strong>
          <ThunderboltOutlined /> 让 AI 按我的要求改「{label}」
        </Typography.Text>
        {canChooseGranularity ? (
          <Radio.Group
            size="small"
            value={wholeSegment ? "whole" : "single"}
            onChange={(event) => {
              setWholeSegment(event.target.value === "whole");
              setSuggestion([]);
              setApplied(null);
            }}
          >
            <Radio.Button value="single">只改这一条</Radio.Button>
            <Radio.Button value="whole">
              重写整段（全部 {readResumeLinesByPath(content, segmentPath).length} 条）
            </Radio.Button>
          </Radio.Group>
        ) : null}
        <div className={`resume-field-rewrite-original${collapsed ? " is-collapsed" : ""}`}>
          <Typography.Text type="secondary">当前内容：</Typography.Text>
          {originalLines.length > 0 ? (
            // 整块文本 + `pre-line`：多条要点各占一行，长段落正常折行；
            // 折叠时用 `-webkit-line-clamp` 按**视觉行**截断（子块做不到这一点）。
            <Typography.Paragraph className="resume-field-rewrite-text">
              {originalLines.join("\n")}
            </Typography.Paragraph>
          ) : (
            <Typography.Text type="secondary">（这一栏现在是空的）</Typography.Text>
          )}
          {collapsible ? (
            <Typography.Link
              className="resume-field-rewrite-more"
              onClick={() => setShowAllOriginal((current) => !current)}
            >
              {collapsed ? `展开全文（共 ${originalLines.length} 条）` : "收起"}
            </Typography.Link>
          ) : null}
        </div>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onPressEnter={() => void run()}
            placeholder={
              wholeSegmentTarget
                ? "例如：每条都补上量化结果，控制在三条"
                : "例如：再短一点，突出数据结果"
            }
            maxLength={500}
            aria-label="对这一栏的改写要求"
          />
          <Button type="primary" loading={running} onClick={() => void run()}>
            生成
          </Button>
        </Space.Compact>
        <Space size={6} wrap>
          {EXAMPLES.map((example) => (
            <Button
              key={example}
              size="small"
              type="link"
              style={{ padding: 0 }}
              onClick={() => setInstruction(example)}
            >
              {example}
            </Button>
          ))}
        </Space>
        {suggestion.length > 0 ? (
          <div className="resume-field-rewrite-result">
            <Typography.Text type="secondary">
              改写结果（还没生效，共 {suggestion.length} 条）
            </Typography.Text>
            <div style={{ margin: "6px 0" }}>
              {suggestion.map((line, index) => (
                <Typography.Text key={index} className="resume-field-rewrite-line">
                  {line}
                </Typography.Text>
              ))}
            </div>
            <Space size={8}>
              <Button type="primary" size="small" onClick={apply}>
                {wholeSegmentTarget ? "填入整段" : "填入这一条"}
              </Button>
              <Button size="small" onClick={() => setSuggestion([])}>
                丢弃
              </Button>
            </Space>
          </div>
        ) : null}
        {applied !== null ? (
          <Space size={8}>
            <Typography.Text type="success">已填入表单，保存后才会更新简历。</Typography.Text>
            <Button size="small" type="link" style={{ padding: 0 }} onClick={revert}>
              还原
            </Button>
          </Space>
        ) : null}
      </Space>
    </div>
  );
}
