"""Schema definition + init for the Gen-1 water-safety backend.

Schema is declared as SQLAlchemy MetaData/Table objects so the same code
emits SQLite DDL locally and Postgres DDL on Railway. init_db() is
idempotent: it creates any missing tables, adds any newly-added columns
on existing tables, and seeds the 10 stations row by row with
ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Index, Integer, MetaData,
    Table, Text, UniqueConstraint, func, inspect, text,
)
from sqlalchemy.engine import Connection

from engine import get_engine


metadata = MetaData()


stations = Table(
    "stations", metadata,
    Column("station_id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("is_closed", Integer, nullable=False, server_default=text("0")),
    Column("created_at", Text, nullable=False, server_default=func.current_timestamp()),
)


sensor_readings = Table(
    "sensor_readings", metadata,
    Column("reading_id", Integer, primary_key=True, autoincrement=True),
    Column("station_id", Integer, ForeignKey("stations.station_id"), nullable=False),
    Column("recorded_at", Text, nullable=False),
    Column("ph", Float),
    Column("turbidity_ntu", Float),
    Column("temperature_c", Float),
    Column("rainfall_mm", Float),
    Column("provenance", Text, nullable=False, server_default=text("'unknown'")),
    Column("received_at", Text, nullable=False, server_default=func.current_timestamp()),
    Index("idx_readings_station_time", "station_id", "recorded_at"),
)


illness_reports = Table(
    "illness_reports", metadata,
    Column("report_id", Integer, primary_key=True, autoincrement=True),
    Column("station_id", Integer, ForeignKey("stations.station_id")),
    Column("reporter_phone", Text),
    Column("raw_message", Text, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("received_at", Text, nullable=False, server_default=func.current_timestamp()),
    Column("report_source", Text, nullable=False, server_default=text("'sms'")),
    Column("submitter", Text),
    Column("case_count", Integer),
    Column("onset_date", Text),
    Column("symptoms", Text),
    Column("risk_tier", Text),
    Column("dialog_state", Text),
    CheckConstraint(
        "report_source IN ('sms', 'medical_portal')",
        name="ck_illness_reports_source",
    ),
    CheckConstraint(
        "risk_tier IS NULL OR risk_tier IN ('low','medium','high','severe')",
        name="ck_illness_reports_risk_tier",
    ),
    CheckConstraint(
        "dialog_state IS NULL OR dialog_state IN "
        "('awaiting_case_count','awaiting_symptoms','awaiting_onset','complete','abandoned')",
        name="ck_illness_reports_dialog_state",
    ),
    Index("idx_reports_station_time", "station_id", "received_at"),
)


reading_labels = Table(
    "reading_labels", metadata,
    Column("label_id", Integer, primary_key=True, autoincrement=True),
    Column("reading_id", Integer, ForeignKey("sensor_readings.reading_id"), nullable=False),
    Column("report_id", Integer, ForeignKey("illness_reports.report_id"), nullable=False),
    Column("label", Text, nullable=False),
    Column("rule_description", Text, nullable=False),
    Column("labelled_at", Text, nullable=False, server_default=func.current_timestamp()),
    CheckConstraint("label IN ('unsafe', 'suspect')", name="ck_reading_labels_label"),
    UniqueConstraint("reading_id", "report_id", name="uq_reading_labels_reading_report"),
    Index("idx_labels_reading", "reading_id"),
)


interventions = Table(
    "interventions", metadata,
    Column("intervention_id", Integer, primary_key=True, autoincrement=True),
    Column("station_id", Integer, ForeignKey("stations.station_id"), nullable=False),
    Column("action_type", Text, nullable=False),
    Column("triggered_by", Text, nullable=False),
    Column("triggered_at", Text, nullable=False, server_default=func.current_timestamp()),
    Column("related_report_id", Integer, ForeignKey("illness_reports.report_id")),
    Column("notes", Text),
    CheckConstraint(
        "action_type IN ('close_borehole', 'reopen_borehole', "
        "'dispatch_sample_team', 'dispatch_medical_team')",
        name="ck_interventions_action_type",
    ),
    Index("idx_interventions_station_time", "station_id", "triggered_at"),
    Index("idx_interventions_report", "related_report_id"),
)


SEED_STATIONS = [
    (1,  "Borehole A — village centre",   -17.829, 31.052),
    (2,  "Borehole B — clinic",           -17.831, 31.057),
    (3,  "Borehole C — school",           -17.828, 31.049),
    (4,  "Borehole D — market",           -17.833, 31.054),
    (5,  "Borehole E — north well",       -17.820, 31.060),
    (6,  "Borehole F — east settlement",  -17.836, 31.069),
    (7,  "Borehole G — south farm",       -17.847, 31.055),
    (8,  "Borehole H — west outpost",     -17.838, 31.041),
    (9,  "Borehole I — river crossing",   -17.826, 31.073),
    (10, "Borehole J — bus station",      -17.842, 31.062),
]


# Columns that may be missing from an existing illness_reports table on a
# pre-Phase-C deploy. CHECK constraints are inlined so an ALTER-TABLE
# upgrade path lands them on the column, matching the Table-level
# CheckConstraints that fire on a fresh CREATE TABLE.
_REPORT_BACKFILL_COLUMNS = [
    ("report_source", "TEXT NOT NULL DEFAULT 'sms'"),
    ("submitter",     "TEXT"),
    ("case_count",    "INTEGER"),
    ("onset_date",    "TEXT"),
    ("symptoms",      "TEXT"),
    ("risk_tier",     "TEXT CHECK (risk_tier IS NULL OR risk_tier IN "
                      "('low','medium','high','severe'))"),
    ("dialog_state",  "TEXT CHECK (dialog_state IS NULL OR dialog_state IN "
                      "('awaiting_case_count','awaiting_symptoms',"
                      "'awaiting_onset','complete','abandoned'))"),
]


@contextmanager
def connection() -> Iterator[Connection]:
    """Yield a SQLAlchemy 2.x Connection.

    Writes must be committed explicitly. SQLAlchemy 2.x auto-begins a
    transaction on the first statement and silently rolls it back when
    the Connection closes, so callers either need ``conn.commit()`` or,
    preferably, ``with conn.begin():`` around their write block.
    Read-only callers can ignore the transaction.
    """
    conn = get_engine().connect()
    try:
        yield conn
    finally:
        conn.close()


def _migrate(conn: Connection) -> None:
    """Add columns introduced after the original schema, idempotently.

    Uses SQLAlchemy's inspect() so it works on both SQLite (PRAGMA-backed
    introspection) and Postgres (information_schema-backed).
    """
    insp = inspect(conn)
    existing_report_cols = {c["name"] for c in insp.get_columns("illness_reports")}
    for col_name, col_type in _REPORT_BACKFILL_COLUMNS:
        if col_name not in existing_report_cols:
            conn.execute(text(
                f"ALTER TABLE illness_reports ADD COLUMN {col_name} {col_type}"
            ))

    existing_station_cols = {c["name"] for c in insp.get_columns("stations")}
    if "is_closed" not in existing_station_cols:
        conn.execute(text(
            "ALTER TABLE stations ADD COLUMN is_closed INTEGER NOT NULL DEFAULT 0"
        ))


def init_db() -> None:
    """Create all tables, run any needed column-level migrations, and seed stations.

    Safe to call repeatedly. Designed to run on every Flask startup. All
    DDL runs in one transaction so a Postgres failure mid-migration rolls
    back cleanly.
    """
    engine = get_engine()
    with engine.begin() as conn:
        metadata.create_all(conn)
        _migrate(conn)
        for sid, name, lat, lon in SEED_STATIONS:
            conn.execute(
                text(
                    "INSERT INTO stations (station_id, name, latitude, longitude) "
                    "VALUES (:sid, :name, :lat, :lon) "
                    "ON CONFLICT (station_id) DO NOTHING"
                ),
                {"sid": sid, "name": name, "lat": lat, "lon": lon},
            )


if __name__ == "__main__":
    init_db()
    print(f"Initialised database at {get_engine().url}")
