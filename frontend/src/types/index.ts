/**
 * 全局类型兼容入口。
 *
 * 类型按领域拆分到相邻模块；保留此处的 re-export，避免历史导入路径失效。
 */

export * from "./common";
export * from "./profile";
export * from "./job";
export * from "./resume";
export * from "./assistant";
export * from "./settings";
export * from "./search";
