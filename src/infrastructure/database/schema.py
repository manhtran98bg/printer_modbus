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

CREATE TABLE IF NOT EXISTS communication_event (
    operation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    direction TEXT NOT NULL,
    request_register INTEGER NOT NULL DEFAULT -1,
    request_value INTEGER NOT NULL DEFAULT 0,
    response_register INTEGER NOT NULL DEFAULT -1,
    response_value INTEGER NOT NULL DEFAULT 0,
    box_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    http_status INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    started_at INTEGER NOT NULL,
    completed_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_communication_event_updated
ON communication_event(updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_communication_event_status_updated
ON communication_event(status, updated_at DESC);
"""
