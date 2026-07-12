from __future__ import annotations


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plc_trigger_event (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    register_address INTEGER NOT NULL,
    register_value INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_plc_trigger_event_batch_created
ON plc_trigger_event(batch_id, created_at);

CREATE INDEX IF NOT EXISTS ix_plc_trigger_event_type_created
ON plc_trigger_event(event_type, created_at);

CREATE TABLE IF NOT EXISTS batch_label_summary (
    batch_id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_batch_label_summary_status_started
ON batch_label_summary(status, started_at);
"""
