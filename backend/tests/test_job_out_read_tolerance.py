"""岗位读取侧必须容忍"写入时的规则后来变了"的历史数据。

真实故障（2026-09-18）：投递台采集把岗位写进库，`recognition_source` 记为「岗位采集」，
而 `JobOut` 继承 `JobCreate`、把**输入侧的白名单校验**一并带到了读取侧——于是
`GET /api/jobs` 与 `GET /api/stats` 在逐行构造响应时抛 `ValidationError`，整份岗位列表
与首页统计**一起 500**。用户在界面上看到的是"岗位广场空白、首页全部清零、服务器内部
错误"，而库里那条岗位其实完好无损。

一条历史数据不该让整个列表接口挂掉。这里同时钉住三件事：

1. 采集写入的来源是**合法输入**（必须在 `RECOGNITION_SOURCES` 里，否则写入路径自己就先拦住了）；
2. 读取侧对未知来源 / 未知状态 / 超量备注图片**一律如实回显**；
3. 输入侧校验**照旧生效**——修的是读取容错，不是把闸门拆掉。
"""
import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.job import Job
from app.schemas.job import JobCreate, JobOut, RECOGNITION_SOURCES


def _row(**overrides) -> dict:
    base = {
        "id": 1,
        "title": "后端开发",
        "created_at": datetime(2026, 9, 18, 10, 0, 0),
        "updated_at": datetime(2026, 9, 18, 10, 0, 0),
    }
    return {**base, **overrides}


def test_collected_source_is_a_supported_input_source():
    """采集器写入的来源必须同时是合法的输入来源。

    否则写入路径与读取路径对同一份数据各执一词，第一个采集进来的岗位就会把列表打崩。
    """
    from app.services.apply.collector import COLLECT_RECOGNITION_SOURCE

    assert COLLECT_RECOGNITION_SOURCE in RECOGNITION_SOURCES


def test_job_out_echoes_unknown_legacy_values():
    """读取不重跑输入白名单：白名单演进后，库里按旧规则写入的行仍要读得出来。"""
    job = JobOut.model_validate(
        _row(
            recognition_source="岗位采集",
            status="某个已经下线的旧状态",
            note_images=["a", "b", "c", "d"],
        )
    )

    assert job.recognition_source == "岗位采集"
    assert job.status == "某个已经下线的旧状态"
    assert len(job.note_images) == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"recognition_source": "某个未来才有的来源"},
        {"status": "某个已经下线的旧状态"},
        {"note_images": ["a", "b", "c"]},
        {"source_url": "不是地址"},
    ],
)
def test_job_create_still_rejects_unsupported_values(overrides):
    """输入侧的校验不能被这次改动误关掉。"""
    with pytest.raises(ValidationError):
        JobCreate(title="后端开发", **overrides)


def test_list_and_stats_survive_a_collected_job(db_session, client):
    """回归：库里有一条采集来的岗位时，岗位列表与首页统计都必须正常返回。

    这是用户实际看到的故障形态——采集"成功"了 3 个岗位，随后岗位广场空白、首页清零。
    """
    db_session.add(
        Job(
            title="全栈开发工程师",
            company="某某科技",
            recognition_source="岗位采集",
            source_url="https://www.zhipin.com/job_detail/abc.html",
        )
    )
    # 再放一条"按未来才会有的规则写入"的脏数据：读取侧同样不该被它绊倒。
    db_session.add(Job(title="历史遗留岗位", recognition_source="某个未来才有的来源"))
    db_session.commit()

    listed = client.get("/api/jobs")
    assert listed.status_code == 200, listed.text
    titles = [item["title"] for item in listed.json()["items"]]
    assert "全栈开发工程师" in titles
    assert "历史遗留岗位" in titles

    stats = client.get("/api/stats")
    assert stats.status_code == 200, stats.text
    assert stats.json()["latest_jobs"], "首页的最近岗位不该因为来源字段而整块消失"
