/**
 * 统一的"从外面拖文件进来"容器。
 *
 * 项目里有五六个导入入口（岗位识别、备选岗位截图、资料箱附件、个人照片、助手附件），
 * 每个入口单独实现一次拖拽会得到五种略有差异的行为——所以这里做一份：
 *
 * - 只接管文件拖拽；拖进来的是文字或链接时不做任何事，不干扰页面其它拖拽（例如
 *   资料页的区块拖动排序）。
 * - 拖拽进入子元素时浏览器会连续触发 dragenter/dragleave，用计数器判稳，避免
 *   "覆盖层疯狂闪烁"。
 * - 按 accept 过滤，不接受的文件直接忽略并回调 onRejected 让调用方提示。
 */
import type { DragEvent, ReactNode } from "react";
import { useCallback, useRef, useState } from "react";

interface Props {
  onFiles: (files: File[]) => void;
  /** 与 `<input accept>` 同一套写法：`.pdf`、`image/*`、`image/png` 的逗号分隔列表。 */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  hint?: string;
  /** 有文件被过滤掉时回调（数量），调用方据此提示用户格式不支持。 */
  onRejected?: (count: number) => void;
  className?: string;
  children: ReactNode;
}

/** 内部用：按 accept 判断一个文件该不该被接受。没有导出——导出非组件会让
 * React Fast Refresh 退化成整页刷新。 */
function matchesAccept(file: File, accept?: string): boolean {
  if (!accept) return true;
  const rules = accept
    .split(",")
    .map((rule) => rule.trim().toLowerCase())
    .filter(Boolean);
  if (rules.length === 0) return true;
  const name = file.name.toLowerCase();
  const type = (file.type || "").toLowerCase();
  return rules.some((rule) => {
    if (rule.startsWith(".")) return name.endsWith(rule);
    if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
    return type === rule;
  });
}

export default function FileDropZone({
  onFiles,
  accept,
  multiple = true,
  disabled = false,
  hint = "松开即可导入",
  onRejected,
  className = "",
  children,
}: Props) {
  const [dragging, setDragging] = useState(false);
  // dragenter/dragleave 会在子元素之间反复触发，用深度计数判断"是否真的离开了"。
  const depthRef = useRef(0);

  const reset = useCallback(() => {
    depthRef.current = 0;
    setDragging(false);
  }, []);

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (disabled) return;
    // 只接管"文件"拖拽；拖文字进来时保持浏览器默认行为。
    if (!Array.from(event.dataTransfer?.types ?? []).includes("Files")) return;
    event.preventDefault();
    depthRef.current += 1;
    setDragging(true);
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (!Array.from(event.dataTransfer?.types ?? []).includes("Files")) return;
    // 必须 preventDefault，否则浏览器会直接打开这个文件。
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.preventDefault();
    depthRef.current = Math.max(0, depthRef.current - 1);
    if (depthRef.current === 0) setDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.preventDefault();
    reset();
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length === 0) return;
    const accepted = files.filter((file) => matchesAccept(file, accept));
    const rejected = files.length - accepted.length;
    if (rejected > 0) onRejected?.(rejected);
    if (accepted.length === 0) return;
    onFiles(multiple ? accepted : accepted.slice(0, 1));
  };

  return (
    <div
      className={`file-drop-zone${dragging ? " is-dragging" : ""}${className ? ` ${className}` : ""}`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}
      {dragging && (
        <div className="file-drop-overlay" aria-hidden>
          <span className="file-drop-overlay-text">{hint}</span>
        </div>
      )}
    </div>
  );
}
