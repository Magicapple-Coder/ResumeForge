import { useCallback, useEffect } from "react";
import type { MutableRefObject, RefObject } from "react";
import type { InteractionMode, PanStart } from "./config";

interface Options {
  containerRef: RefObject<HTMLDivElement | null>;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  panStartRef: MutableRefObject<PanStart | null>;
  frameCleanupRef: MutableRefObject<(() => void) | null>;
  interactionMode: InteractionMode;
  onEditTarget?: (path: string) => void;
  /** 鼠标指到哪一栏（离开纸面或移到空白处时给 null）。用于"看到哪就改哪"。 */
  onHoverTarget?: (path: string | null) => void;
  onZoomWheel: (event: globalThis.WheelEvent) => void;
  onPanningChange: (value: boolean) => void;
}

/** 找到弹窗或页面真正负责纵向滚动的容器。 */
function scrollParent(element: HTMLElement | null): HTMLElement | null {
  let current = element?.parentElement ?? null;
  while (current) {
    const style = window.getComputedStyle(current);
    const canScroll =
      (style.overflowY === "auto" || style.overflowY === "scroll") &&
      current.scrollHeight > current.clientHeight;
    if (canScroll) return current;
    current = current.parentElement;
  }
  return document.scrollingElement as HTMLElement | null;
}

/** iframe 是独立文档，普通滚轮不会冒泡到外层；把纵向滚动转交给外层页面。 */
export function forwardWheelToParent(container: HTMLElement | null, event: WheelEvent): boolean {
  const parent = scrollParent(container);
  let consumed = false;
  if (event.deltaY && parent) {
    const previous = parent.scrollTop;
    parent.scrollTop += event.deltaY;
    consumed ||= parent.scrollTop !== previous;
  }
  if (event.deltaX && container) {
    const previous = container.scrollLeft;
    container.scrollLeft += event.deltaX;
    consumed ||= container.scrollLeft !== previous;
  }
  return consumed;
}

