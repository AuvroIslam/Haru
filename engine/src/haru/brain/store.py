"""SQLite persistence for the Personal Brain.

Storage shape
-------------
Two tables rather than one per entity:

``records``    list-valued entities (projects, experience, skills, …) as JSON
               payloads with the queryable bits lifted into real columns.
``singletons`` one-per-profile blocks (identity, compensation, preferences, …).

The schema will churn heavily in early development and Pydantic already owns
validation, so a JSON payload avoids a migration per field. The columns that are
lifted out — ``profile_id``, ``kind``, ``confirmed`` — are the ones the review
queue and the fact boundary actually filter on.

``record_history`` keeps superseded payloads, satisfying "facts are versioned"
(PRD §6.1).

Connection handling (WAL, per-thread connections, busy timeout) follows standard
SQLite practice for concurrent readers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Sequence, TypeVar

from pydantic import BaseModel

from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    Availability,
    BrainRecord,
    Compensation,
    Credential,
    Education,
    Experience,
    Identity,
    Preferences,
    Project,
    QuestionBankEntry,
    Skill,
    StandardAnswers,
    VoluntaryDisclosure,
    WorkAuthorization,
    WritingSample,
)
from haru.brain.provenance import utcnow

SCHEMA_VERSION = 1

R = TypeVar("R", bound=BrainRecord)
S = TypeVar("S", bound=BaseModel)

#: Stable on-disk names. Never rename a value here without a migration — the
#: class may be renamed freely, the string may not.
RECORD_KINDS: dict[type[BrainRecord], str] = {
    Education: "education",
    Experience: "experience",
    Project: "project",
    Skill: "skill",
    Credential: "credential",
    WritingSample: "writing_sample",
    QuestionBankEntry: "question_bank_entry",
}

SINGLETON_KINDS: dict[type[BaseModel], str] = {
    Identity: "identity",
    WorkAuthorization: "work_authorization",
    Availability: "availability",
    Compensation: "compensation",
    VoluntaryDisclosure: "voluntary_disclosure",
    StandardAnswers: "standard_answers",
    Preferences: "preferences",
}

_KIND_TO_RECORD = {v: k for k, v in RECORD_KINDS.items()}

_local = threading.local()


class UnknownKindError(LookupError):
    """Raised when a model has no registered on-disk kind."""


def record_kind(model: type[BrainRecord]) -> str:
    try:
        return RECORD_KINDS[model]
    except KeyError:
        raise UnknownKindError(
            f"{model.__name__} is not registered in RECORD_KINDS"
        ) from None


def singleton_kind(model: type[BaseModel]) -> str:
    try:
        return SINGLETON_KINDS[model]
    except KeyError:
        raise UnknownKindError(
            f"{model.__name__} is not registered in SINGLETON_KINDS"
        ) from None


def connect(path: Path | str) -> sqlite3.Connection:
    """Return a per-thread connection, creating and initialising as needed.

    SQLite connections are not safe to share across threads, so each thread gets
    its own and they are cached by path.
    """
    key = str(path)
    cache: dict[str, sqlite3.Connection] = getattr(_local, "connections", None) or {}
    _local.connections = cache

    existing = cache.get(key)
    if existing is not None:
        try:
            existing.execute("SELECT 1")
            return existing
        except sqlite3.ProgrammingError:
            cache.pop(key, None)

    if key != ":memory:":
        Path(key).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(key, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate(conn)
    cache[key] = conn
    return conn


def close(path: Path | str) -> None:
    cache: dict[str, sqlite3.Connection] = getattr(_local, "connections", None) or {}
    conn = cache.pop(str(path), None)
    if conn is not None:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent schema creation, versioned via PRAGMA user_version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            id          TEXT PRIMARY KEY,
            profile_id  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            payload     TEXT NOT NULL,
            confirmed   INTEGER NOT NULL DEFAULT 0,
            confidence  REAL NOT NULL DEFAULT 0,
            source      TEXT NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_records_lookup
            ON records (profile_id, kind, confirmed);
        CREATE INDEX IF NOT EXISTS idx_records_review
            ON records (profile_id, confirmed, confidence);

        CREATE TABLE IF NOT EXISTS record_history (
            record_id   TEXT NOT NULL,
            version     INTEGER NOT NULL,
            payload     TEXT NOT NULL,
            superseded_at TEXT NOT NULL,
            PRIMARY KEY (record_id, version)
        );

        CREATE TABLE IF NOT EXISTS singletons (
            profile_id  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            payload     TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (profile_id, kind)
        );
        """
    )
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


