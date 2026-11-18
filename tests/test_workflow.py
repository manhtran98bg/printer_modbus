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
    REGISTER_END_BATCH_REQUEST,
    REGISTER_END_BATCH_RESPONSE,
    REGISTER_LABEL_SUCCESS_REQUEST,
    REGISTER_LABEL_SUCCESS_RESPONSE,
    REGISTER_PRINT_NEXT_REQUEST,
    REGISTER_PRINT_NEXT_RESPONSE,
    REGISTER_REPRINT_REQUEST,
    REGISTER_REPRINT_RESPONSE,
    REGISTER_RESET_REQUEST,
    REGISTER_RESET_RESPONSE,
    REGISTER_START_BATCH_REQUEST,
    REGISTER_START_BATCH_RESPONSE,
)
from src.infrastructure.server.commands import (
    EndBatchCommand,
    PrintNextCommand,
    RePrintCommand,
    StartBatchCommand,
)


def poll(*, sequence: int = 1, **register_values: int) -> ModbusPollEvent:
    registers = [0] * 16
    for register, value in register_values.items():
        registers[int(register.removeprefix("d"))] = value
    return ModbusPollEvent(
        sequence=sequence,
        slave_id=1,
        start_address=0,
        registers=registers,
    )


def completion(
    command: StartBatchCommand | PrintNextCommand | RePrintCommand | EndBatchCommand,
    request_type: str,
    *,
    status_code: int,
    success: bool,
    error: str = "",
) -> ServerRequestCompletedEvent:
    return ServerRequestCompletedEvent(
        request_type=request_type,
        operation_id=command.operation_id,
        success=success,
        status_code=status_code,
        error=error,
    )


def write(address: int, value: int) -> WriteRegistersCommand:
    return WriteRegistersCommand(slave_id=1, address=address, values=[value])


def start_active_batch(workflow: PrinterWorkflow) -> None:
    trigger = workflow.handle_event(poll(d0=1, d6=4))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)
    workflow.handle_event(
        completion(command, "start_batch", status_code=200, success=True)
    )
    workflow.handle_event(poll(sequence=2))


def test_start_batch_reads_box_count_and_marks_response_pending():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(poll(d0=1, d6=12))

    assert commands[0] == write(REGISTER_START_BATCH_RESPONSE, 0)
    assert isinstance(commands[1], StartBatchCommand)
    assert commands[1].box_count == 12
    assert len(commands[1].operation_id) == 32


def test_start_batch_success_starts_local_batch_then_responds_and_resets_request():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=2))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(command, "start_batch", status_code=204, success=True)
    )

    assert isinstance(commands[0], StartBatchSummaryCommand)
    assert isinstance(commands[1], InsertPlcTriggerEventCommand)
    assert commands[-2:] == [
        write(REGISTER_START_BATCH_RESPONSE, 1),
        write(REGISTER_START_BATCH_REQUEST, 0),
    ]
    assert workflow.batch_counters.active is True
    assert len(workflow.current_batch_id) == 32


def test_start_batch_maps_4xx_to_rejected_and_does_not_start_batch():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=0))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=422,
            success=False,
            error="box_count is invalid",
        )
    )

    assert commands == [
        write(REGISTER_START_BATCH_RESPONSE, 2),
        write(REGISTER_START_BATCH_REQUEST, 0),
    ]
    assert workflow.batch_counters.active is False


def test_start_batch_maps_server_and_transport_errors_to_technical_error():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=3))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(command, "start_batch", status_code=0, success=False, error="timeout")
    )

    assert commands == [
        write(REGISTER_START_BATCH_RESPONSE, 3),
        write(REGISTER_START_BATCH_REQUEST, 0),
    ]


