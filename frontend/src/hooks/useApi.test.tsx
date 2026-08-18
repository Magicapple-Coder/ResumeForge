import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useApi } from "./useApi";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("useApi", () => {
  it("does not let an older response overwrite the latest request", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { result, rerender } = renderHook(
      ({ version }) => useApi(() => (version === 1 ? first.promise : second.promise), [version]),
      { initialProps: { version: 1 } },
    );

    rerender({ version: 2 });
    await act(async () => second.resolve("latest"));
    await waitFor(() => expect(result.current.data).toBe("latest"));

    await act(async () => first.resolve("stale"));
    expect(result.current.data).toBe("latest");
  });
});
