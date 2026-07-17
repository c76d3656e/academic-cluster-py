"""Administration API for runtime feature flags that are actually consumed."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import get_database

router = APIRouter(prefix="/pipeline-config")

DEFAULT_CONFIG: dict[str, dict[str, str]] = {
    "ui.show_usage": {
        "value": "false",
        "label": "显示调用明细",
        "description": (
            "开启后用户可在项目详情页查看 LLM 调用明细，并在控制台查看个人用量页面"
        ),
        "group": "系统",
        "type": "bool",
    }
}


async def init_pipeline_config_table() -> None:
    """Create the feature-flag table used by the frontend."""

    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("""
                CREATE TABLE IF NOT EXISTS pipeline_config (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    label VARCHAR(200) NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    group_name VARCHAR(50) NOT NULL DEFAULT 'general',
                    value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
        )


async def _ensure_defaults() -> None:
    """Upsert supported flags and remove keys from the deleted legacy graph."""

    db = get_database()
    async with db.session() as session:
        for key, config in DEFAULT_CONFIG.items():
            await session.execute(
                text("""
                    INSERT INTO pipeline_config (
                        key, value, label, description, group_name, value_type
                    )
                    VALUES (:key, :value, :label, :description, :group, :value_type)
                    ON CONFLICT (key) DO UPDATE SET
                        label = EXCLUDED.label,
                        description = EXCLUDED.description,
                        group_name = EXCLUDED.group_name,
                        value_type = EXCLUDED.value_type
                """),
                {
                    "key": key,
                    "value": config["value"],
                    "label": config["label"],
                    "description": config["description"],
                    "group": config["group"],
                    "value_type": config["type"],
                },
            )
        await session.execute(
            text("DELETE FROM pipeline_config WHERE key NOT LIKE 'ui.%'")
        )


class PipelineConfigItem(BaseModel):
    key: str
    value: str
    label: str = ""
    description: str = ""
    group: str = ""
    type: str = "string"


class PipelineConfigUpdate(BaseModel):
    value: str


def _validate_value(config_type: str, value: str) -> str:
    normalized = value.strip().lower()
    if config_type == "bool":
        if normalized not in {"true", "false"}:
            raise HTTPException(
                status_code=422,
                detail="Boolean feature flags accept only 'true' or 'false'",
            )
        return normalized
    return value


@router.get("/features")
async def get_features() -> dict[str, bool]:
    """Return public UI feature flags."""

    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT key, value FROM pipeline_config WHERE key LIKE 'ui.%'")
        )
        rows = result.fetchall()
    return {str(row[0]).removeprefix("ui."): row[1] == "true" for row in rows}


@router.get("", response_model=list[PipelineConfigItem])
async def list_pipeline_config() -> list[PipelineConfigItem]:
    """List supported runtime feature flags."""

    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            text(
                "SELECT key, value, label, description, group_name, value_type "
                "FROM pipeline_config ORDER BY group_name, key"
            )
        )
        rows = result.fetchall()
    return [
        PipelineConfigItem(
            key=str(row[0]),
            value=str(row[1]),
            label=str(row[2]),
            description=str(row[3]),
            group=str(row[4]),
            type=str(row[5]),
        )
        for row in rows
    ]


@router.put("/{key}")
async def update_pipeline_config(
    key: str,
    body: PipelineConfigUpdate,
) -> dict[str, str]:
    """Update a supported feature flag."""

    db = get_database()
    async with db.session() as session:
        result = await session.execute(
            text("SELECT value_type FROM pipeline_config WHERE key = :key"),
            {"key": key},
        )
        row = result.fetchone()
        if not row or key not in DEFAULT_CONFIG:
            raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
        value = _validate_value(str(row[0]), body.value)
        await session.execute(
            text(
                "UPDATE pipeline_config "
                "SET value = :value, updated_at = NOW() WHERE key = :key"
            ),
            {"key": key, "value": value},
        )
    return {"key": key, "value": value, "message": "配置已更新"}


@router.post("/reset")
async def reset_pipeline_config() -> dict[str, str]:
    """Reset supported feature flags to defaults."""

    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        for key, config in DEFAULT_CONFIG.items():
            await session.execute(
                text(
                    "UPDATE pipeline_config "
                    "SET value = :value, updated_at = NOW() WHERE key = :key"
                ),
                {"key": key, "value": config["value"]},
            )
    return {"message": "所有配置已重置为默认值"}
