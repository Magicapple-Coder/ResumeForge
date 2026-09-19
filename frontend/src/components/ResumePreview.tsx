/** 简历预览：固定为一张 A4 纸，支持抓手浏览和按字段定位编辑。 */
import {
  DragOutlined,
  EditOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { Alert, Button, Segmented, Space, Tooltip, Typography } from "antd";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  measureResumeLayout,
  overflowHeightFor,
  pagesNeededFor,
  type LayoutMeasure,
} from "../utils/resumeLayoutMeasure";

interface Props {
  html: string;
  warnings: string[];
  /** 预览页数：与渲染时的 page_limit 一致；溢出时画布按 N 张 A4 左右并排。 */
  pages?: number;
  /** 仅作为首次布局尚未测量时的占位高度；装得下时画布是 A4 × 页数，溢出时切成单页高 × N 列宽。 */
  height?: number;
  /** 提供后显示“点击编辑”模式，并返回结构化简历字段路径。 */
  onEditTarget?: (path: string) => void;
  /** 渲染完成后的版式状态：当前页数、自动缩放比例与是否溢出。 */
  onLayoutStatus?: (status: { pages: number; scale: number; overflow: boolean }) => void;
  /** 实测高度，交给「版面诊断」用。只有浏览器能量准，所以由预览负责量、上报。 */
  onMeasure?: (measure: LayoutMeasure) => void;
}

const A4_WIDTH_PX = 794;
const A4_HEIGHT_PX = 1123;
const PREVIEW_BOTTOM_RESERVE = 150;
/**
 * 预览区高度的**稳定预算**（窗口高度的比例）与下限。
 *
 * 这里刻意**不**用「窗口高度 − 预览容器顶端位置」：那样预览高度会跟着上方内容走，
 * 「版面诊断」一长就把预览压小，而缩放标签仍然写着 100%——用户看到的是"什么都没改，
 * 预览却缩水了"。改成按窗口给一个固定预算：上方内容再长也只让弹窗自身滚动，
 * 预览始终保持同一个可读高度。
 */
const PREVIEW_HEIGHT_RATIO = 0.62;
const MIN_PREVIEW_HEIGHT = 360;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3.5;

/**
 * 溢出时多页视图的"近似"声明。
 *
 * **为什么必须显式标注**：这里只是把同一份连续流按 A4 高度切几刀、画几条虚线，
 * 并不等于浏览器打印 / 下载 PDF 的真实分页（那要遵守 CSS paged media / 服务端排版，
 * 屏幕上没有任何浏览器实现它）。不标注的话，用户会把它当成"真实分页"——那正是本批
 * 反复修"看起来真、其实不准"这一类缺陷的根源。所以这段文案必须与多页视图**同生共死**，
 * 有测试盯着它不能被单独去掉。
 */
export const APPROXIMATE_PAGINATION_NOTE =
  "多页视图为「按 A4 高度切分的近似分页」，真实分页以「浏览器打印 / 下载 PDF」为准。";

/**
 * 溢出时 iframe 内注入的「横向多列」样式：把同一份连续流用 CSS `columns` 排成若干列、
 * 左右并排，而不是向下堆叠。
 *
 * **为什么用 columns 而不是自造分页**：
 * - 自造分页（把内容按像素切进 N 个页盒）会引入第二套分页口径——屏幕切一刀的位置和浏览器
 *   `@page` + `break-inside: avoid` 切的位置必然不同，这正是此前反复修的"看起来真、其实不准"
 *   那类缺陷的成因。CSS `columns` 让浏览器自己排流，我们只是把容器限制成"一页高、N 页宽"，
 *   内容仍是**同一条流**。
 * - 同一条流意味着**只有一个 `--fit-scale`、只有一套字号与边距**：模板脚本把 `--fit-scale`
 *   写在 body 上、由 `--fs` 吸收，各列共用同一份 CSS，所以第 2 页的字号/边距天然和第 1 页
 *   一致，不存在"给第 2 页另设参数"的问题。
 * - 每列几何自洽：body 保留模板自带的 14mm 页边距，列宽取 210mm - 2×14mm、列间距取 2×14mm
 *   （第 N 页右边距 + 第 N+1 页左边距），于是每张"纸"恰好 210mm 宽，页边界落在 210mm 的整数倍处，
 *   外层分隔线按 A4_WIDTH_PX 等距画即可对齐。
 */
