from __future__ import annotations

from src.application.events import ModbusPollEvent, ServerRequestCompletedEvent
from src.application.workflow import PrinterWorkflow
from src.infrastructure.database.commands import (
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
)
from src.infrastructure.modbus.commands import WriteRegistersCommand
from src.infrastructure.modbus.registers import (
    REGISTER_ATTACK_BATCH_ACK,
    REGISTER_ATTACK_BATCH_DONE,
    REGISTER_ATTACK_LABEL_ACK,
    REGISTER_BATCH_LABEL_COUNT,
    REGISTER_BATCH_SEQUENCE_ID,
    REGISTER_BATCH_STATE,
    REGISTER_BATCH_STATE_ACK,
    REGISTER_PRINT_NEXT_ACK,
    REGISTER_PRINT_NEXT_REQUEST,
)
from src.infrastructure.server.commands import EndBatchCommand, PrintNextCommand, StartBatchCommand


def start_batch_payload(label_count: int = 2) -> dict[str, object]:
    return {"metaData": {"label_counting": label_count}}


def test_workflow_start_batch_waits_for_server_ack():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[1, 0, 0, 0, 0])
    )

    assert commands == [StartBatchCommand()]


def test_workflow_server_start_batch_success_writes_sequence_and_label_count_before_ack():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=2),
        )
    )

    assert commands[0] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_SEQUENCE_ID,
        values=[1],
    )
    assert commands[1] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_LABEL_COUNT,
        values=[2],
    )
    assert isinstance(commands[2], StartBatchSummaryCommand)
    assert len(commands[2].batch_id) == 32
    assert isinstance(commands[3], InsertPlcTriggerEventCommand)
    assert commands[3].event_type == "batch_started"
    assert commands[4] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_STATE,
        values=[0],
    )
    assert commands[5] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_STATE_ACK,
        values=[1],
    )


def test_workflow_start_batch_sequence_increments_and_wraps_without_zero():
    workflow = PrinterWorkflow()
    workflow._batch_sequence_id = 65534

    first_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=1),
        )
    )
    second_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=1),
        )
    )
    third_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=1),
        )
    )

    assert first_commands[0].values == [65535]
    assert second_commands[0].values == [1]
    assert third_commands[0].values == [2]


def test_workflow_start_batch_invalid_payload_does_not_ack_plc():
    workflow = PrinterWorkflow()

    missing_payload_commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="start_batch", success=True, status_code=200)
    )
    missing_label_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload={"metaData": {}},
        )
    )
    negative_label_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=-1),
        )
    )

    assert missing_payload_commands == []
    assert missing_label_commands == []
    assert negative_label_commands == []


def test_workflow_print_next_request_waits_for_server_ack():
    workflow = PrinterWorkflow()
    commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1])
    )

    assert commands == [PrintNextCommand()]


def test_workflow_server_print_next_success_resets_request_and_acks_plc():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="print_next", success=True, status_code=200)
    )

    assert isinstance(commands[0], InsertPlcTriggerEventCommand)
    assert commands[0].event_type == "print_next_request"
    assert commands[1:] == [
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_PRINT_NEXT_REQUEST,
            values=[0],
        ),
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_PRINT_NEXT_ACK,
            values=[1],
        ),
    ]


def test_workflow_server_failure_does_not_ack_plc():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="print_next",
            success=False,
            status_code=500,
            error="server error",
        )
    )

    assert commands == []


def test_workflow_batch_and_label_counters():
    workflow = PrinterWorkflow()

    batch_commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="start_batch",
            success=True,
            status_code=200,
            payload=start_batch_payload(label_count=2),
        )
    )
    success_commands = workflow.handle_event(
        ModbusPollEvent(sequence=2, slave_id=1, start_address=0, registers=[0, 0, 1, 0, 0])
    )
    done_commands = workflow.handle_event(
        ModbusPollEvent(sequence=3, slave_id=1, start_address=0, registers=[0, 0, 0, 0, 1])
    )
    end_batch_server_commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="end_batch", success=True, status_code=200)
    )

    assert isinstance(batch_commands[2], StartBatchSummaryCommand)
    assert isinstance(success_commands[0], InsertPlcTriggerEventCommand)
    assert success_commands[0].event_type == "label_success"
    assert isinstance(success_commands[1], UpdateBatchSummaryCommand)
    assert success_commands[1].success_count == 1
    assert success_commands[2].address == REGISTER_ATTACK_LABEL_ACK
    assert success_commands[2].values == [1]
    assert done_commands[0] == EndBatchCommand()
    assert isinstance(done_commands[1], InsertPlcTriggerEventCommand)
    assert done_commands[1].event_type == "batch_done"
    assert isinstance(done_commands[2], UpdateBatchSummaryCommand)
    assert done_commands[2].status == "done"
    assert done_commands[3].address == REGISTER_ATTACK_BATCH_DONE
    assert done_commands[4].address == REGISTER_ATTACK_BATCH_ACK
    assert end_batch_server_commands == []
    assert workflow.batch_counters.label_success_count == 1
    assert workflow.batch_counters.label_failed_count == 0
    assert workflow.batch_counters.active is False


def test_workflow_pending_server_request_does_not_repeat_request():
    workflow = PrinterWorkflow()
    event = ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1, 0, 0, 0])

    first_commands = workflow.handle_event(event)
    second_commands = workflow.handle_event(event)

    assert first_commands == [PrintNextCommand()]
    assert second_commands == []
