/** 简历预览：固定为一张 A4 纸，支持抓手浏览和按字段定位编辑。 */
import {
  DragOutlined,
  EditOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { Alert, Button, Segmented, Space, Tooltip, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  html: string;
  warnings: string[];
  /** 预览页数：与渲染时的 page_limit 一致，多页时画布按 N 张 A4 叠起来。 */
  pages?: number;
  /** 仅作为首次布局尚未测量时的占位高度，实际画布始终是 A4 × 页数。 */
  height?: number;
  /** 提供后显示“点击编辑”模式，并返回结构化简历字段路径。 */
  onEditTarget?: (path: string) => void;
  /** 渲染完成后的版式状态：当前页数、自动缩放比例与是否溢出。 */
  onLayoutStatus?: (status: { pages: number; scale: number; overflow: boolean }) => void;
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

type InteractionMode = "pan" | "edit";

export default function ResumePreview({
  html,
  warnings,
  pages = 1,
  height,
  onEditTarget,
  onLayoutStatus,
}: Props) {
  const pageCount = Math.max(1, Math.round(pages));
  const paperHeight = A4_HEIGHT_PX * pageCount;
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const panStartRef = useRef<PanStart | null>(null);
  const frameCleanupRef = useRef<(() => void) | null>(null);
  const [availableSpace, setAvailableSpace] = useState<AvailableSpace>({
    width: 0,
    height: height ?? paperHeight,
  });
  const [zoom, setZoom] = useState(1);
  const [isPanning, setIsPanning] = useState(false);
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("pan");

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

    // 长内容压缩到所选页数内（与模板脚本同一套算法），避免用户必须在 iframe 中滚动查看。
    body.style.transform = "none";
    body.style.transformOrigin = "top left";
    body.style.width = "";
    body.style.height = "";
    const contentWidth = Math.max(body.scrollWidth, root.scrollWidth, A4_WIDTH_PX);
    const contentHeight = Math.max(body.scrollHeight, root.scrollHeight, paperHeight);
    const contentScale = Math.min(1, A4_WIDTH_PX / contentWidth, paperHeight / contentHeight);
    if (contentScale < 1) {
      body.style.width = `${A4_WIDTH_PX / contentScale}px`;
      body.style.height = `${paperHeight / contentScale}px`;
      body.style.transform = `scale(${contentScale})`;
    }
    root.style.overflow = "hidden";

    // 模板脚本把实际页数、缩放比例与溢出状态写在 body.dataset 上；读出来交给父组件，
    // 内容塞不下时才能提示「增加页数 / 缩小字号」。
    const reportedScale = Number(body.dataset.scale ?? "");
    onLayoutStatus?.({
      pages: Number(body.dataset.pages ?? "") || pageCount,
      scale: Number.isFinite(reportedScale) && reportedScale > 0 ? reportedScale : contentScale,
      overflow: body.dataset.overflow === "1" || contentHeight > paperHeight + 1,
    });
  }, [onLayoutStatus, pageCount, paperHeight]);

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
  const viewportHeight = availableSpace.height || paperHeight;
  const fitScale = Math.min(1, viewportWidth / A4_WIDTH_PX, viewportHeight / paperHeight);
  const scale = Math.min(2.5, fitScale * zoom);
  // 多页时容器最多占满可用高度，剩下的靠滚动查看，不然弹窗会被撑到几千像素高。
  const viewportHeightForPage = Math.min(paperHeight * fitScale, viewportHeight);
  const scaledWidth = A4_WIDTH_PX * scale;
  const scaledHeight = paperHeight * scale;

  const handleWheel = useCallback((event: globalThis.WheelEvent) => {
    // iframe 会独立接收滚轮；在外层用非被动监听确保每次都能缩放预览。
    if (event.deltaY === 0) return;
    event.preventDefault();
    const direction = event.deltaY > 0 ? -1 : 1;
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current + direction * 0.1)));
  }, []);

  const bindFrameInteractions = useCallback(() => {
    frameCleanupRef.current?.();
    frameCleanupRef.current = null;
    const document = iframeRef.current?.contentDocument;
    if (!document) return;

    document.addEventListener("wheel", handleWheel, { passive: false });
    const interactiveStyle = document.getElementById("resume-preview-interaction-style");
    interactiveStyle?.remove();

    let handleClick: ((event: MouseEvent) => void) | undefined;
    let handleKeyDown: ((event: KeyboardEvent) => void) | undefined;
    const targets = Array.from(document.querySelectorAll<HTMLElement>("[data-resume-path]"));
    const originalAttributes = new Map(
      targets.map((target) => [
        target,
        {
          role: target.getAttribute("role"),
          tabIndex: target.getAttribute("tabindex"),
        },
      ]),
    );
    if (interactionMode === "edit" && onEditTarget) {
      const style = document.createElement("style");
      style.id = "resume-preview-interaction-style";
      style.textContent =
        "[data-resume-path]{cursor:pointer;border-radius:2px;outline:1px solid transparent}" +
        "[data-resume-path]:hover,[data-resume-path]:focus{outline:2px solid #1677ff;outline-offset:2px;background:rgba(22,119,255,.08)}";
      document.head.appendChild(style);
      targets.forEach((target) => {
        target.setAttribute("role", "button");
        target.setAttribute("tabindex", "0");
      });

      const resolveTarget = (target: EventTarget | null) => {
        const ElementConstructor = document.defaultView?.Element;
        return ElementConstructor && target instanceof ElementConstructor
          ? target.closest<HTMLElement>("[data-resume-path]")
          : null;
      };
      handleClick = (event) => {
        const target = resolveTarget(event.target);
        const path = target?.dataset.resumePath;
        if (!path) return;
        event.preventDefault();
        onEditTarget(path);
      };
      handleKeyDown = (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const target = resolveTarget(event.target);
        const path = target?.dataset.resumePath;
        if (!path) return;
        event.preventDefault();
        onEditTarget(path);
      };
      document.addEventListener("click", handleClick);
      document.addEventListener("keydown", handleKeyDown);
    }

    frameCleanupRef.current = () => {
      document.removeEventListener("wheel", handleWheel);
      if (handleClick) document.removeEventListener("click", handleClick);
      if (handleKeyDown) document.removeEventListener("keydown", handleKeyDown);
      targets.forEach((target) => {
        const original = originalAttributes.get(target);
        if (original?.role === null) target.removeAttribute("role");
        else if (original?.role !== undefined) target.setAttribute("role", original.role);
        if (original?.tabIndex === null) target.removeAttribute("tabindex");
        else if (original?.tabIndex !== undefined)
          target.setAttribute("tabindex", original.tabIndex);
      });
      document.getElementById("resume-preview-interaction-style")?.remove();
    };
  }, [handleWheel, interactionMode, onEditTarget]);

  useEffect(() => {
    bindFrameInteractions();
    return () => {
      frameCleanupRef.current?.();
      frameCleanupRef.current = null;
    };
  }, [bindFrameInteractions, html]);

  useEffect(() => {
    const viewport = containerRef.current;
    if (!viewport) return;

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (interactionMode !== "pan") return;
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
  }, [handleWheel, interactionMode]);

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
        <Space size={8} wrap>
          {onEditTarget && (
            <Segmented
              size="small"
              aria-label="简历预览交互模式"
              value={interactionMode}
              onChange={(value) => setInteractionMode(value as InteractionMode)}
              // 两个名字单独看都说不清自己是干嘛的："抓手"是设计软件的行话，"编辑"听起来
              // 像要跳到别的页面；各自配一句悬停说明。
              options={[
                {
                  value: "pan",
                  label: <Tooltip title="按住拖动浏览简历">抓手</Tooltip>,
                  icon: <DragOutlined />,
                },
                {
                  value: "edit",
                  label: <Tooltip title="点击简历中的字段直接修改">编辑</Tooltip>,
                  icon: <EditOutlined />,
                },
              ]}
            />
          )}
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
        className={`resume-preview-viewport${isPanning ? " is-panning" : ""}${interactionMode === "edit" ? " is-editing" : ""}`}
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
            height={paperHeight}
            srcDoc={html}
            sandbox="allow-same-origin"
            scrolling="no"
            onLoad={() => {
              fitFrameContent();
              updateAvailableSpace();
              bindFrameInteractions();
              requestAnimationFrame(fitFrameContent);
            }}
            data-interaction-mode={interactionMode}
            style={{
              width: A4_WIDTH_PX,
              height: paperHeight,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
        </div>
      </div>
    </div>
  );
}
