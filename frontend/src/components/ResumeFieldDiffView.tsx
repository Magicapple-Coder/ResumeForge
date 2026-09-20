/** 版本对比：默认的人性化、字段级视图。
 *
 * 主视图由前端 ``utils/resumeFieldDiff`` 计算出的字段级差异驱动：只展示有变化的区块、
 * 字符串字段做词级高亮、列表字段做条目级 +/- 对照、照片显示为 [图片] 占位。后端下发的
 * 源码 diff 降级为底部的「查看原始差异」折叠兜底，保留既有能力。
 */
import { Card, Collapse, Empty, Tag, Typography } from "antd";
import type { CSSProperties } from "react";
import type { DiffToken } from "../types/resumeWriting";
import type {
  DiffViewData,
  ListItemView,
  ListSectionDiff,
  ModifiedItemDiff,
  SectionDiff,
  StringSectionDiff,
  SubFieldDiff,
} from "../types/resumeFieldDiff";
import ResumeDiffView from "./ResumeDiffView";

const TOKEN_STYLE: Record<string, CSSProperties> = {
  added: { background: "#d9f7be", color: "#135200" },
  removed: { background: "#ffccc7", color: "#a8071a", textDecoration: "line-through" },
  unchanged: {},
};

function TokenText({ tokens }: { tokens: DiffToken[] }) {
  return (
    <>
      {tokens.map((token, index) => (
        <span key={index} style={TOKEN_STYLE[token.type]}>
          {token.text}{" "}
        </span>
      ))}
    </>
  );
}