const COLUMNS_CSS =
  "html,body{overflow:hidden!important}" +
  "body{width:auto!important;height:297mm!important;" +
  "column-width:182mm!important;column-gap:28mm!important;column-fill:auto!important}";

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

/** 预览暴露给外部的命令式接口，只给「自动一页」用。 */
export interface ResumePreviewHandle {
  /**
   * 临时注入一段 CSS 后量一次，量完立刻还原。
   *
   * 「自动一页」靠它逐档试版式：不需要重新渲染（没有网络往返），量到的就是这份内容
   * 在那一档版式下的真实高度。传空串等于"先撤掉探针"。
   */
  measureWithProbe(css: string): LayoutMeasure | null;
  /**
   * 拖动字号时的**即时视觉反馈**：把一段常驻探针样式注入预览（不测量、也不还原）。
   *
   * 与 `measureWithProbe` 的区别是它**不撤销**——用户要看到的是"这个字号长什么样"，
   * 而 `measureWithProbe` 只在量高度时临时套用再摘掉。下一次 `html` 变化会让 iframe
   * 重新加载，这段样式随之消失，所以拖动结束、真实渲染回来后它自然被清掉；传空串可
   * 主动撤掉。**不发任何网络请求**——整段拖动通常几十个事件，每个都 PATCH + render 会
   * 打出几十个请求，而用户看到的还是滞后一跳的旧结果。
   */
  setLiveProbe(css: string): void;
}

const PROBE_STYLE_ID = "resume-fit-probe";
/** 拖动字号的常驻探针样式 id（与 `measureWithProbe` 的临时探针分开，避免互相顶掉）。 */
const LIVE_PROBE_STYLE_ID = "resume-font-live-probe";

