"""Administrator API for TOML-defined, persistent runtime policy."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from ...services.database import get_database
from ...services.runtime_policy import config_definitions, validate_config_value
from ..dependencies import require_admin

router = APIRouter(prefix="/pipeline-config")


async def init_pipeline_config_table() -> None:
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
    """Seed TOML metadata while preserving administrator-owned values."""

    db = get_database()
    async with db.session() as session:
        for key, config in config_definitions().items():
            await session.execute(
                text("""
                    INSERT INTO pipeline_config (
                        key, value, label, description, group_name, value_type
                    ) VALUES (:key, :value, :label, :description, :group, :value_type)
                    ON CONFLICT (key) DO UPDATE SET
                        label = EXCLUDED.label,
                        description = EXCLUDED.description,
                        group_name = EXCLUDED.group_name,
                        value_type = EXCLUDED.value_type
                """),
                {
                    "key": key,
                    "value": str(config["value"]),
                    "label": str(config["label"]),
                    "description": str(config["description"]),
                    "group": str(config["group"]),
                    "value_type": str(config["type"]),
                },
            )


class PipelineConfigItem(BaseModel):
    key: str
    value: str
    label: str = ""
    description: str = ""
    group: str = ""
    type: str = "string"
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] = Field(default_factory=list)


class PipelineConfigUpdate(BaseModel):
    value: str


@router.get("/features")
async def get_features(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        rows = (
            await session.execute(
                text("SELECT key, value FROM pipeline_config WHERE key LIKE 'ui.%'")
            )
        ).fetchall()
    return {str(row[0]).removeprefix("ui."): row[1] == "true" for row in rows}


@router.get("", response_model=list[PipelineConfigItem])
async def list_pipeline_config(
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[PipelineConfigItem]:
    await _ensure_defaults()
    definitions = config_definitions()
    db = get_database()
    async with db.session() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT key, value, label, description, group_name, value_type
                    FROM pipeline_config ORDER BY group_name, key
                """)
            )
        ).fetchall()
    return [
        PipelineConfigItem(
            key=str(row[0]),
            value=str(row[1]),
            label=str(row[2]),
            description=str(row[3]),
            group=str(row[4]),
            type=str(row[5]),
            minimum=definitions[str(row[0])].get("minimum"),
            maximum=definitions[str(row[0])].get("maximum"),
            options=list(definitions[str(row[0])].get("options") or []),
        )
        for row in rows
        if str(row[0]) in definitions
    ]


@router.put("/{key}")
async def update_pipeline_config(
    key: str,
    body: PipelineConfigUpdate,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    definitions = config_definitions()
    definition = definitions.get(key)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    try:
        value = validate_config_value(definition, body.value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db = get_database()
    async with db.session() as session:
        row = (
            await session.execute(
                text("SELECT key FROM pipeline_config WHERE key = :key"),
                {"key": key},
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
        await session.execute(
            text(
                "UPDATE pipeline_config SET value = :value, updated_at = NOW() WHERE key = :key"
            ),
            {"key": key, "value": value},
        )
    await db.log_activity(
        user_id=str(admin["id"]),
        action="runtime_policy.update",
        resource_type="pipeline_config",
        resource_id=key,
        details={"value": value},
    )
    result: dict[str, Any] = {
        "key": key,
        "value": value,
        "message": "Configuration updated",
    }
    if key == "embedding.target_dimensions":
        target_dimensions = int(value)
        async with db.session() as session:
            dimensions = (
                await session.execute(
                    text(
                        "SELECT DISTINCT dimensions FROM embeddings ORDER BY dimensions"
                    )
                )
            ).fetchall()
        existing_dimensions = sorted(
            {
                int(row[0])
                for row in dimensions
                if isinstance(row[0], int) and not isinstance(row[0], bool)
            }
        )
        result.update(
            existing_dimensions=existing_dimensions,
            reindex_required=bool(
                existing_dimensions and existing_dimensions != [target_dimensions]
            ),
        )
    return result


@router.post("/reset")
async def reset_pipeline_config(
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    await _ensure_defaults()
    db = get_database()
    async with db.session() as session:
        for key, config in config_definitions().items():
            await session.execute(
                text(
                    "UPDATE pipeline_config SET value = :value, updated_at = NOW() WHERE key = :key"
                ),
                {"key": key, "value": str(config["value"])},
            )
    await db.log_activity(
        user_id=str(admin["id"]),
        action="runtime_policy.reset",
        resource_type="pipeline_config",
        resource_id="all",
        details={},
    )
    return {"message": "All runtime policy values were reset"}
