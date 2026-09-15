/** 资料分区排序状态与指针拖拽行为。 */

import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import {
  DEFAULT_SECTION_ORDER,
  SECTION_DRAG_THRESHOLD_PX,
  type ProfileSectionKey,
} from "../../components/profile/ProfileSectionConfig";

interface Options {
  editing: boolean;
  saving: boolean;
  photoReading: boolean;
}

export function useProfileSectionReorder({ editing, saving, photoReading }: Options) {
  const [sectionOrder, setSectionOrder] = useState<ProfileSectionKey[]>(DEFAULT_SECTION_ORDER);
  const [sectionReorderMode, setSectionReorderMode] = useState(false);
  const [draggingSection, setDraggingSection] = useState<ProfileSectionKey | null>(null);
  const [dragOverSection, setDragOverSection] = useState<ProfileSectionKey | null>(null);
  const sectionPointerStart = useRef<{ x: number; y: number } | null>(null);
  const sectionDragActivated = useRef(false);

  const clearDragState = () => {
    sectionPointerStart.current = null;
    sectionDragActivated.current = false;
    setDraggingSection(null);
    setDragOverSection(null);
  };

  const resetSectionReorder = (nextOrder?: ProfileSectionKey[]) => {
    if (nextOrder) setSectionOrder(nextOrder);
    setSectionReorderMode(false);
    clearDragState();
  };

  const handleSectionPointerDown = (
    event: ReactPointerEvent<HTMLButtonElement>,
    sectionKey: ProfileSectionKey,
  ) => {
    if (!editing || saving || photoReading) return;
    event.preventDefault();
    sectionPointerStart.current = { x: event.clientX, y: event.clientY };
    sectionDragActivated.current = false;
    setSectionReorderMode(true);
    setDraggingSection(sectionKey);
    setDragOverSection(null);
  };

  useEffect(() => {
    if (!draggingSection) return;
    const findSectionAtPoint = (clientX: number, clientY: number): ProfileSectionKey | null => {
      const element = document.elementFromPoint(clientX, clientY);
      const section = element?.closest<HTMLElement>("[data-profile-section-key]");
      const key = section?.dataset.profileSectionKey;
      return key && DEFAULT_SECTION_ORDER.includes(key as ProfileSectionKey)
        ? (key as ProfileSectionKey)
        : null;
    };
    const handlePointerMove = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = sectionPointerStart.current;
      if (!start) return;
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (!sectionDragActivated.current && distance < SECTION_DRAG_THRESHOLD_PX) return;
      sectionDragActivated.current = true;
      const target = findSectionAtPoint(event.clientX, event.clientY);
      setDragOverSection(target && target !== draggingSection ? target : null);
    };
    const finishSectionDrag = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = sectionPointerStart.current;
      const distance = start ? Math.hypot(event.clientX - start.x, event.clientY - start.y) : 0;
      const target = findSectionAtPoint(event.clientX, event.clientY);
      if (
        sectionDragActivated.current &&
        distance >= SECTION_DRAG_THRESHOLD_PX &&
        target &&
        target !== draggingSection
      ) {
        setSectionOrder((current) => {
          const next = [...current];
          const sourceIndex = next.indexOf(draggingSection);
          const targetIndex = next.indexOf(target);
          if (sourceIndex < 0 || targetIndex < 0) return current;
          next.splice(sourceIndex, 1);
          next.splice(targetIndex, 0, draggingSection);
          return next;
        });
      }
      clearDragState();
    };
    document.addEventListener("pointermove", handlePointerMove, { passive: false });
    document.addEventListener("pointerup", finishSectionDrag);
    document.addEventListener("pointercancel", finishSectionDrag);
    return () => {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", finishSectionDrag);
      document.removeEventListener("pointercancel", finishSectionDrag);
    };
  }, [draggingSection]);

  const toggleSectionReorderMode = () => {
    setSectionReorderMode((current) => {
      if (current) clearDragState();
      return !current;
    });
  };

  const moveSectionByOffset = (sectionKey: ProfileSectionKey, offset: -1 | 1) => {
    setSectionOrder((current) => {
      const sourceIndex = current.indexOf(sectionKey);
      const targetIndex = sourceIndex + offset;
      if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= current.length) return current;
      const next = [...current];
      next.splice(sourceIndex, 1);
      next.splice(targetIndex, 0, sectionKey);
      return next;
    });
  };

  return {
    sectionOrder,
    setSectionOrder,
    sectionReorderMode,
    setSectionReorderMode,
    draggingSection,
    dragOverSection,
    resetSectionReorder,
    handleSectionPointerDown,
    toggleSectionReorderMode,
    moveSectionByOffset,
  };
}