export function useFrameInteractions({
  containerRef,
  iframeRef,
  panStartRef,
  frameCleanupRef,
  interactionMode,
  onEditTarget,
  onHoverTarget,
  onZoomWheel,
  onPanningChange,
}: Options) {
  const bindFrameInteractions = useCallback(() => {
    frameCleanupRef.current?.();
    frameCleanupRef.current = null;
    const document = iframeRef.current?.contentDocument;
    if (!document) return;

    document.addEventListener("wheel", onZoomWheel, { passive: false });
    document.getElementById("resume-preview-interaction-style")?.remove();

    let handleClick: ((event: MouseEvent) => void) | undefined;
    let handleKeyDown: ((event: KeyboardEvent) => void) | undefined;
    let handleHoverOver: ((event: MouseEvent) => void) | undefined;
    let handleHoverOut: ((event: MouseEvent) => void) | undefined;
    const targets = Array.from(document.querySelectorAll<HTMLElement>("[data-resume-path]"));
    const originalAttributes = new Map(
      targets.map((target) => [
        target,
        { role: target.getAttribute("role"), tabIndex: target.getAttribute("tabindex") },
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
      if (onHoverTarget) {
        // 用 **mousemove** 而不是 mouseover 来跟踪"指针在哪一栏"。
        //
        // 为什么：实测（真实 Chromium + Playwright 移动鼠标）`mouseover` 在这个 iframe
        // 的文档里收不到——鼠标从工具栏移进纸面时，帧内元素不会收到那一次进入事件，
        // 于是"看到哪就改哪"在这个最该生效的路径上失效（而合成派发 mouseover 又是好的，
        // 只在单测里看不出来）。mousemove 在指针停留期间持续冒泡，进入元素后必定会来一次。
        //
        // 去重：同一个 path 连续来只 setState 一次，避免每移动一个像素就重渲染工具栏。
        let lastPath: string | null = null;
        console.log("HOVER: mousemove 监听器已挂载");
        handleHoverOver = (event: MouseEvent) => {
          console.log("HOVER: mousemove 触发", (event.target as HTMLElement)?.dataset?.resumePath);
          const path = resolveTarget(event.target)?.dataset.resumePath ?? null;
          if (!path || path === lastPath) return;
          lastPath = path;
          onHoverTarget(path);
        };
        handleHoverOut = (event) => {
          const target = resolveTarget(event.target);
          if (!target) return;
          if (resolveTarget(event.relatedTarget) === target) return;
          lastPath = null;
          onHoverTarget(null);
        };
        document.addEventListener("mousemove", handleHoverOver);
        document.addEventListener("mouseout", handleHoverOut);
      }
      document.addEventListener("click", handleClick);
      document.addEventListener("keydown", handleKeyDown);
    }

    frameCleanupRef.current = () => {
      document.removeEventListener("wheel", onZoomWheel);
      if (handleClick) document.removeEventListener("click", handleClick);
      if (handleKeyDown) document.removeEventListener("keydown", handleKeyDown);
      if (handleHoverOver) document.removeEventListener("mousemove", handleHoverOver);
      if (handleHoverOut) document.removeEventListener("mouseout", handleHoverOut);
      // 退出编辑态（或组件卸载）时把"当前指向"清掉：不然工具栏那颗提示会一直挂在
      // 上一个被指过的栏目上，看起来像还在指着它。
      // 注意：这里**不**清 onHoverTarget——父组件的重渲染会让本 effect 重跑（回调是内联
      // 函数、每次都是新引用），在 cleanup 里 setState 会形成"清空 → 重渲染 → 又重跑"的
      // 振荡（实测 hover 一生效就被清掉）。"指针离开"由 mouseout 负责；"离开编辑态"由
      // ResumePreview 对 interactionMode 变化的响应负责。
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
  }, [frameCleanupRef, iframeRef, interactionMode, onEditTarget, onHoverTarget, onZoomWheel]);

  useEffect(() => {
    bindFrameInteractions();
    return () => {
      frameCleanupRef.current?.();
      frameCleanupRef.current = null;
    };
  }, [bindFrameInteractions, frameCleanupRef, iframeRef]);

  useEffect(() => {
    const viewport = containerRef.current;
    if (!viewport) return;

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (interactionMode !== "pan" || event.button !== 0) return;
      event.preventDefault();
      panStartRef.current = {
        clientX: event.clientX,
        clientY: event.clientY,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      viewport.setPointerCapture?.(event.pointerId);
      onPanningChange(true);
    };
    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const start = panStartRef.current;
      if (!start) return;
      event.preventDefault();
      viewport.scrollLeft = start.scrollLeft - (event.clientX - start.clientX);
      viewport.scrollTop = start.scrollTop - (event.clientY - start.clientY);
    };
    const stopPanning = (event: globalThis.PointerEvent) => {
      if (viewport.hasPointerCapture?.(event.pointerId))
        viewport.releasePointerCapture?.(event.pointerId);
      panStartRef.current = null;
      onPanningChange(false);
    };

    viewport.addEventListener("wheel", onZoomWheel, { passive: false });
    viewport.addEventListener("pointerdown", handlePointerDown);
    viewport.addEventListener("pointermove", handlePointerMove);
    viewport.addEventListener("pointerup", stopPanning);
    viewport.addEventListener("pointercancel", stopPanning);
    viewport.addEventListener("lostpointercapture", stopPanning);
    return () => {
      viewport.removeEventListener("wheel", onZoomWheel);
      viewport.removeEventListener("pointerdown", handlePointerDown);
      viewport.removeEventListener("pointermove", handlePointerMove);
      viewport.removeEventListener("pointerup", stopPanning);
      viewport.removeEventListener("pointercancel", stopPanning);
      viewport.removeEventListener("lostpointercapture", stopPanning);
    };
  }, [containerRef, interactionMode, onPanningChange, onZoomWheel, panStartRef]);

  return bindFrameInteractions;
}
