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
    REGISTER_ATTACK_LABEL_ACK,
    REGISTER_ATTACK_LABEL_STATE,
    REGISTER_BATCH_STATE,
    REGISTER_BATCH_STATE_ACK,
    REGISTER_PENDING_RESET,
    REGISTER_PRINT_NEXT_ACK,
    REGISTER_PRINT_NEXT_REQUEST,
    REGISTER_RE_PRINT_ACK,
    REGISTER_RE_PRINT_REQUEST,
)
from src.infrastructure.server.commands import (
    EndBatchCommand,
    PrintNextCommand,
    RePrintCommand,
    StartBatchCommand,
)


def test_workflow_start_batch_waits_for_server_ack():
    workflow = PrinterWorkflow()
    commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[1, 0, 0, 0, 0, 0])
    )

    assert commands == [StartBatchCommand()]


def test_workflow_server_start_batch_success_starts_batch_and_acks_plc():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="start_batch", success=True, status_code=200)
    )

    assert isinstance(commands[0], StartBatchSummaryCommand)
    assert len(commands[0].batch_id) == 32
    assert isinstance(commands[1], InsertPlcTriggerEventCommand)
    assert commands[1].event_type == "batch_started"
    assert commands[2] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_STATE,
        values=[0],
        metadata={"reason": "start_batch_ok_reset"},
    )
    assert commands[3] == WriteRegistersCommand(
        slave_id=1,
        address=REGISTER_BATCH_STATE_ACK,
        values=[1],
        metadata={"reason": "start_batch_ok"},
    )


def test_workflow_print_next_request_waits_for_server_ack():
    workflow = PrinterWorkflow()
    commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1, 0, 0, 0, 0])
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
            metadata={"reason": "print_next_ok_reset"},
        ),
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_PRINT_NEXT_ACK,
            values=[1],
            metadata={"reason": "print_next_ok"},
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


def test_workflow_server_failure_allows_retry_while_plc_request_stays_active():
    workflow = PrinterWorkflow()
    event = ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1, 0, 0, 0, 0])

    assert workflow.handle_event(event) == [PrintNextCommand()]
    assert workflow.handle_event(event) == []
    commands = workflow.handle_event(
        ServerRequestCompletedEvent(
            request_type="print_next",
            success=False,
            status_code=500,
            error="server error",
        )
    )
    assert commands == []
    assert workflow.handle_event(event) == [PrintNextCommand()]


def test_workflow_batch_and_label_counters():
    workflow = PrinterWorkflow()

    batch_commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="start_batch", success=True, status_code=200)
    )
    success_commands = workflow.handle_event(
        ModbusPollEvent(sequence=2, slave_id=1, start_address=0, registers=[0, 0, 1, 0, 0, 0])
    )
    assert workflow.handle_event(
        ModbusPollEvent(sequence=3, slave_id=1, start_address=0, registers=[0, 0, 0, 0, 1, 0])
    ) == [EndBatchCommand()]
    done_commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="end_batch", success=True, status_code=200)
    )

    assert isinstance(batch_commands[0], StartBatchSummaryCommand)
    assert len(batch_commands[0].batch_id) == 32
    assert isinstance(batch_commands[1], InsertPlcTriggerEventCommand)
    assert batch_commands[1].event_type == "batch_started"
    assert batch_commands[3].address == REGISTER_BATCH_STATE_ACK
    assert isinstance(success_commands[0], InsertPlcTriggerEventCommand)
    assert success_commands[0].event_type == "label_success"
    assert isinstance(success_commands[1], UpdateBatchSummaryCommand)
    assert success_commands[1].success_count == 1
    assert success_commands[2].address == REGISTER_ATTACK_LABEL_ACK
    assert success_commands[2].values == [1]
    assert isinstance(done_commands[0], InsertPlcTriggerEventCommand)
    assert done_commands[0].event_type == "batch_done"
    assert isinstance(done_commands[1], UpdateBatchSummaryCommand)
    assert done_commands[1].status == "done"
    assert done_commands[3].address == REGISTER_ATTACK_BATCH_ACK
    assert workflow.batch_counters.label_success_count == 1
    assert workflow.batch_counters.label_failed_count == 0
    assert workflow.batch_counters.active is False


def test_workflow_pending_server_request_does_not_repeat_request():
    workflow = PrinterWorkflow()
    event = ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1, 0, 0, 0, 0])

    first_commands = workflow.handle_event(event)
    second_commands = workflow.handle_event(event)

    assert first_commands == [PrintNextCommand()]
    assert second_commands == []


def test_workflow_reprint_success_resets_request_and_acks_plc():
    workflow = PrinterWorkflow()

    assert workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 0, 0, 1, 0, 0])
    ) == [RePrintCommand()]
    commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="reprint", success=True, status_code=200)
    )

    assert isinstance(commands[0], InsertPlcTriggerEventCommand)
    assert commands[0].event_type == "reprint_request"
    assert commands[1:] == [
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_RE_PRINT_REQUEST,
            values=[0],
            metadata={"reason": "reprint_ok_reset"},
        ),
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_RE_PRINT_ACK,
            values=[1],
            metadata={"reason": "reprint_ok"},
        ),
    ]


def test_workflow_pending_attack_blocks_reprint_until_label_result():
    workflow = PrinterWorkflow()

    workflow.handle_event(
        ServerRequestCompletedEvent(request_type="print_next", success=True, status_code=200)
    )
    blocked_commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 0, 0, 1, 0, 0])
    )
    label_commands = workflow.handle_event(
        ModbusPollEvent(sequence=2, slave_id=1, start_address=0, registers=[0, 0, 1, 0, 0, 0])
    )
    retry_commands = workflow.handle_event(
        ModbusPollEvent(sequence=3, slave_id=1, start_address=0, registers=[0, 0, 0, 1, 0, 0])
    )

    assert blocked_commands == []
    assert label_commands[0].register_address == REGISTER_ATTACK_LABEL_STATE
    assert retry_commands == [RePrintCommand()]


def test_workflow_d5_resets_pending_attack_and_plc_register():
    workflow = PrinterWorkflow()

    workflow.handle_event(
        ServerRequestCompletedEvent(request_type="print_next", success=True, status_code=200)
    )
    reset_commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 0, 0, 0, 0, 1])
    )
    retry_commands = workflow.handle_event(
        ModbusPollEvent(sequence=2, slave_id=1, start_address=0, registers=[0, 0, 0, 1, 0, 0])
    )

    assert reset_commands == [
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_PENDING_RESET,
            values=[0],
            metadata={"reason": "pending_reset"},
        )
    ]
    assert retry_commands == [RePrintCommand()]

