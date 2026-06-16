from academic_cluster.services import source_config


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, db):
        self.db = db

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "CREATE TABLE" in sql or "CREATE INDEX" in sql or "CREATE TRIGGER" in sql or "DO $$" in sql:
            return _FakeResult()
        if "SELECT key, label, value_enc" in sql:
            keys = params.get("keys") or []
            return _FakeResult([self.db.rows[key] for key in keys if key in self.db.rows])
        return _FakeResult()


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def session(self):
        return _FakeSessionContext(_FakeSession(self))


class _FakeSettings:
    semantic_scholar_api_key = "env-s2-key"
    pubmed_email = "env@example.com"
    pubmed_api_key = "env-pubmed-key"


class _FakeRow:
    def __init__(self, **kwargs):
        self._mapping = kwargs


async def test_effective_source_value_uses_env_when_no_db_row(monkeypatch):
    monkeypatch.setattr(source_config, "get_settings", lambda: _FakeSettings())

    value = await source_config.get_effective_source_value(
        "semantic_scholar_api_key",
        db=_FakeDb(),
    )

    assert value == "env-s2-key"


async def test_disabled_db_row_suppresses_env_fallback(monkeypatch):
    monkeypatch.setattr(source_config, "get_settings", lambda: _FakeSettings())
    db = _FakeDb(rows={
        "semantic_scholar_api_key": _FakeRow(
            key="semantic_scholar_api_key",
            label="Semantic Scholar API Key",
            value_enc=None,
            is_enabled=False,
            metadata={},
            created_at=None,
            updated_at=None,
        )
    })

    value = await source_config.get_effective_source_value(
        "semantic_scholar_api_key",
        db=db,
    )

    assert value is None
