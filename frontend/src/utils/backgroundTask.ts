/**
 * 「用户离开了等待界面，但活儿还在跑」的完成提醒。
 *
 * 场景：点了"生成岗位解读"以后不想干等，关掉弹窗去干别的。请求本身不会因为弹窗关掉而中断
 * （是一个已经发出去的 Promise），但**结果会随着组件卸载一起丢掉**——用户回来什么也看不到，
 * 于是"可以后台继续"在体验上等于一句空话。
 *
 * 所以约定：生成类弹窗在关闭时把"用户已经离开"记下来，请求结束时如果发现人已经走了，
 * 就改用统一通知（弹窗卡片 + 提示声）告诉他结果好了，而不是对着已卸载的组件 setState。
 */
import { notifyTaskDone } from "./taskNotify";

/** 报告一件"你没在看，但它完成了"的结果。 */
export function announceBackgroundResult(label: string, detail?: string): void {
  notifyTaskDone({
    title: `${label}已完成`,
    description: detail ?? "结果已经可以查看了，回到刚才的页面即可。",
  });
}

/** 报告一件"你没在看，但它失败了"的结果——失败更需要知道。 */
export function announceBackgroundFailure(label: string, detail?: string): void {
  notifyTaskDone({
    kind: "error",
    title: `${label}失败`,
    description: detail ?? "可以回到刚才的页面重试。",
  });
}
