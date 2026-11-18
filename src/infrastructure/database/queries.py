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

UPSERT_COMMUNICATION_EVENT = """
INSERT INTO communication_event (
    operation_id, batch_id, action, direction,
    request_register, request_value, response_register, response_value,
    box_count, status, http_status, message,
    started_at, completed_at, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(operation_id) DO UPDATE SET
    batch_id = excluded.batch_id,
    action = excluded.action,
    direction = excluded.direction,
    request_register = excluded.request_register,
    request_value = excluded.request_value,
    response_register = excluded.response_register,
    response_value = excluded.response_value,
    box_count = excluded.box_count,
    status = excluded.status,
    http_status = excluded.http_status,
    message = excluded.message,
    completed_at = excluded.completed_at,
    updated_at = excluded.updated_at
"""

DELETE_OLD_COMMUNICATION_EVENTS = """
DELETE FROM communication_event WHERE updated_at < ?
"""
