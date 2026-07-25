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
    REGISTER_BATCH_STATE_ACK,
    REGISTER_PRINT_NEXT_ACK,
)
from src.infrastructure.server.commands import PrintNextCommand


def test_workflow_print_next_request_waits_for_server_ack():
    workflow = PrinterWorkflow()
    commands = workflow.handle_event(
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1])
    )

    assert isinstance(commands[0], InsertPlcTriggerEventCommand)
    assert commands[0].event_type == "print_next_request"
    assert commands[1] == PrintNextCommand()


def test_workflow_server_print_next_success_acks_plc():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(
        ServerRequestCompletedEvent(request_type="print_next", success=True, status_code=200)
    )

    assert commands == [
        WriteRegistersCommand(
            slave_id=1,
            address=REGISTER_PRINT_NEXT_ACK,
            values=[1],
            metadata={"reason": "print_next_ok"},
        )
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
        ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[1, 0, 0, 0, 0])
    )
    success_commands = workflow.handle_event(
        ModbusPollEvent(sequence=2, slave_id=1, start_address=0, registers=[0, 0, 1, 0, 0])
    )
    done_commands = workflow.handle_event(
        ModbusPollEvent(sequence=3, slave_id=1, start_address=0, registers=[0, 0, 0, 0, 1])
    )

    assert isinstance(batch_commands[0], StartBatchSummaryCommand)
    assert len(batch_commands[0].batch_id) == 32
    assert isinstance(batch_commands[1], InsertPlcTriggerEventCommand)
    assert batch_commands[1].event_type == "batch_started"
    assert batch_commands[2].address == REGISTER_BATCH_STATE_ACK
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
    assert done_commands[2].address == REGISTER_ATTACK_BATCH_ACK
    assert workflow.batch_counters.label_success_count == 1
    assert workflow.batch_counters.label_failed_count == 0
    assert workflow.batch_counters.active is False


def test_workflow_edge_detection_does_not_repeat_request():
    workflow = PrinterWorkflow()
    event = ModbusPollEvent(sequence=1, slave_id=1, start_address=0, registers=[0, 1, 0, 0, 0])

    first_commands = workflow.handle_event(event)
    second_commands = workflow.handle_event(event)

    assert isinstance(first_commands[0], InsertPlcTriggerEventCommand)
    assert first_commands[1] == PrintNextCommand()
    assert second_commands == []

