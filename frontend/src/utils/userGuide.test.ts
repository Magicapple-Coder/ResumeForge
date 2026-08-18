import { afterEach, describe, expect, it } from "vitest";
import {
  consumeFirstVisitGuide,
  markUserGuideSeen,
  shouldShowUserGuide,
  USER_GUIDE_STORAGE_KEY,
} from "./userGuide";

afterEach(() => {
  window.localStorage.clear();
});

describe("user guide persistence", () => {
  it("only consumes the first visit", () => {
    expect(consumeFirstVisitGuide(window.localStorage)).toBe(true);
    expect(consumeFirstVisitGuide(window.localStorage)).toBe(false);
    expect(window.localStorage.getItem(USER_GUIDE_STORAGE_KEY)).toBe("1");
  });

  it("supports reopening without changing the first-visit marker", () => {
    markUserGuideSeen(window.localStorage);
    expect(shouldShowUserGuide(window.localStorage)).toBe(false);
  });

  it("does not throw when browser storage is unavailable", () => {
    const unavailableStorage = {
      getItem: () => {
        throw new Error("storage blocked");
      },
      setItem: () => {
        throw new Error("storage blocked");
      },
    };

    expect(() => consumeFirstVisitGuide(unavailableStorage)).not.toThrow();
    expect(consumeFirstVisitGuide(unavailableStorage)).toBe(true);
  });
});