/** 旧→新两列；窄 Modal 下 flex-wrap 自动上下堆叠。 */
function TwoColumn({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>{children}</div>;
}

function Column({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{ flex: "1 1 240px", minWidth: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}
    >
      {children}
    </div>
  );
}

function StringSectionCard({ section }: { section: StringSectionDiff }) {
  const tag = !section.oldText
    ? { color: "green", text: "新增" }
    : !section.newText
      ? { color: "red", text: "删除" }
      : { color: "blue", text: "修改" };
  return (
    <Card
      size="small"
      title={
        <span>
          <Typography.Text strong>{section.label}</Typography.Text>{" "}
          <Tag color={tag.color}>{tag.text}</Tag>
        </span>
      }
    >
      <TwoColumn>
        <Column>
          <Typography.Text type="secondary">原</Typography.Text>
          <div>
            {section.oldText ? (
              <TokenText tokens={section.oldTokens} />
            ) : (
              <Typography.Text type="secondary">（空）</Typography.Text>
            )}
          </div>
        </Column>
        <Column>
          <Typography.Text type="secondary">新</Typography.Text>
          <div>
            {section.newText ? (
              <TokenText tokens={section.newTokens} />
            ) : (
              <Typography.Text type="secondary">（空）</Typography.Text>
            )}
          </div>
        </Column>
      </TwoColumn>
    </Card>
  );
}

/** 新增/删除条目：红 − / 绿 + 边框块。 */
function ItemBlock({ item, sign }: { item: ListItemView; sign: "added" | "removed" }) {
  const color = sign === "added" ? "#52c41a" : "#ff4d4f";
  const bg = sign === "added" ? "#f6ffed" : "#fff1f0";
  return (
    <div
      data-sign={sign}
      style={{ border: `1px solid ${color}`, borderRadius: 6, padding: "8px 12px", background: bg }}
    >
      <div style={{ fontWeight: 600, color }}>
        {sign === "added" ? "+ " : "− "}
        {item.title || "（条目）"}
      </div>
      {item.lines.map((line, index) => (
        <div key={index} style={{ fontSize: 13 }}>
          {line}
        </div>
      ))}
    </div>
  );
}

function SubFieldRow({ sub }: { sub: SubFieldDiff }) {
  if (sub.kind === "string") {
    return (
      <div>
        <Typography.Text type="secondary">{sub.label}：</Typography.Text>
        <TwoColumn>
          <Column>
            {sub.oldText ? (
              <TokenText tokens={sub.oldTokens} />
            ) : (
              <Typography.Text type="secondary">（空）</Typography.Text>
            )}
          </Column>
          <Column>
            {sub.newText ? (
              <TokenText tokens={sub.newTokens} />
            ) : (
              <Typography.Text type="secondary">（空）</Typography.Text>
            )}
          </Column>
        </TwoColumn>
      </div>
    );
  }
  return (
    <div>
      <Typography.Text type="secondary">{sub.label}：</Typography.Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {sub.removedLines.map((line, index) => (
          <div key={`r-${index}`} style={{ color: "#a8071a" }}>
            − {line}
          </div>
        ))}
        {sub.addedLines.map((line, index) => (
          <div key={`a-${index}`} style={{ color: "#135200" }}>
            + {line}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 修改条目：拆成子字段逐条对照。 */
function ModifiedItemBlock({ item }: { item: ModifiedItemDiff }) {
  return (
    <div
      data-sign="modified"
      style={{
        border: "1px solid #91caff",
        borderRadius: 6,
        padding: "8px 12px",
        background: "#e6f4ff",
      }}
    >
      <Tag color="blue">修改</Tag>
      <Typography.Text strong>{item.key || "（条目）"}</Typography.Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        {item.subfields.map((sub, index) => (
          <SubFieldRow key={index} sub={sub} />
        ))}
      </div>
    </div>
  );
}

function ListSectionCard({ section }: { section: ListSectionDiff }) {
  return (
    <Card size="small" title={<Typography.Text strong>{section.label}</Typography.Text>}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {section.removed.map((item, index) => (
          <ItemBlock key={`r-${index}`} item={item} sign="removed" />
        ))}
        {section.added.map((item, index) => (
          <ItemBlock key={`a-${index}`} item={item} sign="added" />
        ))}
        {section.modified.map((item, index) => (
          <ModifiedItemBlock key={`m-${index}`} item={item} />
        ))}
        {section.unchangedCount > 0 && (
          <Typography.Text type="secondary">{section.unchangedCount} 个条目未变化</Typography.Text>
        )}
      </div>
    </Card>
  );
}

function SectionCard({ section }: { section: SectionDiff }) {
  return section.type === "string" ? (
    <StringSectionCard section={section} />
  ) : (
    <ListSectionCard section={section} />
  );
}

export default function ResumeFieldDiffView({ data }: { data: DiffViewData }) {
  const { field, raw } = data;
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Typography.Text>对比：</Typography.Text>
        <Typography.Text strong>{field.baseTitle}</Typography.Text>
        <Typography.Text type="secondary"> → </Typography.Text>
        <Typography.Text strong>{field.againstTitle}</Typography.Text>
        <span style={{ marginLeft: 12 }}>
          <Tag color="green">新增 {raw.stats.added}</Tag>
          <Tag color="red">删除 {raw.stats.removed}</Tag>
          <Tag>未变 {raw.stats.unchanged}</Tag>
        </span>
      </div>

      {field.changed.length === 0 ? (
        <Empty description="两份简历内容完全一致，没有差异" />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {field.changed.map((section) => (
            <SectionCard key={section.key} section={section} />
          ))}
        </div>
      )}

      {field.unchangedLabels.length > 0 && (
        <Collapse
          style={{ marginTop: 12 }}
          items={[
            {
              key: "unchanged",
              label: `${field.unchangedLabels.length} 个字段未变化`,
              children: (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {field.unchangedLabels.map((label) => (
                    <Tag key={label}>{label}</Tag>
                  ))}
                </div>
              ),
            },
          ]}
        />
      )}

      <Collapse
        style={{ marginTop: 12 }}
        items={[
          {
            key: "raw",
            label: "查看原始差异",
            children: <ResumeDiffView diff={raw} />,
          },
        ]}
      />
    </div>
  );
}
