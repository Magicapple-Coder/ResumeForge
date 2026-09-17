import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    clearMocks: true,
    restoreMocks: true,
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
