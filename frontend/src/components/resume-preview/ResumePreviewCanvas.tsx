import { Alert } from "antd";
import type { RefObject } from "react";
import { A4_WIDTH_PX, APPROXIMATE_PAGINATION_NOTE, type InteractionMode } from "./config";

interface Props {
  warnings: string[];
  overflow: boolean;
  pagesNeeded: number;
  pageCount: number;
  overflowAmountText: string;
  interactionMode: InteractionMode;
  isPanning: boolean;
  viewportHeight: number;
  scaledWidth: number;
  scaledHeight: number;
  contentTotalWidth: number;
  contentTotalHeight: number;
  scale: number;
  separatorCount: number;
  totalVisualPages: number;
  html: string;
  containerRef: RefObject<HTMLDivElement>;
  iframeRef: RefObject<HTMLIFrameElement>;
  onIframeLoad: () => void;
}

export default function ResumePreviewCanvas({
  warnings,
  overflow,
  pagesNeeded,
  pageCount,
  overflowAmountText,
  interactionMode,
  isPanning,
  viewportHeight,
  scaledWidth,
  scaledHeight,
  contentTotalWidth,
  contentTotalHeight,
  scale,
  separatorCount,
  totalVisualPages,
  html,
  containerRef,
  iframeRef,
  onIframeLoad,
}: Props) {
  return (
    <>
      {warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="发现以下内容需要人工核对（可能存在 AI 虚构）"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          }
        />
      )}
      {overflow && (
        <Alert
          type="warning"
          showIcon
          className="resume-preview-overflow"
          message={`按当前设置约需 ${pagesNeeded} 页（上限 ${pageCount} 页）；字号已降到最小，仍然放不下。`}
          description={
            <>
              {overflowAmountText} {APPROXIMATE_PAGINATION_NOTE}
            </>
          }
        />
      )}
      <div
        ref={containerRef}
        className={`resume-preview-viewport${isPanning ? " is-panning" : ""}${interactionMode === "edit" ? " is-editing" : ""}`}
        style={{ height: viewportHeight }}
      >
        <div
          className="resume-preview-scale-box"
          style={{ width: scaledWidth, height: scaledHeight, position: "relative" }}
        >
          <iframe
            ref={iframeRef}
            title="简历预览"
            className="resume-iframe"
            width={contentTotalWidth}
            height={contentTotalHeight}
            srcDoc={html}
            sandbox="allow-same-origin"
            scrolling="no"
            onLoad={onIframeLoad}
            data-interaction-mode={interactionMode}
            style={{
              width: contentTotalWidth,
              height: contentTotalHeight,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
          {Array.from({ length: separatorCount }, (_, index) => {
            const pageNumber = index + 2;
            return (
              <div
                key={pageNumber}
                className="resume-preview-page-separator"
                style={{ left: (index + 1) * A4_WIDTH_PX * scale }}
              >
                <span className="resume-preview-page-separator-line" />
                <span className="resume-preview-page-separator-label">
                  第 {pageNumber} 页 / 共 {totalVisualPages} 页（近似）
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
