import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    clearMocks: true,
    restoreMocks: true,
    // Cap concurrent test files. Vitest defaults to one worker per core, and each
    // fork is a whole Node process: an Ant Design-heavy page costs well over a
    // gigabyte to import, so on a many-core machine the default fan-out dies with
    // "JavaScript heap out of memory" **before printing any results at all**
    // (reproduced on a 32-core Windows box; the run never finishes, it aborts).
    //
    // 4 rather than something closer to the core count, because it is the number
    // that was actually measured to be both reliable and no slower: the suite
    // takes ~217s at 4 and ~250s at 8 (the bottleneck is per-file module import,
    // not CPU), while at 8 a streaming test with its own 10s budget starts timing
    // out under contention. Small CI runners pick fewer workers anyway, so this
    // cap only binds on the machines that were crashing.
    maxWorkers: 4,
    // Shared CI runners can spend several seconds mounting Ant Design-heavy
    // pages; keep async UI assertions from failing before the render settles.
    //
    // 30s rather than 15s: settings/message pages mount six cards plus a message
    // list, and a full mount of those costs seconds of jsdom work per test. At
    // 15s the heaviest tests passed alone but timed out when the suite ran with
    // two workers. Per-test overrides equal to the global were removed so this
    // stays the single place to tune — an override silently wins over it.
    testTimeout: 30_000,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },
});