const ResumePreview = forwardRef<ResumePreviewHandle, Props>(function ResumePreview(
  { html, warnings, pages = 1, height, onEditTarget, onLayoutStatus, onMeasure },
  ref,
) {
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
  // 预览自己量到的版面：用于"约需几页 / 还差多少"的兜底展示（不依赖诊断接口）。
  const [measure, setMeasure] = useState<LayoutMeasure | null>(null);
  // 内容是否超出所选页数：决定要不要切多页、要不要显示超出提示。
  const [overflow, setOverflow] = useState(false);
  // 横向多列的总宽（未缩放 px）：溢出时 iframe 要宽到能把全部列画出来。
  const [naturalWidth, setNaturalWidth] = useState(A4_WIDTH_PX);

  const updateAvailableSpace = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    // 宽度仍取自容器（预览区是 width:100%，不会因为高度变化而变宽，所以不构成反馈环）；
    // 高度只由窗口决定，与上方内容无关——见 PREVIEW_HEIGHT_RATIO 的说明。
    const budget = Math.round(window.innerHeight * PREVIEW_HEIGHT_RATIO);
    const ceiling = Math.max(MIN_PREVIEW_HEIGHT, window.innerHeight - PREVIEW_BOTTOM_RESERVE);
    setAvailableSpace({
      width: container.clientWidth,
      height: Math.min(ceiling, Math.max(MIN_PREVIEW_HEIGHT, budget)),
    });
  }, []);

  const fitFrameContent = useCallback(() => {
    const document = iframeRef.current?.contentDocument;
    const body = document?.body;
    const root = document?.documentElement;
    if (!document || !body || !root) return;

    // 长内容压缩到所选页数内。
    //
    // **缩放只由模板脚本负责**（它把 `--fit-scale` 写在 body 上，由 CSS 的 `--fs` 吸收，
    // 让**版式**真实变矮）。预览层**不再自己加 transform**：transform 只改视觉、不改版式，
    // 两套缩放叠在一起时，预览看起来刚好一页、而打印/导出按**未缩放的版式**分页，于是
    // "预览一页装得下、浏览器打印却超出一页"（用户实测反馈）。分页只能靠版式对齐，
    // 所以这里只做两件事：量尺寸、读状态；脚本没跑时才用**同一套机制**兜底。
    body.style.width = "";
    body.style.height = "";

    // 先撤掉上一轮可能注入的「横向多列」样式，回到单列布局再量。CSS columns 会把纵向高度
    // 折成"一页高、N 列宽"，直接量会拿到错误（偏小）的高度、导致"约需几页"算错——所以测量
    // 必须发生在单列状态下，量完再按需重新注入。整个过程同步完成，中间不会画出来。
    let style = document.getElementById("resume-preview-style") as HTMLStyleElement | null;
    if (style) style.textContent = "";

    // 量真实尺寸必须在缩放之前做：量完再让脚本自己去缩。
    const measured = measureResumeLayout(document, pageCount);
    if (measured) onMeasure?.(measured);

    const reportedScale = Number(body.dataset.scale ?? "");
    const templateScriptRan = Number.isFinite(reportedScale) && reportedScale > 0;

    let overflow = body.dataset.overflow === "1";
    if (!templateScriptRan) {
      // 兜底（理论上不该发生：内置模板与用户自制模板都会带上自适应脚本）。
      // 用的是同一套 `--fit-scale` 机制，不是 transform——否则兜底路径又会造出第二种分页口径。
      const contentWidth = Math.max(body.scrollWidth, root.scrollWidth, A4_WIDTH_PX);
      const contentHeight = Math.max(body.scrollHeight, root.scrollHeight, paperHeight);
      const contentScale = Math.min(1, A4_WIDTH_PX / contentWidth, paperHeight / contentHeight);
      if (contentScale < 1) body.style.setProperty("--fit-scale", contentScale.toFixed(4));
      overflow = overflow || body.scrollHeight > paperHeight + 1;
    }

    // 真实页数用浏览器量到的版面算：与后端 derive_pages 同一套 ceil 口径，但不下网络、
    // 也不依赖 `X-Resume-Pages`（那个头只在 PDF 导出时由服务端写，HTML 预览路径里根本没有）。
    // 只有浏览器量得准 HTML 里的真实高度，所以它才是"这份内容约需几页"的唯一诚实来源。
    const pagesNeeded = measured ? pagesNeededFor(measured) : pageCount;
    overflow = overflow || pagesNeeded > pageCount;

    // 内容装得下时保持原来的 `overflow:hidden`（单页行为不变）；溢出时切成「横向多列」，
    // 让放不下的内容向右排到第 2、3…列（左右铺开、水平滚动），而不是被裁掉看不见。
    if (!style) {
      style = document.createElement("style");
      style.id = "resume-preview-style";
      document.head.appendChild(style);
    }
    style.textContent = overflow ? COLUMNS_CSS : "html,body{overflow:hidden!important}";

    // 横向多列的总宽：溢出时 iframe 要宽到能把全部列画出来，再由外层按 A4 宽度画页分隔线。
    let totalNaturalWidth = A4_WIDTH_PX;
    if (overflow) {
      // 强制一次重排，让 columns 生效后再量横向总宽。
      void body.offsetWidth;
      totalNaturalWidth = Math.max(body.scrollWidth, root.scrollWidth, A4_WIDTH_PX);
    }

    setMeasure(measured);
    setOverflow(overflow);
    setNaturalWidth(totalNaturalWidth);

    // 模板脚本把实际页数、缩放比例与溢出状态写在 body.dataset 上；读出来交给父组件，
    // 内容塞不下时才能提示「增加页数 / 缩小字号」。
    onLayoutStatus?.({
      pages: Number(body.dataset.pages ?? "") || pageCount,
      scale: templateScriptRan ? reportedScale : 1,
      overflow,
    });
  }, [onLayoutStatus, onMeasure, pageCount, paperHeight]);

  useImperativeHandle(
    ref,
    () => ({
      measureWithProbe(css: string) {
        const document = iframeRef.current?.contentDocument;
        if (!document?.body) return null;
        document.getElementById(PROBE_STYLE_ID)?.remove();
        if (css) {
          const style = document.createElement("style");
          style.id = PROBE_STYLE_ID;
          style.textContent = css;
          document.head.appendChild(style);
        }
        try {
          // 量之前必须把压缩用的 transform 摘掉（measureResumeLayout 自己会处理），
          // 并且强制一次重排，否则拿到的是应用新 CSS 之前的旧布局。
          void document.body.offsetHeight;
          return measureResumeLayout(document, pageCount);
        } finally {
          if (css) document.getElementById(PROBE_STYLE_ID)?.remove();
        }
      },
      setLiveProbe(css: string) {
        const document = iframeRef.current?.contentDocument;
        const head = document?.head;
        if (!document || !head) return;
        const existing = document.getElementById(LIVE_PROBE_STYLE_ID) as HTMLStyleElement | null;
        if (!css) {
          existing?.remove();
          return;
        }
        // 复用同一个 style 元素、只改内容：拖动期间每次都新建会不断往 head 里塞节点。
        const style = existing ?? document.createElement("style");
        style.id = LIVE_PROBE_STYLE_ID;
        style.textContent = css;
        if (!existing) head.appendChild(style);
      },
    }),
    [pageCount],
  );

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
  // 溢出时画布从"页数上限 × A4"变成"单页高 × N 列宽"，但"一页"的 fit 基准仍按单张 A4 算：
  // 每张 A4 都按正常比例缩放，整行纸在 viewport 里左右滚动，而不是把一长条硬塞进一屏。
  const contentUnitHeight = overflow ? A4_HEIGHT_PX : paperHeight;
  const contentTotalWidth = overflow ? Math.max(naturalWidth, A4_WIDTH_PX) : A4_WIDTH_PX;
  const contentTotalHeight = overflow ? A4_HEIGHT_PX : paperHeight;
  const fitScale = Math.min(1, viewportWidth / A4_WIDTH_PX, viewportHeight / contentUnitHeight);
  const scale = Math.min(2.5, fitScale * zoom);
  // 多页时容器最多占满一页高，剩下的靠左右滚动查看，不然弹窗会被撑到几千像素宽。
  const viewportHeightForPage = Math.min(contentUnitHeight * fitScale, viewportHeight);
  const scaledWidth = contentTotalWidth * scale;
  const scaledHeight = contentTotalHeight * scale;

  // 约需页数 / 超出量：浏览器量到才有；量不到（jsdom / 脚本未跑完）时用"至少再多一页"兜底。
  const pagesNeeded = measure ? pagesNeededFor(measure) : overflow ? pageCount + 1 : pageCount;
  const overflowAmount = measure ? overflowHeightFor(measure) : 0;
  // 多页视图共几张 A4（近似）：至少比上限多一页，再按横向多列的总宽取整（每张纸 = A4 宽）。
  const totalVisualPages = overflow
    ? Math.max(pageCount + 1, Math.round(naturalWidth / A4_WIDTH_PX))
    : pageCount;
  const separatorCount = overflow ? totalVisualPages - 1 : 0;

  // 超出量文案：量得到就精确到"多出百分之几的一页 / 多出几页"，量不到就如实说不确定。
  const overflowAmountText = measure
    ? (() => {
        const ratio = overflowAmount / measure.pageContentHeight;
        return ratio < 1
          ? `正文还多出约 ${Math.max(1, Math.round(ratio * 100))}% 的一页高度。`
          : `正文还多出约 ${ratio.toFixed(1)} 页的高度。`;
      })()
    : "暂时量不到精确的超出量。";

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
            {Math.round(scale * 100)}%
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
          <Tooltip title="适应页面（重置缩放）">
            <Button
              type="text"
              size="small"
              aria-label="适应页面"
              icon={<ReloadOutlined />}
              onClick={() => setZoom(1)}
            />
          </Tooltip>
        </Space>
      </div>
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
        style={{ height: viewportHeightForPage }}
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
            onLoad={() => {
              fitFrameContent();
              updateAvailableSpace();
              bindFrameInteractions();
              requestAnimationFrame(fitFrameContent);
            }}
            data-interaction-mode={interactionMode}
            style={{
              width: contentTotalWidth,
              height: contentTotalHeight,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
          {Array.from({ length: separatorCount }, (_, index) => {
            const pageNumber = index + 2; // 第 0 条线是"第 2 页"的左边界。
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
    </div>
  );
});

export default ResumePreview;
