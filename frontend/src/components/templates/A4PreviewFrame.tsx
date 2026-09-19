/**
 * A4 预览画布：把渲染好的简历 HTML 按 **A4 纸的比例**（794×1123）整体等比缩放放进容器。
 *
 * 为什么不直接铺满容器（模板预览以前的做法）：简历是 794×1123 的**竖版 A4**，而原先的写法
 * 把 iframe 拉成"容器宽 × 72vh"，比例与真实纸张完全不同——用户既看不出"排上去好不好看"，
 * 也看不出"一页到底装不装得下"（预览与导出/打印不一致的抱怨，一部分就来自这里）。
 * 另一处原先写法是**写死** `transform: scale(0.54)`，而列宽是可变的，于是要么没铺满、
 * 要么被裁掉（用户反馈"右侧预览没有一次性展示全"）。
 *
 * 这里统一画一张 A4 纸、按容器实测尺寸整体缩放（contain），所以**任何时候都能完整看到一整页**。
 * 缩放比例由 `ResizeObserver` 实测得出而不是写死断点：这个组件同时用在宽弹窗预览与窄侧栏
 * 预览里，写死断点必然在其中一处失真。
 */
import { useLayoutEffect, useRef, useState } from "react";

/** A4 在 96dpi 下的 CSS 像素尺寸，与后端模板里的 `210mm / 297mm` 对应。 */
export const A4_WIDTH_PX = 794;
export const A4_HEIGHT_PX = 1123;

interface Props {
  html: string;
  /** iframe 的无障碍名称；同时也被测试用来定位。 */
  title: string;
  /** 画布高度上限，默认 72vh。 */
  maxHeight?: string;
}

export default function A4PreviewFrame({ html, title, maxHeight = "72vh" }: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  // 初值给 1 而不是 0：容器尺寸量不到时（jsdom 不做布局）仍要渲染出内容，
  // 否则组件在测试里会"什么都不显示"，那是比缩放不准更糟的失败方式。
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const fit = () => {
      const width = stage.clientWidth;
      const height = stage.clientHeight;
      // 量不到尺寸（布局尚未完成 / 测试环境）就保持当前比例，不要缩成 0。
      if (!width || !height) return;
      setScale(Math.min(width / A4_WIDTH_PX, height / A4_HEIGHT_PX));
    };
    // 放在 layout effect 里：首帧就按正确比例绘制，不会先大后小闪一下。
    fit();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    observer?.observe(stage);
    window.addEventListener("resize", fit);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [html]);

  return (
    <div
      ref={stageRef}
      className="a4-preview-stage"
      style={{ height: `min(${maxHeight}, ${A4_HEIGHT_PX}px)` }}
    >
      <div
        className="a4-preview-paper"
        style={{ width: Math.round(A4_WIDTH_PX * scale), height: Math.round(A4_HEIGHT_PX * scale) }}
      >
        <iframe
          className="a4-preview-frame"
          title={title}
          sandbox=""
          scrolling="no"
          srcDoc={html}
          style={{
            width: A4_WIDTH_PX,
            height: A4_HEIGHT_PX,
            transform: `scale(${scale})`,
          }}
        />
      </div>
    </div>
  );
}
