import react from "@vitejs/plugin-react";
import { codeInspectorPlugin } from "code-inspector-plugin";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendUrl = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

  return {
    // 开发调试辅助：按住 Alt+Shift（Windows）点击页面元素，自动在 VS Code 中定位到对应源码行。
    // 插件自身只在 dev server 生效，生产构建不受影响。
    plugins: [react(), codeInspectorPlugin({ bundler: "vite", editor: "code" })],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (
              /[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(
                id,
              )
            ) {
              return "react-vendor";
            }
          },
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  };
});