class BrainStore:
    """Read/write access to one Brain database."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        self._conn = connect(self.path)

    @property
    def conn(self) -> sqlite3.Connection:
        # Re-resolve so a store handed to another thread still works.
        return connect(self.path)

    # ── records ──────────────────────────────────────────────────────────

    def put(self, record: R) -> R:
        """Insert or update a record, bumping version and archiving the old payload."""
        kind = record_kind(type(record))
        conn = self.conn
        previous = conn.execute(
            "SELECT payload, version FROM records WHERE id = ?", (record.id,)
        ).fetchone()

        if previous is not None:
            record = record.model_copy(
                update={"version": previous["version"] + 1, "updated_at": utcnow()}
            )
            conn.execute(
                "INSERT OR REPLACE INTO record_history "
                "(record_id, version, payload, superseded_at) VALUES (?, ?, ?, ?)",
                (
                    record.id,
                    previous["version"],
                    previous["payload"],
                    utcnow().isoformat(),
                ),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO records
                (id, profile_id, kind, payload, confirmed, confidence,
                 source, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.profile_id,
                kind,
                record.model_dump_json(),
                int(record.provenance.confirmed),
                record.provenance.confidence,
                record.provenance.source.value,
                record.version,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        conn.commit()
        return record

    def put_many(self, records: Iterable[R]) -> list[R]:
        return [self.put(r) for r in records]

    def get(self, model: type[R], record_id: str) -> R | None:
        row = self.conn.execute(
            "SELECT payload FROM records WHERE id = ? AND kind = ?",
            (record_id, record_kind(model)),
        ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    def list(
        self,
        model: type[R],
        *,
        profile_id: str = DEFAULT_PROFILE_ID,
        confirmed_only: bool = False,
    ) -> list[R]:
        """List records of one kind.

        ``confirmed_only`` is what the fact boundary uses — unconfirmed facts
        must never widen what may be claimed (PRD §6.3).
        """
        sql = "SELECT payload FROM records WHERE kind = ? AND profile_id = ?"
        params: list[object] = [record_kind(model), profile_id]
        if confirmed_only:
            sql += " AND confirmed = 1"
        sql += " ORDER BY created_at"
        rows = self.conn.execute(sql, params).fetchall()
        return [model.model_validate_json(r["payload"]) for r in rows]

    def delete(self, model: type[R], record_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM records WHERE id = ? AND kind = ?",
            (record_id, record_kind(model)),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def history(self, record_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version, payload, superseded_at FROM record_history "
            "WHERE record_id = ? ORDER BY version",
            (record_id,),
        ).fetchall()
        return [
            {
                "version": r["version"],
                "payload": json.loads(r["payload"]),
                "superseded_at": r["superseded_at"],
            }
            for r in rows
        ]

    # ── singletons ───────────────────────────────────────────────────────

    def put_singleton(self, block: S) -> S:
        kind = singleton_kind(type(block))
        profile_id = getattr(block, "profile_id", DEFAULT_PROFILE_ID)
        self.conn.execute(
            "INSERT OR REPLACE INTO singletons (profile_id, kind, payload, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (profile_id, kind, block.model_dump_json(), utcnow().isoformat()),
        )
        self.conn.commit()
        return block

    def get_singleton(
        self, model: type[S], *, profile_id: str = DEFAULT_PROFILE_ID
    ) -> S | None:
        row = self.conn.execute(
            "SELECT payload FROM singletons WHERE profile_id = ? AND kind = ?",
            (profile_id, singleton_kind(model)),
        ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    # ── review queue feed ────────────────────────────────────────────────

    def unconfirmed(
        self, *, profile_id: str = DEFAULT_PROFILE_ID, limit: int | None = None
    ) -> list[BrainRecord]:
        """Every unconfirmed record, least confident first.

        This is the review queue's data source (PRD §6.3): imports land here and
        nothing leaves until a human confirms it.
        """
        sql = (
            "SELECT kind, payload FROM records "
            "WHERE profile_id = ? AND confirmed = 0 "
            "ORDER BY confidence ASC, created_at ASC"
        )
        params: list[object] = [profile_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [
            _KIND_TO_RECORD[r["kind"]].model_validate_json(r["payload"])
            for r in self.conn.execute(sql, params).fetchall()
        ]

    def counts(self, *, profile_id: str = DEFAULT_PROFILE_ID) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT kind, COUNT(*) AS n FROM records WHERE profile_id = ? GROUP BY kind",
            (profile_id,),
        ).fetchall()
        return {r["kind"]: r["n"] for r in rows}

    def profiles(self) -> Sequence[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT profile_id FROM records ORDER BY profile_id"
        ).fetchall()
        return [r["profile_id"] for r in rows]

    def close(self) -> None:
        close(self.path)
