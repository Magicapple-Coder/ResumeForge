"""进程内单例任务运行器：一个工作线程 + 状态落库 + 前端轮询。

为什么自建而不用框架：本项目是单用户本地应用，投递/采集是"几分钟到几十分钟的同步阻塞
工艺"，引入 Celery/RQ 只会增加部署成本。一个 ``threading.Thread`` 足够，但必须守住几条
纪律，否则会变成"停不下来的后台线程"：

- 工作线程**自己建、自己关** ``SessionLocal()``，会话绝不跨线程共享；
- **每一次 CDP 调用前后**都检查停止/暂停信号（用户点停止要真的停得下来）；
- 工作线程的异常**不许被吞**：兜底把任务置失败并写中文 ``message``；
- 连续失败达阈值**熔断**并醒目提示；每日上限**只计成功投递**。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError
from sqlalchemy import update

from ...database import SessionLocal
from ...config import captures_dir
from .. import tracker
from ...models.apply import (
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_NETWORK_TIMEOUT,
    FAILURE_UNKNOWN,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_RUNNING,
    ITEM_STATUS_SKIPPED,
    ITEM_STATUS_SUCCESS,
    STEP_FILLING,
    STEP_IDLE,
    STEP_OPENING,
    STEP_SUBMITTING,
    STEP_VERIFYING,
    STOP_REASON_BREAKER,
    STOP_REASON_DONE,
    STOP_REASON_ERROR,
    STOP_REASON_USER,
    TASK_KIND_COLLECT,
    TASK_STATUS_BREAKER_PAUSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PAUSED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_STOPPED,
    ApplyTask,
    ApplyTaskItem,
)
from ...models.job import Job
from ...models.profile import utcnow
from ...schemas.apply import ApplyConfigIn, CollectConfigIn
from ..browser.cdp_client import CdpClient, CdpError
from ..browser.sample_recorder import SampleRecordingCdpClient
from ..sites.base import SiteFailure
from ..sites.registry import get_registry
from .collector import Collector

logger = logging.getLogger(__name__)

# 任务终态集合：一旦任务落进这里就表示"这件事结束了"，任何控制接口（暂停 / 恢复 / 停止）
# 都不许再把它改回活动态。用途见 ``TaskRunner._set_status``——它正是 pause/resume 竞态的
# 收敛点：工作线程抢先提交 ``completed`` 后，``resume()`` 的 ``_set_status(RUNNING)`` 必须
# 让位，否则终态会被盖回 ``running`` 且再无人修正，任务永久卡住。
_TERMINAL_STATUSES = frozenset(
    {TASK_STATUS_COMPLETED, TASK_STATUS_STOPPED, TASK_STATUS_FAILED}
)


def _is_within(path: Path, root: Path) -> bool:
    """``path`` 是否落在 ``root`` 之内（两边都 ``resolve``，消掉 ".." 与符号链接）。

    用途见 ``_run_collect`` 里拼样例目录那段：这是"样例只写进 ``captures/``"这条底线的**代码级
    保证**，而不是"相信调用方传对了路径"。``resolve`` 在路径不存在时也能工作（非严格模式）。
    """
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


class TaskStopped(Exception):
    """停止信号在步骤之间被检查到时抛出，用于优雅收尾（不是错误）。"""


class TaskRunnerError(Exception):
    """运行器控制类错误（任务未在运行、已有任务在跑等），message 为中文提示。"""


class _ItemSkip(Exception):
    """单个条目的"软跳过"（如没有可用简历）：不计失败、不触发熔断。"""


class StopAwareCdpClient(CdpClient):
    """包一层 CdpClient，在每次 CDP 调用前检查停止/暂停信号。

    这样即使用户在某个岗位投递的**中途**点停止，也能在"下一次 CDP 调用前"及时退出，
    而不是等整个岗位跑完——这直接对应"停止信号必须在步骤之间被检查到"的硬要求。
    """

    def __init__(self, inner: CdpClient, checkpoint: Callable[[], None]) -> None:
        self._inner = inner
        self._checkpoint = checkpoint

    def _guard(self) -> None:
        self._checkpoint()

    def list_targets(self) -> list[dict[str, Any]]:
        self._guard()
        return self._inner.list_targets()

    def new_tab(self, url: str = "about:blank") -> str:
        self._guard()
        return self._inner.new_tab(url)

    def send(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> dict[str, Any]:
        self._guard()
        return self._inner.send(method, params, timeout=timeout)

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        self._guard()
        return self._inner.evaluate(expression, timeout=timeout)

    def set_file_input(self, selector: str, files: list[str], *, timeout: float | None = None) -> None:
        self._guard()
        return self._inner.set_file_input(selector, files, timeout=timeout)

    def navigate(self, url: str, *, timeout: float | None = None) -> dict[str, Any]:
        self._guard()
        return self._inner.navigate(url, timeout=timeout)

    # 事件订阅必须**显式转发**。``CdpClient`` 给这三个方法提供了"不支持"的空实现，
    # 所以忘了转发不会报错：它安静地返回空事件列表，而站点适配器把"没拦到响应"当作
    # "接口这条路走不通"，于是退回 DOM——**离线测试全绿，生产里网络优先却从未生效**。
    def start_event_capture(self, methods: Sequence[str]) -> None:
        self._guard()
        self._inner.start_event_capture(methods)

    def stop_event_capture(self) -> None:
        # 取走缓冲是纯本地操作，不发 CDP、不等待，所以不插停止检查点：这里抛异常
        # 会让已经拦到的响应白白丢掉。
        self._inner.stop_event_capture()

    def drain_events(self) -> list[dict[str, Any]]:
        return self._inner.drain_events()

    def close(self) -> None:
        self._inner.close()


class TaskRunner:
    """单例任务运行器：同一时刻只跑一个批次（投递或采集）。"""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        registry: Any = None,
        client_factory: Callable[[Any], CdpClient] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval: float = 0.2,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._client_factory = client_factory
        self._sleeper = sleeper
        self._clock = clock
        self._poll = poll_interval
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current_task_id: int | None = None

    # ===== 控制接口 =====

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def current_task_id(self) -> int | None:
        return self._current_task_id

    def start(self, task_id: int) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise TaskRunnerError("已有任务正在进行中，请先停止或等待其完成")
            self._stop.clear()
            self._resume.set()
            self._current_task_id = task_id
            self._thread = threading.Thread(
                target=self._run, args=(task_id,), name=f"rf-task-{task_id}", daemon=True
            )
            self._thread.start()

    def pause(self, task_id: int) -> None:
        # 先落"暂停"再/与工作线程检查点竞争：若工作线程此刻已跑完并提交终态，
        # _set_status 的终态守卫会拒绝把 completed/stopped/failed 改回 paused。
        self._require_current(task_id)
        self._resume.clear()
        self._set_status(task_id, TASK_STATUS_PAUSED)

    def resume(self, task_id: int) -> None:
        # 唤醒工作线程（_resume.set）后写 running 是竞态高发点：worker 可能在写入前就跑完，
        # 因此必须以"当前状态是否已是终态"为准，而不是无条件回写 running（见 _set_status）。
        self._require_current(task_id)
        self._resume.set()
        self._set_status(task_id, TASK_STATUS_RUNNING)

    def stop(self, task_id: int) -> None:
        # 停止目标本身即终态：若任务其实已经 completed（用户点慢了一步），
        # 终态守卫会保留原终态，不把成功的任务误标成 stopped。
        self._require_current(task_id)
        self._stop.set()
        self._resume.set()  # 释放可能正卡在暂停等待里的工作线程
        self._set_status(task_id, TASK_STATUS_STOPPED, STOP_REASON_USER)

    def shutdown(self) -> None:
        self._stop.set()
        self._resume.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _require_current(self, task_id: int) -> None:
        if self._current_task_id != task_id or not self.is_running():
            raise TaskRunnerError("该任务当前未在运行，无法执行该操作")

    # ===== 工作线程 =====

    def _run(self, task_id: int) -> None:
        session = self._session_factory()  # 工作线程自建会话
        task: ApplyTask | None = None
        try:
            task = session.get(ApplyTask, task_id)
            if task is None:
                return
            if self._stop.is_set():
                # 停止信号早于工作线程读取任务（如刚 start 就 stop）：与运行中停止保持一致地收尾，
                # 否则会留下"已停止但没有结束时间、条目仍待投递"的半截记录。
                self._finalize_early_stop(session, task)
                return
            task.status = TASK_STATUS_RUNNING
            task.started_at = utcnow()
            task.current_step = STEP_OPENING
            session.commit()
            if task.kind == TASK_KIND_COLLECT:
                self._run_collect(session, task)
            else:
                self._run_apply(session, task)
        except TaskStopped:
            self._finalize(session, task, TASK_STATUS_STOPPED, STOP_REASON_USER)
        except Exception:  # noqa: BLE001 - 工作线程异常必须兜底，绝不能静默丢失
            logger.exception("投递/采集任务执行发生内部错误 task_id=%s", task_id)
            self._finalize(
                session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message="任务执行发生内部错误，请查看后端日志"
            )
        finally:
            session.close()  # 工作线程自关会话
            with self._lock:
                self._current_task_id = None
                self._thread = None
            self._stop.clear()
            self._resume.set()

    # ===== 投递批次 =====

    def _run_apply(self, session: Any, task: ApplyTask) -> None:
        from . import apply_service

        config = self._load_config(task, ApplyConfigIn)
        items = (
            session.query(ApplyTaskItem)
            .filter(ApplyTaskItem.task_id == task.id)
            .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
            .all()
        )
        try:
            client = self._make_client(config)
        except Exception as exc:  # noqa: BLE001 - 连不上浏览器是可直接展示的失败
            self._finalize(
                session,
                task,
                TASK_STATUS_FAILED,
                STOP_REASON_ERROR,
                message=str(exc) or "无法连接投递专用浏览器，请先在投递台启动浏览器",
            )
            return

        wrapped = StopAwareCdpClient(client, self._checkpoint)
        registry = self._registry or get_registry()
        consecutive = 0
        try:
            for index, item in enumerate(items):
                try:
                    self._checkpoint()
                    if apply_service.daily_success_count(session) >= config.daily_limit:
                        self._stop_remaining(
                            session,
                            task,
                            items,
                            index,
                            reason=STOP_REASON_DONE,
                            message=f"今日投递已达上限（{config.daily_limit}），剩余岗位已跳过",
                        )
                        return
                    item.status = ITEM_STATUS_RUNNING
                    item.attempt += 1
                    item.started_at = utcnow()
                    task.current_step = STEP_OPENING
                    session.commit()
                    self._execute_item(session, task, item, config, wrapped, registry, apply_service)
                except TaskStopped:
                    item.status = ITEM_STATUS_SKIPPED
                    item.failure_detail = "用户停止了任务，当前岗位未完成"
                    item.finished_at = utcnow()
                    task.skipped += 1
                    session.commit()
                    self._stop_remaining(session, task, items, index + 1, reason=STOP_REASON_USER, message="")
                    return
                except _ItemSkip as exc:
                    item.status = ITEM_STATUS_SKIPPED
                    item.failure_detail = str(exc)
                    item.finished_at = utcnow()
                    task.processed += 1
                    task.skipped += 1
                    session.commit()
                except SiteFailure as exc:
                    self._mark_failed(session, task, item, exc.category, exc.detail)
                    consecutive += 1
                except CdpError as exc:
                    self._mark_failed(session, task, item, FAILURE_NETWORK_TIMEOUT, str(exc))
                    consecutive += 1
                except Exception:  # noqa: BLE001 - 单岗位异常不能打死整个批次
                    logger.exception("投递单个岗位失败 task_id=%s item_id=%s", task.id, item.id)
                    self._mark_failed(
                        session, task, item, FAILURE_UNKNOWN, "投递时发生内部错误，请查看后端日志"
                    )
                    consecutive += 1
                else:
                    item.status = ITEM_STATUS_SUCCESS
                    item.finished_at = utcnow()
                    task.processed += 1
                    task.succeeded += 1
                    session.commit()
                    consecutive = 0
                    apply_service.write_back_job_status(session, item.job_id)
                    apply_service.mark_queue_done(session, item.job_id)
                    # 投出去的岗位要在「求职进度」里也落一条「已投递」，否则用户还得手工
                    # 把刚投的岗位再录一遍。用条目上的快照字段，岗位被删掉也记得住。
                    tracker.record_applied(
                        session,
                        company=item.company,
                        title=item.job_title,
                        job_id=item.job_id,
                    )
                    session.commit()

                if item.status == ITEM_STATUS_FAILED:
                    if item.failure_category == FAILURE_CAPTCHA_REQUIRED:
                        self._pause_with_message(
                            session,
                            task,
                            "站点出现验证码或安全验证：请在浏览器窗口里完成验证后点击「继续」",
                        )
                        if not self._wait_resume_or_stop():
                            raise TaskStopped()
                        consecutive = 0
                    elif consecutive >= config.breaker_threshold:
                        self._breaker_pause(session, task, consecutive)
                        if not self._wait_resume_or_stop():
                            raise TaskStopped()
                        consecutive = 0

                if index < len(items) - 1 and not self._interruptible_sleep(
                    config.interval_seconds, config.interval_jitter_seconds
                ):
                    raise TaskStopped()

            task.current_step = STEP_IDLE
            task.status = TASK_STATUS_COMPLETED
            task.stop_reason = STOP_REASON_DONE
            task.finished_at = utcnow()
            task.message = task.message or "投递任务已完成"
            session.commit()
        except TaskStopped:
            self._stop_remaining(session, task, items, 0, reason=STOP_REASON_USER, message="")
        finally:
            client.close()

    def _execute_item(
        self,
        session: Any,
        task: ApplyTask,
        item: ApplyTaskItem,
        config: ApplyConfigIn,
        client: CdpClient,
        registry: Any,
        apply_service: Any,
    ) -> None:
        job = session.get(Job, item.job_id) if item.job_id else None
        if job is None:
            raise _ItemSkip("岗位已被删除，跳过该条目")
        resume = apply_service.resolve_resume(session, job.id, item.resume_id)
        if resume is None:
            raise _ItemSkip("未找到可用简历：请先在简历中心为该岗位生成简历后再投递")
        adapter = registry.for_job(job)
        data = apply_service.build_apply_data(session, resume)
        greeting = (item.greeting or "").strip() or config.default_greeting

        task.current_step = STEP_FILLING
        session.commit()
        adapter.open_apply(client, job)
        task.current_step = STEP_SUBMITTING
        session.commit()
        outcome = adapter.fill_and_submit(client, data, greeting)
        task.current_step = STEP_VERIFYING
        session.commit()
        if not outcome.success:
            raise SiteFailure(FAILURE_UNKNOWN, "未能确认投递成功，请在浏览器中核对")
        if outcome.greeting_sent:
            item.greeting = outcome.greeting_sent

    # ===== 采集批次 =====

    def _run_collect(self, session: Any, task: ApplyTask) -> None:
        # 「补齐详情」把「这一批岗位从哪儿来」写在 task.config 的 backfill_job_ids 里。它是一次性
        # 的目标清单，不是采集参数，所以刻意不放进 CollectConfigIn——否则公开的「采集配置」接口
        # 也会接受并回显一个很快过期的 id 列表。代价是 CollectConfigIn 是 extra="forbid" 的，
        # 必须先剔除再还原，否则会静默退回默认值、把用户设的限速一起丢掉（见 _load_config）。
        backfill_job_ids = self._backfill_job_ids(task)
        # ``save_site_samples`` 同样是"只属于这次任务"的一次性键（见 _load_config 的 ignore）。
        # 为真才安装录制装饰器；为假时连目录都不创建、一个文件都不写。
        save_site_samples = bool((task.config or {}).get("save_site_samples"))
        config = self._load_config(
            task, CollectConfigIn, ignore=("backfill_job_ids", "save_site_samples")
        )
        registry = self._registry or get_registry()
        # 记录本次采集所属的站点：站点健康度要按站点归因，不写它事后无法把失败/详情缺失归到
        # 具体站点（这就是"静默失败"的根因之一）。取不到就留空串，**不**回退到"注册表第一个
        # 站点"——那是编造默认站点，会把别站点的问题算到它头上。（不新增数据库列，与
        # ``unmapped_conditions`` 同一套做法。）
        site_key = self._collect_site_key(session)
        task.config = {**(task.config or {}), "site_key": site_key}
        session.commit()
        adapter = self._collect_adapter(session, registry)
        if adapter is None:
            self._record_failure_category(task, FAILURE_UNKNOWN)
            self._finalize(session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message="没有可用的采集适配器")
            return
        try:
            client = self._make_client(config)
        except Exception as exc:  # noqa: BLE001
            self._record_failure_category(task, FAILURE_UNKNOWN)
            self._finalize(
                session,
                task,
                TASK_STATUS_FAILED,
                STOP_REASON_ERROR,
                message=str(exc) or "无法连接投递专用浏览器，请先在投递台启动浏览器",
            )
            return

        wrapped = StopAwareCdpClient(client, self._checkpoint)
        # 记录站点原文：套在停止守卫**之外**，这样适配器仍然通过同一个 client 取响应体，
        # 录制器只在旁边观察（配对 url/body 并落盘）。要保存哪些接口由**站点适配器**声明
        # （``sample_markers``），录制器本身不含任何站点常量；适配器没声明就什么都不存。
        recorder: SampleRecordingCdpClient | None = None
        markers = tuple(getattr(adapter, "sample_markers", ()) or ())
        if save_site_samples and markers:
            # 目录一律用**已解析适配器**的 key（代码常量，如 "boss"），**不用**配置里的 site_key：
            # 后者是用户输入、schema 未限制字符集，可含 ".." 之类；用它拼路径会把样例写出
            # captures 之外（例如投递浏览器的登录态目录 browser-profile），破坏"只写 captures"这条底线。
            # adapter 在这里必然存在（取不到适配器时采集早已失败返回，走不到这一步）。
            captures_root = captures_dir()
            target_dir = captures_root / (adapter.key or "unknown")
            # 再把底线做成**代码级检查**而不是假设：以后谁改回用 site_key、或换个拼法，
            # 越界的目录都会被这里挡住，而不是悄悄写到别处。
            if _is_within(target_dir, captures_root):
                recorder = SampleRecordingCdpClient(
                    wrapped, markers=markers, directory=target_dir
                )
                wrapped = recorder
            else:
                # 落盘是旁路能力，绝不能因为路径异常把采集本身弄坏：不保存、只记日志。
                logger.warning("站点样例目录不在 captures 之内，已跳过保存：%s", target_dir)
        try:
            Collector().run(
                session=session,
                task=task,
                client=wrapped,
                adapter=adapter,
                config=config,
                checkpoint=self._checkpoint,
                sleeper=self._sleeper,
                clock=self._clock,
                backfill_job_ids=backfill_job_ids or None,
            )
        except TaskStopped:
            # 停止路径也要落"保存了几份 / 存哪了"的账目：用户点了停止后同样想知道样例在哪，
            # 不写等于把已经存下来的样例藏起来（上一次交付刚因为"停止时账目没写"修过一处）。
            self._record_sample_result(task, recorder)
            self._stop_remaining(session, task, [], 0, reason=STOP_REASON_USER, message="")
            return
        except SiteFailure as exc:
            # 真正"抓不到"（页面没 load 好 / 选择器失效 / 需登录）时**必须失败**，并原样带上
            # 可操作诊断——绝不能像以前那样把"什么都没做"伪装成"采集完成，共新增 0 个岗位"。
            # 同时把**失败分类**一并落进 config：message 是给用户看的，分类是给站点健康度用的
            # ——它靠 ``selector_invalid`` 区分"站点改版"与"环境/用户侧"（需登录、验证码、超时）。
            self._record_failure_category(task, exc.category)
            self._finalize(
                session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message=f"采集失败：{exc.detail}"
            )
            self._record_sample_result(task, recorder)
            session.commit()
            return
        except CdpError as exc:
            self._record_failure_category(task, FAILURE_UNKNOWN)
            self._finalize(
                session, task, TASK_STATUS_FAILED, STOP_REASON_ERROR, message=f"采集失败：{exc}"
            )
            self._record_sample_result(task, recorder)
            session.commit()
            return
        finally:
            client.close()

        task.status = TASK_STATUS_COMPLETED
        task.stop_reason = STOP_REASON_DONE
        task.current_step = STEP_IDLE
        task.finished_at = utcnow()
        task.message = task.message or self._collect_message(task)
        self._record_sample_result(task, recorder)
        session.commit()

    def _collect_adapter(self, session: Any, registry: Any) -> Any:
        """按"当前站点"取采集适配器；取不到就回退注册表里的第一个。

        站点优先从投递配置的 ``site_key`` 解析——这样界面选了哪个站点，采集就用哪个；
        配置读不出（尚未保存过 / 数据损坏）时回退，保证依旧能跑。
        """
        adapters = registry.all()
        if not adapters:
            return None

        site_key = self._collect_site_key(session)
        if site_key:
            adapter = registry.resolve(site_key)
            if adapter is not None:
                return adapter
        return adapters[0]

    @staticmethod
    def _collect_site_key(session: Any) -> str:
        """读取当前配置里的采集站点 key；读不出（未保存 / 数据损坏）时返回空串。

        刻意**不**回退到"注册表第一个站点"：站点健康度按站点归因，编造一个默认站点会把
        别站点的问题算到它头上（也违反"不要编造默认站点"）。这里只取用户实际选中的那个。
        """
        from . import apply_service

        try:
            return apply_service.get_apply_config(session).site_key or ""
        except Exception:  # noqa: BLE001 - 配置读取失败不该阻断采集
            logger.warning("读取当前站点配置失败（站点标识留空）", exc_info=True)
            return ""

    @staticmethod
    def _record_failure_category(task: ApplyTask, category: str) -> None:
        """把采集失败分类写进 ``task.config``（不新增数据库列）。

        分类取不到（非 ``SiteFailure`` 的失败路径）时落 ``FAILURE_UNKNOWN``，绝不留空——
        站点健康度要靠它区分"站点改版"与"环境/用户侧"，留空会让前端去猜。
        """
        task.config = {**(task.config or {}), "failure_category": category or FAILURE_UNKNOWN}

    @staticmethod
    def _record_sample_result(task: ApplyTask, recorder: SampleRecordingCdpClient | None) -> None:
        """把"保存了几份站点原文、在哪个目录"写进 ``task.config`` 与任务文案。

        只在本次真的开启了保存（``recorder`` 不为 None）时才写——关闭时不留任何痕迹，
        与"为假就不创建目录、不写文件"一致。**停止 / 失败路径同样要写**：用户点了停止后
        同样想知道样例存哪了，不写等于把已经存下来的样例藏起来。
        """
        if recorder is None:
            return
        saved = int(recorder.saved_count)
        directory = str(recorder.directory)
        task.config = {**(task.config or {}), "saved_samples": saved, "samples_dir": directory}
        if saved:
            note = f"（已保存 {saved} 份站点原文，可在 {directory} 查看）"
        else:
            note = f"（本次未保存站点原文，目录 {directory}）"
        task.message = f"{task.message or ''}{note}"

    @staticmethod
    def _collect_message(task: ApplyTask) -> str:
        """区分几种收尾，让用户一眼看懂发生了什么、**以及下一步点哪里**。

        - 有暂存 → 已暂存 N 个岗位，并明确指出「下一步去哪个面板挑」；
        - 有筛掉 → 说清"筛掉了几个、因为什么"，不给用户留下"怎么少了"的疑惑；
        - 条件没被识别 → 明确说"这条筛选本次没有生效"（**绝不静默**）；
        - 一个没暂存、但**跳过了重复**（整页岗位都已存在）→ 明确说"都已存在、没有新增"，
          绝不能把"都是重复"误述成"没搜到"；
        - 真的一条都没搜到 → 才是"没有找到匹配的岗位（关键词或城市可能太窄）"。

        用户反馈过"采集完只知道成功了，不知道下一步该做什么"——所以这句话不只是汇报结果，
        还得给出下一个动作。措辞里的面板名要与界面上的标题一致。
        """
        config = task.config or {}
        # 「补齐详情」是采集的另一个模式：这批岗位由用户点名、只补 JD，不进暂存区。它"发生了什么"
        # 与搜索采集完全不同，所以走另一套文案——否则会冒出"已暂存 0 个岗位"这种驴唇不对马嘴的说法。
        if "backfill_job_ids" in config:
            return TaskRunner._backfill_message(config)
        succeeded = int(task.succeeded or 0)
        skipped = int(task.skipped or 0)
        filtered = int(config.get("filtered_out") or 0)
        unapplied = config.get("filter_unapplied") or []

        if succeeded > 0:
            parts = [f"采集完成：已暂存 {succeeded} 个岗位。"]
            if filtered:
                parts.append(f"另有 {filtered} 个不符合你填的筛选条件，已筛掉。")
            if unapplied:
                parts.append(
                    f"注意：{'、'.join(str(item) for item in unapplied)} "
                    "这条筛选条件没能识别，本次没有生效。"
                )
            parts.append(
                "在下方「本次采集结果」里勾选要收进岗位广场的岗位，再点「导入选中的岗位」。"
            )
            return "".join(parts)
        if filtered and not skipped:
            # 采到了、但全被筛掉——这与"没搜到"是两回事，说成后者会让用户去改关键词。
            return (
                f"采集到的 {filtered} 个岗位都不符合你填的筛选条件（学历 / 经验 / 薪资），已全部筛掉。"
                "把条件放宽一些再试。"
            )
        if skipped > 0:
            message = f"本次采集到的岗位都已存在，没有新增（跳过 {skipped} 个重复岗位）"
            trashed = int(config.get("skipped_trashed") or 0)
            if trashed:
                # "你之前删过它"和"早就在库里了"是两件事，说清楚才不会让人以为删除没生效。
                message += (
                    f"。其中 {trashed} 条在岗位广场的「回收站」里"
                    "——想重新收进来，先去「回收站」恢复或彻底删除它"
                )
            return message
        return "采集完成：没有找到匹配的岗位（关键词或城市可能太窄），请调整后重试"

    @staticmethod
    def _backfill_message(config: dict[str, Any]) -> str:
        """「补齐详情」的收尾文案：补到几条、跳过几条，一条没补上时也要说清为什么。

        用户点这次操作就是为了把空的 JD 补上，所以"完成"两个字本身没有信息量：没补到时必须如实
        说明（已有描述 / 仍然抓不到 / 已在回收站里都会计进跳过），否则他会以为补上了。
        """
        backfilled = int(config.get("backfilled") or 0)
        skipped = int(config.get("backfill_skipped") or 0)
        if backfilled > 0:
            message = f"已为 {backfilled} 条岗位补齐职位描述。"
            if skipped:
                message += f"另有 {skipped} 条跳过（已有描述 / 仍然抓不到 / 已在回收站里）。"
            return message
        if skipped:
            return (
                f"没有补到新的职位描述：{skipped} 条岗位已跳过"
                "（已有描述 / 仍然抓不到 / 已在回收站里）。"
                "若这些岗位在浏览器里确实打不开，请确认岗位仍然在线后重试。"
            )
        return "没有补到新的职位描述：所选岗位都已无可补充的内容。"

    # ===== 信号检查 =====

    def _checkpoint(self) -> None:
        """步骤之间检查信号：停止则抛 ``TaskStopped``，暂停则阻塞等待。"""
        while not self._resume.is_set():
            if self._stop.is_set():
                raise TaskStopped()
            self._resume.wait(timeout=self._poll)
        if self._stop.is_set():
            raise TaskStopped()

    def _wait_resume_or_stop(self) -> bool:
        """阻塞直到恢复运行；返回 False 表示期间用户点了停止。"""
        while not self._resume.wait(timeout=self._poll):
            if self._stop.is_set():
                return False
        return not self._stop.is_set()

    def _interruptible_sleep(self, interval: int, jitter: int) -> bool:
        total = max(0, interval)
        if jitter:
            total += random.uniform(0, jitter)
        if total <= 0:
            return True
        end = self._clock() + total
        while True:
            if self._stop.is_set():
                return False
            if not self._resume.is_set() and not self._wait_resume_or_stop():
                return False
            remaining = end - self._clock()
            if remaining <= 0:
                return True
            self._sleeper(min(0.2, remaining))

    # ===== 状态写入 =====

    def _mark_failed(
        self, session: Any, task: ApplyTask, item: ApplyTaskItem, category: str, detail: str
    ) -> None:
        item.status = ITEM_STATUS_FAILED
        item.failure_category = category
        item.failure_detail = detail
        item.finished_at = utcnow()
        task.processed += 1
        task.failed += 1
        session.commit()

    def _pause_with_message(self, session: Any, task: ApplyTask, message: str) -> None:
        self._resume.clear()
        task.status = TASK_STATUS_PAUSED
        task.message = message
        session.commit()

    def _breaker_pause(self, session: Any, task: ApplyTask, count: int) -> None:
        self._resume.clear()
        task.status = TASK_STATUS_BREAKER_PAUSED
        task.stop_reason = STOP_REASON_BREAKER
        task.message = f"已因连续 {count} 次失败自动暂停，请查看记录并处理后点击「继续」"
        session.commit()

    def _stop_remaining(
        self,
        session: Any,
        task: ApplyTask,
        items: list[ApplyTaskItem],
        start_index: int,
        *,
        reason: str,
        message: str,
    ) -> None:
        for item in items[start_index:]:
            if item.status == ITEM_STATUS_PENDING:
                item.status = ITEM_STATUS_SKIPPED
                item.finished_at = utcnow()
                task.skipped += 1
        task.status = TASK_STATUS_STOPPED
        task.stop_reason = reason
        task.current_step = STEP_IDLE
        task.finished_at = utcnow()
        if message:
            task.message = message
        session.commit()

    def _finalize_early_stop(self, session: Any, task: ApplyTask) -> None:
        """工作线程尚未开始就收到停止信号时的收尾（与运行中停止同一形态）。

        直接复用 ``_stop_remaining``：写 ``finished_at``、把未处理条目标为 ``skipped``，并落
        ``stopped / user``。采集批次没有 ``apply_task_item`` 条目，此时仅收尾任务本身，行为与
        ``_run_collect`` 的停止路径一致。
        """
        items = (
            session.query(ApplyTaskItem)
            .filter(ApplyTaskItem.task_id == task.id)
            .order_by(ApplyTaskItem.sort_order, ApplyTaskItem.id)
            .all()
        )
        self._stop_remaining(session, task, items, 0, reason=STOP_REASON_USER, message="")

    def _finalize(
        self, session: Any, task: ApplyTask | None, status: str, reason: str, message: str = ""
    ) -> None:
        if task is None:
            return
        task.status = status
        task.stop_reason = reason
        task.current_step = STEP_IDLE
        task.finished_at = utcnow()
        if message:
            task.message = message
        session.commit()

    def _set_status(self, task_id: int, status: str, reason: str = "") -> None:
        """在控制接口里即时落一次状态，让界面立刻看到"已暂停/已停止"。

        **终态只读，且必须原子**：``pause()`` / ``resume()`` / ``stop()`` 与工作线程并发写
        同一行。工作线程可能在这一瞬间跑完并提交了终态（``completed`` / ``stopped`` /
        ``failed``）。若这里先 ``SELECT`` 判断再 ``UPDATE``，两步之间就存在一个窗口——
        工作线程的终态提交恰好落在窗口里，随后这次**盲写**会把终态盖回活动态；工作线程已退出，
        再没有人会修正它，任务于是永久卡在 ``running``（违反"暂停可恢复"）。

        因此这里不做"读—判—写"，而是把守卫直接写进 ``WHERE``：只有当**当前仍是活动态**且
        与目标不同才更新。整条 ``UPDATE`` 由数据库原子执行，与工作线程的提交严格串行——
        谁先提交谁生效：控制写在前会被工作线程的终态覆盖，控制写在后则因 ``WHERE`` 不成立
        而彻底不生效。无论如何终态都不会被活动态回写覆盖。

        守卫只加在**控制接口的这条回写路径**上；工作线程自己的提交路径
        （``_finalize`` / ``_stop_remaining`` / ``_finalize_early_stop``）不经此方法，始终
        保有写终态的能力，故不受影响。
        """
        session = self._session_factory()
        try:
            values: dict[str, Any] = {"status": status}
            if reason:
                values["stop_reason"] = reason
            statement = (
                update(ApplyTask)
                .where(ApplyTask.id == task_id)
                .where(ApplyTask.status.notin_(_TERMINAL_STATUSES))
                .where(ApplyTask.status != status)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            result = session.execute(statement)
            changed = result.rowcount or 0
            session.commit()
            if changed == 0:
                # 没改动：可能是任务已是终态（被拒绝），也可能目标状态与现状相同。读一次只为
                # 留下可检索的日志，不参与写入决策。
                current = session.get(ApplyTask, task_id)
                if current is not None and current.status in _TERMINAL_STATUSES:
                    logger.warning(
                        "拒绝把终态任务改回活动态：task_id=%s 当前状态=%s 目标状态=%s（工作线程已提交终态，控制接口回写让位）",
                        task_id,
                        current.status,
                        status,
                    )
        except Exception:  # noqa: BLE001 - 与工作线程并发写时可能短暂锁库，忽略即可
            logger.warning("更新任务状态失败 task_id=%s", task_id)
        finally:
            session.close()

    # ===== 依赖装配 =====

    def _make_client(self, config: Any) -> CdpClient:
        if self._client_factory is not None:
            return self._client_factory(config)
        from . import apply_service

        session = self._session_factory()
        try:
            manager = apply_service.get_browser_manager(session)
            return manager.client()
        finally:
            session.close()

    @staticmethod
    def _load_config(task: ApplyTask, model: type, *, ignore: Sequence[str] = ()) -> Any:
        """从 ``task.config`` 还原配置模型；``ignore`` 里的键在还原前剔除。

        为什么需要 ``ignore``：配置模型是 ``extra="forbid"`` 的，而任务快照里可能带着**只属于
        这次任务、不属于该配置**的编排字段（如补详情的 ``backfill_job_ids``）。若不剔除，
        ``model_validate`` 会抛 ``ValidationError``，下面那条兜底会**静默退回全默认值**——把用户
        设的限速一起丢掉，而且不会报错。剔除后这类键既不会污染公开的配置接口，也不会误伤还原。
        """
        raw = task.config or {}
        if ignore:
            raw = {key: value for key, value in raw.items() if key not in ignore}
        try:
            return model.model_validate(raw)
        except ValidationError:
            logger.warning("任务配置快照损坏，已退回默认值 task_id=%s", task.id)
            return model()

    @staticmethod
    def _backfill_job_ids(task: ApplyTask) -> list[int]:
        """读出「补齐详情」模式的目标岗位 id；非补详情任务返回空列表。

        对值做一次宽松的 int 归一：配置快照可能被外部改坏，一个坏值不该让整个批次崩掉——
        真正"该不该补"的判断在采集器的 ``_backfill`` 里，这里只负责把 id 取出来。
        """
        raw = (task.config or {}).get("backfill_job_ids")
        if not isinstance(raw, list):
            return []
        ids: list[int] = []
        for value in raw:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        return ids


_RUNNER: TaskRunner | None = None
_RUNNER_LOCK = threading.Lock()


def get_task_runner() -> TaskRunner:
    """进程内共享的运行器单例。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = TaskRunner()
        return _RUNNER


def reset_task_runner() -> None:
    """测试用：释放单例，避免用例之间共享线程状态。"""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
        _RUNNER = None


__all__ = [
    "StopAwareCdpClient",
    "TaskRunner",
    "TaskRunnerError",
    "TaskStopped",
    "get_task_runner",
    "reset_task_runner",
]