def test_print_next_success_sets_pending_until_d2_acknowledges_label_success():
    workflow = PrinterWorkflow()
    start_active_batch(workflow)
    trigger = workflow.handle_event(poll(sequence=3, d1=1))
    command = trigger[1]
    assert isinstance(command, PrintNextCommand)

    completed = workflow.handle_event(
        completion(command, "print_next", status_code=200, success=True)
    )
    blocked_reprint = workflow.handle_event(poll(sequence=4, d1=0, d3=1))
    label_commands = workflow.handle_event(poll(sequence=5, d2=1, d3=1))

    assert isinstance(completed[0], InsertPlcTriggerEventCommand)
    assert completed[-2:] == [
        write(REGISTER_PRINT_NEXT_RESPONSE, 1),
        write(REGISTER_PRINT_NEXT_REQUEST, 0),
    ]
    assert blocked_reprint == []
    assert isinstance(label_commands[0], InsertPlcTriggerEventCommand)
    assert isinstance(label_commands[1], UpdateBatchSummaryCommand)
    assert label_commands[2:4] == [
        write(REGISTER_LABEL_SUCCESS_RESPONSE, 1),
        write(REGISTER_LABEL_SUCCESS_REQUEST, 0),
    ]
    assert label_commands[4] == write(REGISTER_REPRINT_RESPONSE, 0)
    assert isinstance(label_commands[5], RePrintCommand)
    assert workflow.batch_counters.label_success_count == 1


def test_d2_level_is_processed_once_until_plc_returns_to_zero():
    workflow = PrinterWorkflow()

    first = workflow.handle_event(poll(d2=1))
    repeated = workflow.handle_event(poll(sequence=2, d2=1))
    workflow.handle_event(poll(sequence=3, d2=0))
    second = workflow.handle_event(poll(sequence=4, d2=1))

    assert first[-2:] == [
        write(REGISTER_LABEL_SUCCESS_RESPONSE, 1),
        write(REGISTER_LABEL_SUCCESS_REQUEST, 0),
    ]
    assert repeated == []
    assert second[-2:] == first[-2:]


def test_end_batch_only_closes_local_batch_after_2xx():
    workflow = PrinterWorkflow()
    start_active_batch(workflow)
    failed_trigger = workflow.handle_event(poll(sequence=3, d4=1))
    failed_command = failed_trigger[1]
    assert isinstance(failed_command, EndBatchCommand)

    failed = workflow.handle_event(
        completion(failed_command, "end_batch", status_code=503, success=False)
    )
    assert failed == [
        write(REGISTER_END_BATCH_RESPONSE, 3),
        write(REGISTER_END_BATCH_REQUEST, 0),
    ]
    assert workflow.batch_counters.active is True

    workflow.handle_event(poll(sequence=4))
    success_trigger = workflow.handle_event(poll(sequence=5, d4=1))
    success_command = success_trigger[1]
    assert isinstance(success_command, EndBatchCommand)
    succeeded = workflow.handle_event(
        completion(success_command, "end_batch", status_code=200, success=True)
    )

    assert isinstance(succeeded[0], InsertPlcTriggerEventCommand)
    assert isinstance(succeeded[1], UpdateBatchSummaryCommand)
    assert succeeded[1].status == "done"
    assert succeeded[-2:] == [
        write(REGISTER_END_BATCH_RESPONSE, 1),
        write(REGISTER_END_BATCH_REQUEST, 0),
    ]
    assert workflow.batch_counters.active is False


def test_reset_has_priority_and_ignores_old_server_completion():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d1=1))
    old_command = trigger[1]
    assert isinstance(old_command, PrintNextCommand)

    reset_commands = workflow.handle_event(poll(sequence=2, d0=1, d1=1, d5=1))
    stale = workflow.handle_event(
        completion(old_command, "print_next", status_code=200, success=True)
    )

    assert reset_commands == [
        write(REGISTER_START_BATCH_REQUEST, 0),
        write(REGISTER_PRINT_NEXT_REQUEST, 0),
        write(REGISTER_LABEL_SUCCESS_REQUEST, 0),
        write(REGISTER_REPRINT_REQUEST, 0),
        write(REGISTER_RESET_RESPONSE, 1),
        write(REGISTER_RESET_REQUEST, 0),
    ]
    assert stale == []


def test_only_one_server_request_is_started_per_poll_using_priority_order():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(poll(d0=1, d1=1, d3=1, d4=1, d6=5))

    assert commands[0] == write(REGISTER_END_BATCH_RESPONSE, 0)
    assert isinstance(commands[1], EndBatchCommand)
