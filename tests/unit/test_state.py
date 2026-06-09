"""
状态模型单元测试
"""

import pytest

from academic_cluster.graphs.state import PipelineState


class TestPipelineState:
    """PipelineState 测试"""

    def test_create_state(self):
        """测试创建状态"""
        state = PipelineState(
            project_id="test-123",
            query="machine learning",
        )

        assert state.project_id == "test-123"
        assert state.query == "machine learning"
        assert state.status == "created"
        assert state.retry_count == 0

    def test_state_defaults(self):
        """测试默认值"""
        state = PipelineState(
            project_id="test-123",
            query="test",
        )

        assert state.paper_ids == []
        assert state.core_paper_ids == []
        assert state.cluster_ids == []
        assert state.errors == []
        assert state.needs_targeted_refinement is False

    def test_state_update(self):
        """测试状态更新"""
        state = PipelineState(
            project_id="test-123",
            query="test",
        )

        # 模拟状态更新
        update = {
            "paper_ids": ["p1", "p2"],
            "status": "searched",
        }

        # Pydantic 模型更新
        updated = state.model_copy(update=update)
        assert updated.paper_ids == ["p1", "p2"]
        assert updated.status == "searched"
        assert updated.project_id == "test-123"  # 保持原有值

    def test_state_with_config(self):
        """测试带配置的状态"""
        config = {
            "max_embedding_papers": 500,
            "core_reference_count": 80,
        }

        state = PipelineState(
            project_id="test-123",
            query="test",
            config=config,
        )

        assert state.config["max_embedding_papers"] == 500
        assert state.config["core_reference_count"] == 80
