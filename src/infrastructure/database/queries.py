from __future__ import annotations


INSERT_PLC_TRIGGER_EVENT = """
INSERT INTO plc_trigger_event (
    id, batch_id, event_type, register_address, register_value, created_at
)
VALUES (?, ?, ?, ?, ?, ?)
"""

INSERT_BATCH_SUMMARY = """
INSERT INTO batch_label_summary (
    batch_id, started_at, ended_at, status, success_count, failed_count, created_at, updated_at
)
VALUES (?, ?, 0, ?, 0, 0, ?, ?)
ON CONFLICT(batch_id) DO UPDATE SET
    started_at = excluded.started_at,
    ended_at = 0,
    status = excluded.status,
    success_count = 0,
    failed_count = 0,
    updated_at = excluded.updated_at
"""

UPDATE_BATCH_SUMMARY = """
UPDATE batch_label_summary
SET ended_at = ?,
    status = ?,
    success_count = ?,
    failed_count = ?,
    updated_at = ?
WHERE batch_id = ?
"""
