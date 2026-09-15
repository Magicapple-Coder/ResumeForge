/** 页面级导航动作；单独成模块是为了让测试可以替换它们。 */

/** 整页重载。恢复备份后所有本地状态都需要按新数据重建。 */
export function reloadPage(): void {
  window.location.reload();
}
