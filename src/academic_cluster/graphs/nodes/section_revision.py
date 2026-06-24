"""
章节修订节点 - 修订无效引用（对齐 Rust 版 section_revision.rs）

1. 校验引用有效性（validate_citations）
2. LLM 辅助重写含无效引用的句子
3. 移除剩余无效引用（strip_invalid_citations）
4. 重编号引用（renumber_citations_by_first_use）
5. 重新组装综述
"""

import contextlib
import re
import traceback
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...services.citation_utils import (
    render_reference_list,
    renumber_citations_by_first_use,
    strip_invalid_citations,
    validate_citations,
)
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

# 对齐 Rust 版 CITATION_REVISION_ATTEMPT_LIMIT
_MAX_LLM_REVISION_ATTEMPTS = 1


def _find_sentences_with_invalid_citations(
    content: str,
    invalid_numbers: set[int],
) -> list[dict[str, Any]]:
    """
    找出包含无效引用的句子（对齐 Rust 版 citation_verifier）。

    返回 [{"sentence": str, "invalid_refs": set[int], "start": int, "end": int}]
    """
    results = []
    sentences = re.split(r"(?<=[。！？；\n])", content)
    offset = 0
    for sentence in sentences:
        sentence_stripped = sentence.strip()
        if not sentence_stripped:
            offset += len(sentence)
            continue

        # 找出该句子中的引用
        refs_in_sentence = set()
        for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", sentence_stripped):
            for num_str in match.group(1).split(","):
                with contextlib.suppress(ValueError):
                    refs_in_sentence.add(int(num_str.strip()))

        # 检查是否包含无效引用
        invalid_in_sentence = refs_in_sentence & invalid_numbers
        if invalid_in_sentence:
            results.append(
                {
                    "sentence": sentence_stripped,
                    "invalid_refs": invalid_in_sentence,
                    "start": offset,
                    "end": offset + len(sentence),
                }
            )

        offset += len(sentence)

    return results


async def _llm_rewrite_invalid_sentences(
    section_content: str,
    invalid_sentences: list[dict[str, Any]],
    valid_references: str,
    topic: str,
) -> str:
    """
    使用 LLM 重写含无效引用的句子（对齐 Rust 版 revise_invalid_section_citations）。

    将无效引用替换为有效引用，或改写为不需要该引用的表述。
    """
    from ...services.llm_client import ainvoke_with_callbacks, create_llm

    if not invalid_sentences:
        return section_content

    # 构建需要修订的句子列表
    sentences_to_fix = []
    for i, item in enumerate(invalid_sentences[:10], 1):
        sentences_to_fix.append(
            f'{i}. "{item["sentence"]}" — 包含无效引用 {item["invalid_refs"]}'
        )

    prompt = f"""你是一位学术综述修订专家。以下综述章节中有些句子引用了不存在的参考文献编号。
请修订这些句子，用有效的参考文献替换无效引用，或者改写句子使其不再需要该引用。

## 研究主题
{topic}

## 无效引用句子
{chr(10).join(sentences_to_fix)}

## 有效的参考文献（只能引用这些）
{valid_references}

## 修订要求
1. 只修订列出的句子，不要修改其他内容
2. 优先用有效参考文献替换无效引用
3. 如果找不到合适的替代文献，改写句子使论断更泛化或加入"据报道"等弱化表述
4. 保持学术中文风格
5. 输出修订后的完整章节（不只是修订的句子）

## 输出格式
输出修订后的完整章节正文。"""

    try:
        llm = create_llm(temperature=0.3, max_tokens=8192)
        messages = [
            SystemMessage(
                content="你是一位学术综述修订专家。只输出修订后的章节正文，不要解释。"
            ),
            HumanMessage(content=prompt),
        ]
        response = await ainvoke_with_callbacks(llm, messages)

        raw_content: Any = response.content
        if isinstance(raw_content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw_content
            )
        else:
            content = str(raw_content)

        # 验证修订后的内容质量：至少保留原始内容的 70%
        if len(content.strip()) < len(section_content.strip()) * 0.7:
            logger.warning(
                "LLM revision too short, falling back to deterministic",
                original_len=len(section_content),
                revised_len=len(content),
            )
            return section_content

        return content.strip()

    except Exception as e:
        logger.warning(
            "LLM revision failed, using deterministic fallback", error=str(e)
        )
        return section_content


