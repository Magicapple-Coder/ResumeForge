/** 简历写作增强面板：STAR 改写 / 话术生成 / 风格润色 / 中英互译。
 *
 * 自包含：一段文本进、一段文本出。结果既可复制，也可一键回填——由父组件决定
 * 「回填到哪个字段」，这里只负责把结果交回去。
 */
import { App, Button, Checkbox, Input, Radio, Segmented, Space, Spin, Typography } from "antd";
import { useMemo, useState } from "react";
import {
  generatePhrases,
  polishResumeText,
  rewriteStar,
  translateResumeText,
} from "../api/resumeWriting";
import type {
  PhraseMode,
  PhrasesResult,
  PolishStyle,
  TranslateDirection,
} from "../types/resumeWriting";

type Operation = "star" | "phrases" | "polish" | "translate";

const OPERATIONS: { value: Operation; label: string }[] = [
  { value: "star", label: "STAR 改写" },
  { value: "phrases", label: "话术生成" },
  { value: "polish", label: "风格润色" },
  { value: "translate", label: "中英互译" },
];

const POLISH_STYLES: { value: PolishStyle; label: string }[] = [
  { value: "big_tech", label: "大厂风" },
  { value: "concise_tech", label: "简洁技术风" },
  { value: "campus", label: "应届生风" },
];

const PHRASE_MODES: { value: PhraseMode; label: string }[] = [
  { value: "star", label: "STAR 版" },
  { value: "resume", label: "简历版" },
  { value: "interview", label: "面试口述版" },
];

interface Props {
  resumeId: number;
  initialText?: string;
  /** 把某条结果回填到父组件选定的字段。 */
  onApply: (text: string) => void;
}

export default function ResumeWritingPanel({ resumeId, initialText = "", onApply }: Props) {
  const { message } = App.useApp();
  const [text, setText] = useState(initialText);
  const [operation, setOperation] = useState<Operation>("star");
  const [polishStyle, setPolishStyle] = useState<PolishStyle>("concise_tech");
  const [direction, setDirection] = useState<TranslateDirection>("zh2en");
  const [modes, setModes] = useState<PhraseMode[]>(["star", "resume", "interview"]);
  const [loading, setLoading] = useState(false);
  const [singleResult, setSingleResult] = useState("");
  const [phrasesResult, setPhrasesResult] = useState<PhrasesResult | null>(null);

  const canRun = useMemo(() => text.trim().length > 0, [text]);

  const run = async () => {
    if (!canRun || loading) return;
    setLoading(true);
    setSingleResult("");
    setPhrasesResult(null);
    try {
      if (operation === "star") {
        setSingleResult((await rewriteStar(resumeId, text.trim())).result);
      } else if (operation === "phrases") {
        setPhrasesResult(await generatePhrases(resumeId, text.trim(), modes));
      } else if (operation === "polish") {
        setSingleResult((await polishResumeText(resumeId, text.trim(), polishStyle)).result);
      } else {
        setSingleResult((await translateResumeText(resumeId, text.trim(), direction)).result);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "生成失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const apply = (result: string) => {
    if (!result) return;
    onApply(result);
    message.success("已回填");
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Input.TextArea
        rows={4}
        value={text}
        placeholder="粘贴或输入一段简历描述"
        onChange={(event) => setText(event.target.value)}
        aria-label="写作输入文本"
      />

      <Segmented
        block
        options={OPERATIONS}
        value={operation}
        onChange={(value) => setOperation(value as Operation)}
      />

      {operation === "polish" && (
        <Radio.Group
          value={polishStyle}
          onChange={(event) => setPolishStyle(event.target.value)}
          aria-label="润色风格"
        >
          {POLISH_STYLES.map((item) => (
            <Radio.Button key={item.value} value={item.value}>
              {item.label}
            </Radio.Button>
          ))}
        </Radio.Group>
      )}

      {operation === "translate" && (
        <Radio.Group
          value={direction}
          onChange={(event) => setDirection(event.target.value)}
          aria-label="翻译方向"
        >
          <Radio.Button value="zh2en">中译英</Radio.Button>
          <Radio.Button value="en2zh">英译中</Radio.Button>
        </Radio.Group>
      )}

      {operation === "phrases" && (
        <Checkbox.Group
          options={PHRASE_MODES}
          value={modes}
          onChange={(value) => setModes(value as PhraseMode[])}
          aria-label="话术版式"
        />
      )}

      <Button type="primary" loading={loading} disabled={!canRun} onClick={() => void run()}>
        生成
      </Button>

      {loading && <Spin />}

      {!loading && singleResult && (
        <ResultBlock label="结果" onApply={() => apply(singleResult)}>
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
            {singleResult}
          </Typography.Paragraph>
        </ResultBlock>
      )}

      {!loading && phrasesResult && (
        <Space direction="vertical" style={{ width: "100%" }} size="small">
          {(
            [
              ["star", "STAR 版"],
              ["resume", "简历版"],
              ["interview", "面试口述版"],
            ] as const
          )
            .filter(([key]) => phrasesResult[key])
            .map(([key, label]) => (
              <ResultBlock key={key} label={label} onApply={() => apply(phrasesResult[key])}>
                <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
                  {phrasesResult[key]}
                </Typography.Paragraph>
              </ResultBlock>
            ))}
        </Space>
      )}
    </Space>
  );
}

function ResultBlock({
  label,
  onApply,
  children,
}: {
  label: string;
  onApply: () => void;
  children: React.ReactNode;
}) {
  return (
    <div style={{ border: "1px solid #f0f0f0", borderRadius: 8, padding: 12 }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Text strong>{label}</Typography.Text>
        <Button size="small" type="link" onClick={onApply}>
          回填
        </Button>
      </Space>
      {children}
    </div>
  );
}
