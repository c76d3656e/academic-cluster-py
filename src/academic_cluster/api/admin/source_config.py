"""Admin endpoints for academic source credentials."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...services.database import DatabaseService, get_database
from ...services.source_config import (
    append_source_config_value,
    clear_source_config,
    list_academic_sources,
    upsert_source_config,
)
from ...services.source_config import (
    list_source_configs as list_source_configs_service,
)
from ..dependencies import require_admin

logger = structlog.get_logger()

router = APIRouter(tags=["admin-source-config"])


async def _audit_source_change(
    db: DatabaseService,
    admin: dict[str, Any],
    action: str,
    key: str,
    item: dict[str, Any],
) -> None:
    try:
        await db.log_activity(
            user_id=str(admin["id"]),
            action=f"source.{action}",
            resource_type="source_config",
            details={
                "key": key,
                "is_enabled": bool(item.get("is_enabled")),
                "key_count": int(item.get("key_count") or 0),
                "is_set": bool(item.get("is_set")),
            },
        )
    except Exception as error:
        logger.warning(
            "Failed to persist source configuration audit",
            key=key,
            action=action,
            error=str(error),
        )


class SourceConfigItem(BaseModel):
    key: str
    label: str
    value: str | None = None
    is_set: bool = False
    key_count: int = 0
    is_enabled: bool = True
    value_source: str = "env"
    is_secret: bool = True
    supports_multiple: bool = False
    description: str = ""
    updated_at: str | None = None


class SourceConfigListResponse(BaseModel):
    configs: list[SourceConfigItem]
    sources: list[dict[str, Any]] = Field(default_factory=list)


class UpdateSourceConfigRequest(BaseModel):
    value: str = Field(
        default="", description="Raw source value. Empty value clears the DB override."
    )
    is_enabled: bool = True


class AppendSourceConfigRequest(BaseModel):
    value: str = Field(
        ...,
        min_length=1,
        description="One or more new values. Multi-key sources accept comma-separated values.",
    )


@router.get("/sources", response_model=SourceConfigListResponse)
async def list_source_configs(
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> SourceConfigListResponse:
    configs = await list_source_configs_service(db)
    return SourceConfigListResponse(
        configs=[SourceConfigItem(**item) for item in configs],
        sources=list_academic_sources(),
    )


@router.put("/sources/{key}", response_model=SourceConfigItem)
async def update_source_config(
    key: str,
    body: UpdateSourceConfigRequest,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> SourceConfigItem:
    try:
        if not body.value.strip() or not body.is_enabled:
            item = await clear_source_config(key, created_by=admin.get("id"), db=db)
        else:
            item = await upsert_source_config(
                key,
                body.value,
                is_enabled=body.is_enabled,
                created_by=admin.get("id"),
                db=db,
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown source key") from None

    _reset_search_runtime_cache()
    await _audit_source_change(db, admin, "update", key, item)
    logger.info("Source config updated", key=key, admin_id=admin.get("id"))
    return SourceConfigItem(**item)


@router.post("/sources/{key}/append", response_model=SourceConfigItem)
async def append_source_config(
    key: str,
    body: AppendSourceConfigRequest,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> SourceConfigItem:
    try:
        item = await append_source_config_value(
            key,
            body.value,
            created_by=admin.get("id"),
            db=db,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown source key") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    _reset_search_runtime_cache()
    await _audit_source_change(db, admin, "append", key, item)
    logger.info("Source config appended", key=key, admin_id=admin.get("id"))
    return SourceConfigItem(**item)


@router.delete("/sources/{key}", response_model=SourceConfigItem)
async def delete_source_config(
    key: str,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> SourceConfigItem:
    try:
        item = await clear_source_config(key, created_by=admin.get("id"), db=db)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown source key") from None

    _reset_search_runtime_cache()
    await _audit_source_change(db, admin, "clear", key, item)
    logger.info("Source config cleared", key=key, admin_id=admin.get("id"))
    return SourceConfigItem(**item)


def _reset_search_runtime_cache() -> None:
    try:
        from ...tools.academic_search import reset_source_config_runtime_cache

        reset_source_config_runtime_cache()
    except Exception as e:
        logger.warning("Failed to reset source runtime cache", error=str(e))