async def section_revision_node(state: PipelineState) -> dict[str, Any]:
    """
     章节修订（对齐 Rust 版 section_revision.rs）

     1. 校验每个章节的引用有效性
    2. LLM 辅助重写含无效引用的句子
    3. 确定性移除剩余无效引用
     4. 按首次出现顺序重编号
     5. 重新组装综述 + 参考文献列表
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("section_revision", "compute", index=9)

    logger.info(
        "Starting section revision", invalid_citations=state.invalid_citation_count
    )

    await send_progress(
        state.project_id,
        "section_revision",
        f"章节修订中，处理 {state.invalid_citation_count} 个无效引用...",
    )

    db = get_database()

    try:
        # 引用编号基于全部论文（core + auxiliary），校验时必须用总数
        all_paper_ids = list(
            dict.fromkeys(
                list(state.core_paper_ids or []) + list(state.auxiliary_paper_ids or [])
            )
        )
        valid_paper_count = len(all_paper_ids)

        # 获取已写章节
        written_sections = await db.get_written_sections_by_ids(
            state.written_section_ids
        )
        if not written_sections:
            raise ValueError("No written sections to revise")

        # 获取大纲（用于章节标题）
        outline = state.outline_data or {}
        sections_meta = outline.get("sections", [])

        # 构建有效参考文献上下文（供 LLM 使用）
        papers = await db.get_papers_by_ids(all_paper_ids)
        ref_lines = []
        for i, p in enumerate(papers[:30], 1):
            title = p.get("title", "")
            year = p.get("year", "")
            venue = p.get("journal", p.get("venue", ""))
            ref_lines.append(f"[{i}] {title} ({year}) {venue}")
        valid_references_text = "\n".join(ref_lines)

        # === Step 1: 校验 + LLM 辅助修订 ===
        all_invalid = set()
        revised_contents = []

        for i, section in enumerate(written_sections):
            content = section.get("content", "")

            # 校验引用
            result = validate_citations(content, valid_paper_count)
            if result["invalid_numbers"]:
                all_invalid.update(result["invalid_numbers"])
                logger.warning(
                    "Invalid citations in section",
                    section_index=i,
                    invalid=result["invalid_numbers"],
                )

                # LLM 辅助重写含无效引用的句子
                invalid_sentences = _find_sentences_with_invalid_citations(
                    content, set(result["invalid_numbers"])
                )
                if invalid_sentences:
                    logger.info(
                        "LLM rewriting sentences with invalid citations",
                        section_index=i,
                        sentence_count=len(invalid_sentences),
                    )
                    content = await _llm_rewrite_invalid_sentences(
                        content,
                        invalid_sentences,
                        valid_references_text,
                        state.query,
                    )

                # 确定性移除剩余无效引用
                recheck = validate_citations(content, valid_paper_count)
                if recheck["invalid_numbers"]:
                    content = strip_invalid_citations(
                        content, set(recheck["invalid_numbers"])
                    )

            revised_contents.append(content)

        # === Step 2: 按首次出现顺序重编号 ===
        paper_metadata_map = {}
        for i, p in enumerate(papers):
            authors = p.get("authors", [])
            author_str = ", ".join(a.get("name", "Unknown") for a in authors[:3])
            if len(authors) > 3:
                author_str += " et al."
            paper_metadata_map[i + 1] = {
                "paper_id": p.get("id", ""),
                "title": p.get("title", ""),
                "authors": author_str,
                "venue": p.get("journal", p.get("venue", "")),
                "year": str(p.get("year", "")),
                "doi": p.get("doi", ""),
            }

        # 拼接各章节（带标题）
        review_parts = []
        for i, content in enumerate(revised_contents):
            title = ""
            if i < len(sections_meta):
                title = sections_meta[i].get("title", "")
            if title:
                review_parts.append(f"## {title}\n\n{content}")
            else:
                review_parts.append(content)
        assembled = "\n\n".join(review_parts)

        # 重编号
        final_review, ref_mappings = renumber_citations_by_first_use(
            assembled, paper_metadata_map
        )

        # 生成参考文献列表
        ref_list = render_reference_list(papers, ref_mappings)
        final_review = final_review.rstrip() + "\n\n## References\n\n" + ref_list

        # 更新章节到数据库
        for i, section in enumerate(written_sections):
            section_id = section.get("id")
            if section_id and i < len(revised_contents):
                await db.save_written_section(
                    {
                        "id": section_id,
                        "outline_id": section.get("outline_id"),
                        "section_id": section.get("section_id"),
                        "content": revised_contents[i],
                        "word_count": len(revised_contents[i]),
                    }
                )

        logger.info(
            "Section revision completed",
            sections_revised=len(revised_contents),
            invalid_stripped=len(all_invalid),
            final_references=len(ref_mappings),
            total_chars=len(final_review),
        )

        await send_progress(
            state.project_id,
            "section_revision",
            f"章节修订完成，移除 {len(all_invalid)} 个无效引用",
        )

        result = {
            "final_review": final_review,
            "invalid_citation_count": len(all_invalid),
            "retry_count": (state.retry_count or 0) + 1,
            "status": "revised",
        }
        if tracker:
            await tracker.end_node(
                "section_revision",
                "succeeded",
                output_summary={
                    "sections_revised": len(revised_contents),
                    "invalid_stripped": len(all_invalid),
                },
            )
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node(
                "section_revision",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
        logger.error("Section revision failed", error=str(e))
        raise
