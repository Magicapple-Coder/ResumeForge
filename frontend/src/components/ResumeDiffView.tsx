/** 版本对比视图：三态高亮（added / removed / unchanged）。
 *
 * 只渲染后端 ``services/resume_diff.py`` 下发的三态结构，不重算 diff——共享知识第 11 条。
 */
import { Tag, Typography } from "antd";
import type { CSSProperties } from "react";
import type { DiffLine, DiffLineType, ResumeDiff } from "../types/resumeWriting";

const LINE_STYLE: Record<DiffLineType, CSSProperties> = {
  added: { background: "#f6ffed", color: "#135200" },
  removed: { background: "#fff1f0", color: "#a8071a", textDecoration: "line-through" },
  unchanged: { background: "transparent" },
};

const TOKEN_STYLE: Record<DiffLineType, CSSProperties> = {
  added: { background: "#d9f7be", color: "#135200" },
  removed: { background: "#ffccc7", color: "#a8071a", textDecoration: "line-through" },
  unchanged: {},
};

const PREFIX: Record<DiffLineType, string> = {
  added: "+ ",
  removed: "− ",
  unchanged: "  ",
};

export default function ResumeDiffView({ diff }: { diff: ResumeDiff }) {
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Typography.Text>对比：</Typography.Text>
        <Typography.Text strong>{diff.base_title}</Typography.Text>
        <Typography.Text type="secondary"> → </Typography.Text>
        <Typography.Text strong>{diff.against_title}</Typography.Text>
        <span style={{ marginLeft: 12 }}>
          <Tag color="green">新增 {diff.stats.added}</Tag>
          <Tag color="red">删除 {diff.stats.removed}</Tag>
          <Tag>未变 {diff.stats.unchanged}</Tag>
        </span>
      </div>
      <div style={{ fontFamily: "monospace", fontSize: 13, lineHeight: 1.7 }}>
        {diff.lines.map((line, index) => (
          <DiffLineRow key={index} line={line} />
        ))}
      </div>
    </div>
  );
}

function DiffLineRow({ line }: { line: DiffLine }) {
  if (line.tokens.length === 0) {
    return (
      <div data-line-type={line.type} style={LINE_STYLE[line.type]}>
        {PREFIX[line.type]}
        {line.text || " "}
      </div>
    );
  }
  return (
    <div data-line-type={line.type} style={LINE_STYLE[line.type]}>
      {PREFIX[line.type]}
      {line.tokens.map((token, index) => (
        <span key={index} style={TOKEN_STYLE[token.type]}>
          {token.text}{" "}
        </span>
      ))}
    </div>
  );
}
