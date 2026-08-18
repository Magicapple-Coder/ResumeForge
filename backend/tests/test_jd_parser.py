"""JD 解析规则测试。"""
from app.services.jd_parser import parse_jd

SAMPLE_JD = """
职位：后端开发工程师
1. 本科及以上学历，计算机相关专业，3年以上开发经验；
2. 熟练掌握 Python 和 Java，了解 Go；
3. 熟悉 MySQL、Redis，有 Kafka 使用经验；
4. 了解微服务架构与分布式系统，熟悉 Linux；
5. 具备良好的数据结构与算法基础。
"""


def test_parse_jd_extracts_skills():
    result = parse_jd(SAMPLE_JD)
    names = {tag.name for tag in result["skills"]}
    assert {"Python", "Java", "Go", "MySQL", "Redis", "Kafka"} <= names
    assert "React" not in names  # 未出现的技能不应误报


def test_parse_jd_extracts_degree_and_years():
    result = parse_jd(SAMPLE_JD)
    assert result["degree"] == "本科"
    assert result["min_years"] == 3


def test_parse_jd_handles_empty_and_garbage():
    assert parse_jd("") == {"skills": [], "degree": "", "min_years": None}
    assert parse_jd(None) == {"skills": [], "degree": "", "min_years": None}
    result = parse_jd("！！!@#￥%……&*")
    assert result["skills"] == []


def test_parse_jd_dedupes_skills_case_insensitive():
    result = parse_jd("熟悉 python 和 Python")
    names = [tag.name for tag in result["skills"]]
    assert names.count("Python") == 1


def test_parse_jd_matches_english_skill_next_to_chinese_text():
    result = parse_jd("熟练掌握JavaScript等语言，使用Python开发")
    names = {tag.name for tag in result["skills"]}
    assert {"JavaScript", "Python"} <= names


def test_parse_jd_takes_highest_degree_and_lowest_years():
    result = parse_jd("硕士及以上，博士优先；5年以上经验，3年以上亦可")
    assert result["degree"] == "博士"
    assert result["min_years"] == 3
