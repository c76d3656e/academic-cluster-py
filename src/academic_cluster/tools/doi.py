"""
DOI 解析和标准化工具

DOI (Digital Object Identifier) 是学术论文的唯一标识符。
"""

import re
from typing import Any

# DOI 正则表达式
DOI_PATTERN = re.compile(
    r"(?:doi[:\s]*|https?://doi\.org/|https?://dx\.doi\.org/)?"
    r'(10\.\d{4,9}/[^\s,;}\])"]+)',
    re.IGNORECASE,
)


def extract_doi(text: str) -> str | None:
    """
    从文本中提取 DOI

    支持格式：
    - 10.xxxx/xxxxx
    - doi:10.xxxx/xxxxx
    - https://doi.org/10.xxxx/xxxxx
    - https://dx.doi.org/10.xxxx/xxxxx

    Args:
        text: 包含 DOI 的文本

    Returns:
        标准化的 DOI，如果没有找到返回 None
    """
    if not text:
        return None

    match = DOI_PATTERN.search(text)
    if match:
        return normalize_doi(match.group(1))
    return None


def normalize_doi(doi: str) -> str:
    """
    标准化 DOI 格式

    - 去除前缀 (doi:, https://doi.org/, https://dx.doi.org/)
    - 去除尾部空白和标点
    - 转为小写

    Args:
        doi: 原始 DOI

    Returns:
        标准化后的 DOI
    """
    if not doi:
        return ""

    # 去除前缀
    doi = doi.strip()
    for prefix in [
        "doi:",
        "DOI:",
        "https://doi.org/",
        "https://dx.doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
    ]:
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break

    # 去除尾部空白和标点
    doi = doi.strip().rstrip(".")

    # 转为小写（DOI 不区分大小写）
    doi = doi.lower()

    return doi


def is_valid_doi(doi: str) -> bool:
    """
    验证 DOI 是否有效

    DOI 格式: 10.xxxxx/xxxxx

    Args:
        doi: DOI 字符串

    Returns:
        是否有效
    """
    if not doi:
        return False

    doi = normalize_doi(doi)
    return bool(re.match(r"^10\.\d{4,9}/[^\s]+$", doi))


def doi_to_url(doi: str) -> str:
    """
    将 DOI 转换为 URL

    Args:
        doi: DOI 字符串

    Returns:
        DOI URL
    """
    doi = normalize_doi(doi)
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def get_paper_doi(paper: dict[str, Any]) -> str | None:
    """
    从论文数据中获取 DOI

    优先级：
    1. doi 字段
    2. external_id 中的 DOI
    3. url 中的 DOI

    Args:
        paper: 论文数据字典

    Returns:
        标准化的 DOI，如果没有找到返回 None
    """
    # 1. 直接的 doi 字段
    doi = paper.get("doi")
    if doi:
        normalized = normalize_doi(doi)
        if is_valid_doi(normalized):
            return normalized

    # 2. external_id 中的 DOI
    external_id = paper.get("external_id", "")
    if external_id.startswith("10.") or "doi.org" in external_id:
        doi = extract_doi(external_id)
        if doi:
            return doi

    # 3. url 中的 DOI
    url = paper.get("url", "")
    if "doi.org" in url:
        doi = extract_doi(url)
        if doi:
            return doi

    return None


def get_best_external_id(paper: dict[str, Any]) -> str:
    """
    获取论文的最佳外部 ID

    优先级：
    1. DOI（如果存在且有效）
    2. 源特定的 external_id

    Args:
        paper: 论文数据字典

    Returns:
        最佳外部 ID
    """
    # 优先使用 DOI
    doi = get_paper_doi(paper)
    if doi:
        return doi

    # 回退到源特定 ID
    result: str = str(paper.get("external_id", ""))
    return result
