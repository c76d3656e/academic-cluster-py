"""
文本处理工具

实现 BM25 检索、相似度计算、关键词提取等文本处理功能。
"""

import math
import re
from collections import Counter

import structlog

logger = structlog.get_logger()


# =============================================================================
# BM25 检索
# =============================================================================


class BM25:
    """
    BM25 文本检索算法

    简化实现，用于学术论文检索。
    生产环境建议使用 rank_bm25 或 tantivy。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = []
        self.doc_freqs = {}
        self.doc_lens = []
        self.avg_doc_len = 0
        self.n_docs = 0

    def _tokenize(self, text: str) -> list[str]:
        """简单分词"""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        return text.split()

    def fit(self, corpus: list[str]):
        """
        拟合语料库

        Args:
            corpus: 文档列表
        """
        self.corpus = [self._tokenize(doc) for doc in corpus]
        self.n_docs = len(self.corpus)

        # 计算文档长度
        self.doc_lens = [len(doc) for doc in self.corpus]
        self.avg_doc_len = sum(self.doc_lens) / self.n_docs if self.n_docs > 0 else 0

        # 计算文档频率
        self.doc_freqs = Counter()
        for doc in self.corpus:
            unique_terms = set(doc)
            for term in unique_terms:
                self.doc_freqs[term] += 1

    def score(self, query: str, doc_idx: int) -> float:
        """计算查询与文档的 BM25 分数"""
        query_terms = self._tokenize(query)
        doc = self.corpus[doc_idx]
        doc_len = self.doc_lens[doc_idx]

        score = 0.0
        doc_term_freq = Counter(doc)

        for term in query_terms:
            if term not in self.doc_freqs:
                continue

            # IDF
            df = self.doc_freqs[term]
            idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1)

            # TF
            tf = doc_term_freq.get(term, 0)
            tf_norm = (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
            )

            score += idf * tf_norm

        return score

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """
        搜索最相关的文档

        Args:
            query: 查询文本
            top_k: 返回前 K 个结果

        Returns:
            [(doc_index, score), ...]
        """
        scores = [(i, self.score(query, i)) for i in range(self.n_docs)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


async def bm25_search(
    query: str,
    documents: list[dict],
    top_k: int = 100,
) -> list[dict]:
    """
    BM25 搜索接口

    Args:
        query: 搜索查询
        documents: 文档列表，每个包含 id, title, abstract
        top_k: 返回前 K 个结果

    Returns:
        排序后的文档列表
    """
    # 构建文档文本
    corpus = [f"{doc.get('title', '')} {doc.get('abstract', '')}" for doc in documents]

    # 创建 BM25 实例并搜索
    bm25 = BM25()
    bm25.fit(corpus)
    results = bm25.search(query, top_k=top_k)

    # 返回排序后的文档
    sorted_docs = []
    for idx, score in results:
        doc = documents[idx].copy()
        doc["bm25_score"] = score
        sorted_docs.append(doc)

    logger.info(
        "BM25 search completed",
        query=query,
        total_docs=len(documents),
        results=len(sorted_docs),
    )

    return sorted_docs


# =============================================================================
# 相似度计算
# =============================================================================


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """计算余弦相似度"""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


async def compute_similarity(
    embedding_a: list[float],
    embedding_b: list[float],
) -> float:
    """计算两个嵌入向量的相似度"""
    return cosine_similarity(embedding_a, embedding_b)


# =============================================================================
# 关键词提取
# =============================================================================


def extract_keywords_tfidf(
    documents: list[str],
    top_k: int = 10,
) -> list[str]:
    """
    使用 TF-IDF 提取关键词

    Args:
        documents: 文档列表
        top_k: 返回前 K 个关键词

    Returns:
        关键词列表
    """
    # 分词
    tokenized_docs = [re.sub(r"[^\w\s]", " ", doc.lower()).split() for doc in documents]

    # 计算 TF
    tf = Counter()
    for doc in tokenized_docs:
        tf.update(doc)

    # 计算 IDF
    n_docs = len(tokenized_docs)
    doc_freq = Counter()
    for doc in tokenized_docs:
        for term in set(doc):
            doc_freq[term] += 1

    # 计算 TF-IDF
    tfidf = {}
    for term, freq in tf.items():
        idf = math.log(n_docs / (doc_freq[term] + 1)) + 1
        tfidf[term] = freq * idf

    # 排序并返回
    sorted_terms = sorted(tfidf.items(), key=lambda x: x[1], reverse=True)

    # 过滤停用词
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "if",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
    }

    keywords = [
        term for term, _ in sorted_terms if term not in stop_words and len(term) > 2
    ]

    return keywords[:top_k]


async def extract_keywords(
    text: str,
    top_k: int = 10,
) -> list[str]:
    """提取文本关键词"""
    return extract_keywords_tfidf([text], top_k=top_k)
