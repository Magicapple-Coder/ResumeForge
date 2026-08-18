/** 简历预览：固定为一张 A4 纸，再按弹窗可用空间等比缩放。 */
import { ReloadOutlined, ZoomInOutlined, ZoomOutOutlined } from "@ant-design/icons";
import { Alert, Button, Space, Tooltip, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  html: string;
  warnings: string[];
  /** 仅作为首次布局尚未测量时的占位高度，实际画布始终是 A4。 */
  height?: number;
}

const A4_WIDTH_PX = 794;
const A4_HEIGHT_PX = 1123;
const PREVIEW_BOTTOM_RESERVE = 150;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3.5;

interface AvailableSpace {
  width: number;
  height: number;
}

interface PanStart {
  clientX: number;
  clientY: number;
  scrollLeft: number;
  scrollTop: number;
}

export default function ResumePreview({ html, warnings, height = A4_HEIGHT_PX }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const panStartRef = useRef<PanStart | null>(null);
  const [availableSpace, setAvailableSpace] = useState<AvailableSpace>({ width: 0, height });
  const [zoom, setZoom] = useState(1);
  const [isPanning, setIsPanning] = useState(false);

  const updateAvailableSpace = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const top = container.getBoundingClientRect().top;
    setAvailableSpace({
      width: container.clientWidth,
      height: Math.max(240, window.innerHeight - top - PREVIEW_BOTTOM_RESERVE),
    });
  }, []);

  const fitFrameContent = useCallback(() => {
    const document = iframeRef.current?.contentDocument;
    const body = document?.body;
    const root = document?.documentElement;
    if (!document || !body || !root) return;

    // 预览不允许 iframe 自己产生滚动条，滚动统一由外层 viewport 承担。
    if (!document.getElementById("resume-preview-style")) {
      const style = document.createElement("style");
      style.id = "resume-preview-style";
      style.textContent = "html,body{overflow:hidden!important}";
      document.head.appendChild(style);
    }

    // 长内容也压缩到单页 A4 内，避免用户必须在 iframe 中滚动查看。
    body.style.transform = "none";
    body.style.transformOrigin = "top left";
    body.style.width = "";
    body.style.height = "";
    const contentWidth = Math.max(body.scrollWidth, root.scrollWidth, A4_WIDTH_PX);
    const contentHeight = Math.max(body.scrollHeight, root.scrollHeight, A4_HEIGHT_PX);
    const contentScale = Math.min(1, A4_WIDTH_PX / contentWidth, A4_HEIGHT_PX / contentHeight);
    if (contentScale < 1) {
      body.style.width = `${A4_WIDTH_PX / contentScale}px`;
      body.style.height = `${A4_HEIGHT_PX / contentScale}px`;
      body.style.transform = `scale(${contentScale})`;
    }
    root.style.overflow = "hidden";
  }, []);

  useEffect(() => {
    setZoom(1);
    updateAvailableSpace();
    const container = containerRef.current;
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateAvailableSpace);
    if (container) observer?.observe(container);
    window.addEventListener("resize", updateAvailableSpace);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateAvailableSpace);
    };
  }, [html, updateAvailableSpace]);

  const viewportWidth = availableSpace.width || A4_WIDTH_PX;
  const viewportHeight = availableSpace.height || height;
  const fitScale = Math.min(1, viewportWidth / A4_WIDTH_PX, viewportHeight / A4_HEIGHT_PX);
  const scale = Math.min(2.5, fitScale * zoom);
  const viewportHeightForPage = A4_HEIGHT_PX * fitScale;
  const scaledWidth = A4_WIDTH_PX * scale;
  const scaledHeight = A4_HEIGHT_PX * scale;

  const handleWheel = useCallback((event: globalThis.WheelEvent) => {
    // iframe 会独立接收滚轮；在外层用非被动监听确保每次都能缩放预览。
    if (event.deltaY === 0) return;
    event.preventDefault();
    const direction = event.deltaY > 0 ? -1 : 1;
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current + direction * 0.1)));
  }, []);

  useEffect(() => {
    const viewport = containerRef.current;
    if (!viewport) return;

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (event.button !== 0) return;
      event.preventDefault();
      panStartRef.current = {
        clientX: event.clientX,
        clientY: event.clientY,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      viewport.setPointerCapture?.(event.pointerId);
      setIsPanning(true);
    };

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const start = panStartRef.current;
      if (!start) return;
      event.preventDefault();
      viewport.scrollLeft = start.scrollLeft - (event.clientX - start.clientX);
      viewport.scrollTop = start.scrollTop - (event.clientY - start.clientY);
    };

    const stopPanning = (event: globalThis.PointerEvent) => {
      if (viewport.hasPointerCapture?.(event.pointerId)) {
        viewport.releasePointerCapture?.(event.pointerId);
      }
      panStartRef.current = null;
      setIsPanning(false);
    };

    // passive=false is required because the browser otherwise treats wheel as scroll-only.
    viewport.addEventListener("wheel", handleWheel, { passive: false });
    viewport.addEventListener("pointerdown", handlePointerDown);
    viewport.addEventListener("pointermove", handlePointerMove);
    viewport.addEventListener("pointerup", stopPanning);
    viewport.addEventListener("pointercancel", stopPanning);
    viewport.addEventListener("lostpointercapture", stopPanning);
    return () => {
      viewport.removeEventListener("wheel", handleWheel);
      viewport.removeEventListener("pointerdown", handlePointerDown);
      viewport.removeEventListener("pointermove", handlePointerMove);
      viewport.removeEventListener("pointerup", stopPanning);
      viewport.removeEventListener("pointercancel", stopPanning);
      viewport.removeEventListener("lostpointercapture", stopPanning);
    };
  }, [handleWheel]);

  const adjustZoom = (delta: number) => {
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current + delta)));
  };

  return (
    <div>
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
      <div className="resume-preview-toolbar">
        <Space size={4}>
          <Tooltip title="缩小预览">
            <Button
              type="text"
              size="small"
              aria-label="缩小预览"
              icon={<ZoomOutOutlined />}
              onClick={() => adjustZoom(-0.1)}
            />
          </Tooltip>
          <Typography.Text type="secondary" className="resume-preview-zoom-label">
            {Math.round(zoom * 100)}%
          </Typography.Text>
          <Tooltip title="放大预览">
            <Button
              type="text"
              size="small"
              aria-label="放大预览"
              icon={<ZoomInOutlined />}
              onClick={() => adjustZoom(0.1)}
            />
          </Tooltip>
          <Tooltip title="重置预览大小">
            <Button
              type="text"
              size="small"
              aria-label="重置预览大小"
              icon={<ReloadOutlined />}
              onClick={() => setZoom(1)}
            />
          </Tooltip>
        </Space>
      </div>
      <div
        ref={containerRef}
        className={`resume-preview-viewport${isPanning ? " is-panning" : ""}`}
        style={{ height: viewportHeightForPage }}
      >
        <div
          className="resume-preview-scale-box"
          style={{ width: scaledWidth, height: scaledHeight }}
        >
          <iframe
            ref={iframeRef}
            title="简历预览"
            className="resume-iframe"
            width={A4_WIDTH_PX}
            height={A4_HEIGHT_PX}
            srcDoc={html}
            sandbox="allow-same-origin"
            scrolling="no"
            onLoad={() => {
              fitFrameContent();
              updateAvailableSpace();
              requestAnimationFrame(fitFrameContent);
            }}
            style={{
              width: A4_WIDTH_PX,
              height: A4_HEIGHT_PX,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
        </div>
      </div>
    </div>
  );
}
