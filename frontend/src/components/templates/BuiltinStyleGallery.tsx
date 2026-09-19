/**
 * 内置样式缩略图墙：给每个内置样式渲染一张**真实效果**的缩略图，点开看大图。
 *
 * 之前这里只有一排文字标签（「经典」「现代」…），用户看不出它们长什么样，只能一个个
 * 点「复制改一份」才知道——等于把"选样式"变成盲选。缩略图用的是与正式预览同一条渲染
 * 接口（``/resume-templates/preview`` + 内置示例简历），所以看到的就是最终效果，
 * 不是另画一版示意图（示意图会随项目演进和真实模板脱节）。
 *
 * 两个成本上的取舍：
 * - **缩略图只是缩放的 iframe，不做截图**：截图要额外的浏览器依赖，而 iframe 本身就是
 *   真实渲染，且随窗口自适应。
 * - **一次拉齐、失败只留占位**：6 张缩略图的 HTML 都很小，逐个懒加载省不下多少；
 *   任何一张失败都只影响它自己，不打断了整个工作台。
 */
import { Modal, Skeleton, Typography } from "antd";
import { useEffect, useState } from "react";
import { previewResumeTemplate } from "../../api/resumes";
import A4PreviewFrame from "./A4PreviewFrame";

/** 与 A4 保持同比例，避免缩略图把简历"压扁"。 */
const THUMB_WIDTH = 150;
const A4_WIDTH_PX = 794;
const A4_HEIGHT_PX = 1123;
const THUMB_HEIGHT = Math.round((THUMB_WIDTH * A4_HEIGHT_PX) / A4_WIDTH_PX);
const THUMB_SCALE = THUMB_WIDTH / A4_WIDTH_PX;

export interface BuiltinStyleItem {
  name: string;
  label: string;
  description?: string;
}

interface Props {
  items: BuiltinStyleItem[];
}

export default function BuiltinStyleGallery({ items }: Props) {
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [opened, setOpened] = useState<BuiltinStyleItem | null>(null);

  // 依赖用名字拼出来的键：父组件每次渲染都会现造数组，直接依赖 items 会陷入死循环。
  const namesKey = items.map((item) => item.name).join("|");
  useEffect(() => {
    let cancelled = false;
    for (const item of items) {
      void previewResumeTemplate({ template_name: item.name, font_scale: "small", page_limit: 1 })
        .then((html) => {
          if (!cancelled) setPreviews((prev) => ({ ...prev, [item.name]: html }));
        })
        .catch(() => {
          // 单张失败只留占位；用户仍可点开看大图（那会再报一次错，信息更具体）。
        });
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namesKey]);

  const openedHtml = opened ? (previews[opened.name] ?? "") : "";

  return (
    <>
      <div className="builtin-style-gallery">
        {items.map((item) => {
          const html = previews[item.name];
          return (
            <button
              type="button"
              key={item.name}
              className="builtin-style-card"
              aria-label={`预览「${item.label}」样式效果`}
              onClick={() => setOpened(item)}
            >
              <span
                className="builtin-style-thumb"
                style={{ width: THUMB_WIDTH, height: THUMB_HEIGHT }}
              >
                {html ? (
                  <iframe
                    className="builtin-style-frame"
                    title={`${item.label} 样式缩略图`}
                    aria-hidden="true"
                    tabIndex={-1}
                    sandbox=""
                    scrolling="no"
                    srcDoc={html}
                    style={{
                      width: A4_WIDTH_PX,
                      height: A4_HEIGHT_PX,
                      transform: `scale(${THUMB_SCALE})`,
                      transformOrigin: "top left",
                    }}
                  />
                ) : (
                  <Skeleton.Node active style={{ width: THUMB_WIDTH, height: THUMB_HEIGHT }} />
                )}
              </span>
              <span className="builtin-style-name">{item.label}</span>
            </button>
          );
        })}
      </div>

      <Modal
        title={opened ? `内置样式预览 · ${opened.label}` : "内置样式预览"}
        open={!!opened}
        onCancel={() => setOpened(null)}
        footer={null}
        width="min(1000px, 96vw)"
        styles={{
          body: { maxHeight: "calc(100vh - 200px)", overflowY: "auto", overflowX: "hidden" },
        }}
        destroyOnHidden
      >
        {opened?.description && (
          <Typography.Paragraph type="secondary">{opened.description}</Typography.Paragraph>
        )}
        {openedHtml ? (
          <A4PreviewFrame html={openedHtml} title="内置样式大图预览" />
        ) : (
          <div className="template-preview-loading">
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        )}
      </Modal>
    </>
  );
}
