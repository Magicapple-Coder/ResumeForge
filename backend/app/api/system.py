"""应用生命周期接口：退出应用。

这是本项目唯一一个"会让服务消失"的接口，因此边界写得很死：
- **只接受回环请求**：局域网里的页面不该有权限关掉别人的应用；
- 先返回响应再退出（延迟一小会儿），否则浏览器只会看到一个连接被重置的错误。

前端点「退出」后：后端进程结束，页面随即失去全部数据来源，可以直接关闭标签页；
重新使用双击 `start.cmd`。
"""
import ipaddress
import logging
import os
import signal
import threading
import time

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

# 退出前的等待：够响应走完浏览器这一趟，又不至于让用户觉得没反应。
_SHUTDOWN_DELAY_SECONDS = 0.6


def _is_loopback_request(request: Request) -> bool:
    """与密钥查看同一套判断：只有直连本机的请求算数。"""
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    # ipv4_mapped 只存在于 IPv6 地址对象上：直接用属性访问会在"IPv4 且非回环"时
    # 抛 AttributeError（本该返回 403 的请求变成 500）。
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def _stop_process() -> None:
    """在独立线程里让 uvicorn 优雅退出。

    优先给自己发 SIGINT（等价于 Ctrl+C，uvicorn 会走完整的关闭流程：等待进行中的
    请求、关闭连接池与数据库）；极端情况下再用 ``os._exit`` 兜底，避免出现"点了退出
    但进程还在"的状态。
    """
    time.sleep(_SHUTDOWN_DELAY_SECONDS)
    try:
        signal.raise_signal(signal.SIGINT)
        # 给优雅关闭一点时间；仍然活着就强退。
        time.sleep(3.0)
        logger.warning("优雅退出未完成，强制结束进程")
    except Exception:  # noqa: BLE001 - 退出路径本身绝不能抛异常
        logger.exception("发送退出信号失败，强制结束进程")
    os._exit(0)


@router.post("/shutdown", status_code=202)
def shutdown_application(request: Request):
    """退出后端进程（仅本机可调用）。"""
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="只能在运行后端的本机退出应用")
    logger.info("收到退出请求，正在关闭后端")
    threading.Thread(target=_stop_process, name="resumeforge-shutdown", daemon=True).start()
    return {"status": "stopping", "message": "应用正在退出，可以关闭此页面"}
