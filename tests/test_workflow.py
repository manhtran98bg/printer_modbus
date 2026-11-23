from __future__ import annotations

import re

from src.application.events import (
    ModbusPollEvent,
    ModbusWriteEvent,
    ServerRequestCompletedEvent,
)
from src.application.workflow import PrinterWorkflow
from src.infrastructure.database.commands import (
    InsertPlcTriggerEventCommand,
    StartBatchSummaryCommand,
    UpdateBatchSummaryCommand,
    UpsertCommunicationEventCommand,
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
    payload: dict[str, object] | None = None,
) -> ServerRequestCompletedEvent:
    return ServerRequestCompletedEvent(
        request_type=request_type,
        operation_id=command.operation_id,
        success=success,
        status_code=status_code,
        error=error,
        payload=payload,
    )


def write(address: int, value: int) -> WriteRegistersCommand:
    return WriteRegistersCommand(slave_id=1, address=address, values=[value])


def writes(commands: list[object]) -> list[WriteRegistersCommand]:
    return [command for command in commands if isinstance(command, WriteRegistersCommand)]


def assert_write(command: object, address: int, value: int) -> None:
    assert isinstance(command, WriteRegistersCommand)
    assert command.address == address
    assert command.values == [value]


def start_active_batch(workflow: PrinterWorkflow) -> None:
    trigger = workflow.handle_event(poll(d0=1, d6=4))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)
    workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=200,
            success=True,
            payload={
                "metaData": {
                    "machine_id": "M16-02",
                    "order_id": "ORD-407038",
                }
            },
        )
    )
    workflow.handle_event(poll(sequence=2))


def test_start_batch_reads_box_count_and_marks_response_pending():
    workflow = PrinterWorkflow(use_d6_box_count=True)

    commands = workflow.handle_event(poll(d0=1, d6=12))

    assert commands[0] == write(REGISTER_START_BATCH_RESPONSE, 0)
    assert isinstance(commands[1], StartBatchCommand)
    assert commands[1].box_count == 12
    assert len(commands[1].operation_id) == 32


def test_start_batch_sends_zero_when_d6_box_count_is_disabled():
    workflow = PrinterWorkflow(use_d6_box_count=False)

    commands = workflow.handle_event(poll(d0=1, d6=12))

    assert isinstance(commands[1], StartBatchCommand)
    assert commands[1].box_count == 0
    dashboard_event = commands[2]
    assert isinstance(dashboard_event, UpsertCommunicationEventCommand)
    assert dashboard_event.box_count == 0


def test_start_batch_success_starts_local_batch_then_responds_and_resets_request():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=2))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=204,
            success=True,
            payload={
                "metaData": {
                    "machine_id": "M16-02",
                    "order_id": "ORD-407038",
                }
            },
        )
    )

    assert isinstance(commands[0], StartBatchSummaryCommand)
    assert isinstance(commands[1], InsertPlcTriggerEventCommand)
    response_writes = writes(commands)
    assert_write(response_writes[-2], REGISTER_START_BATCH_RESPONSE, 1)
    assert_write(response_writes[-1], REGISTER_START_BATCH_REQUEST, 0)
    assert workflow.batch_counters.active is True
    assert re.fullmatch(
        r"M16-02_ORD-407038_\d{14}",
        workflow.current_batch_id,
    )
    assert commands[0].batch_id == workflow.current_batch_id


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

    assert len(commands) == 2
    assert_write(commands[0], REGISTER_START_BATCH_RESPONSE, 2)
    assert_write(commands[1], REGISTER_START_BATCH_REQUEST, 0)
    assert workflow.batch_counters.active is False


def test_start_batch_maps_already_started_mes_error_to_operator_message():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=4))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=404,
            success=False,
            error='No print history with status "new" found',
            payload={
                "statusCode": 404,
                "message": 'No print history with status "new" found',
            },
        )
    )
    response_write = writes(commands)[0]
    database_commands = workflow.handle_event(
        ModbusWriteEvent(
            sequence=2,
            slave_id=1,
            address=response_write.address,
            values=response_write.values,
            metadata=response_write.metadata,
        )
    )

    dashboard_event = database_commands[0]
    assert isinstance(dashboard_event, UpsertCommunicationEventCommand)
    assert dashboard_event.status == "rejected"
    assert dashboard_event.message == "Lệnh in này đã được bắt đầu trước đó"


def test_start_batch_maps_server_and_transport_errors_to_technical_error():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=3))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    commands = workflow.handle_event(
        completion(command, "start_batch", status_code=0, success=False, error="timeout")
    )

    assert len(commands) == 2
    assert_write(commands[0], REGISTER_START_BATCH_RESPONSE, 3)
    assert_write(commands[1], REGISTER_START_BATCH_REQUEST, 0)


def test_dashboard_operation_is_completed_after_response_register_write():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=3))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    completion_commands = workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=422,
            success=False,
            error="Không có lệnh tem đang chờ",
        )
    )
    response_write = writes(completion_commands)[0]
    database_commands = workflow.handle_event(
        ModbusWriteEvent(
            sequence=2,
            slave_id=1,
            address=response_write.address,
            values=response_write.values,
            metadata=response_write.metadata,
        )
    )

    assert len(database_commands) == 1
    dashboard_event = database_commands[0]
    assert isinstance(dashboard_event, UpsertCommunicationEventCommand)
    assert dashboard_event.operation_id == command.operation_id
    assert dashboard_event.status == "rejected"
    assert dashboard_event.http_status == 422
    assert dashboard_event.response_register == REGISTER_START_BATCH_RESPONSE
    assert dashboard_event.response_value == 2
    assert dashboard_event.message == "Không có lệnh tem đang chờ"


def test_start_batch_success_log_includes_mes_identity_and_box_count():
    workflow = PrinterWorkflow(use_d6_box_count=True)
    trigger = workflow.handle_event(poll(d0=1, d6=4))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    completion_commands = workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=200,
            success=True,
            payload={
                "msg": "Batch started successfully",
                "metaData": {
                    "order_id": "ORD-407038",
                    "machine_id": "M16-02",
                },
            },
        )
    )
    response_write = writes(completion_commands)[-2]
    database_commands = workflow.handle_event(
        ModbusWriteEvent(
            sequence=2,
            slave_id=1,
            address=response_write.address,
            values=response_write.values,
            metadata=response_write.metadata,
        )
    )

    dashboard_event = database_commands[0]
    assert isinstance(dashboard_event, UpsertCommunicationEventCommand)
    assert dashboard_event.message == (
        "Order ID: ORD-407038 · Machine ID: M16-02 · Box count: 4"
    )
    assert re.fullmatch(
        r"M16-02_ORD-407038_\d{14}",
        workflow.current_batch_id,
    )


def test_batch_id_normalizes_machine_and_order_id():
    workflow = PrinterWorkflow()
    trigger = workflow.handle_event(poll(d0=1, d6=4))
    command = trigger[1]
    assert isinstance(command, StartBatchCommand)

    workflow.handle_event(
        completion(
            command,
            "start_batch",
            status_code=200,
            success=True,
            payload={
                "metaData": {
                    "machine_id": " M16 / 02 ",
                    "order_id": "ORD 407/038",
                }
            },
        )
    )

    assert re.fullmatch(
        r"M16-02_ORD-407-038_\d{14}",
        workflow.current_batch_id,
    )


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
    completed_writes = writes(completed)
    assert_write(completed_writes[-2], REGISTER_PRINT_NEXT_RESPONSE, 1)
    assert_write(completed_writes[-1], REGISTER_PRINT_NEXT_REQUEST, 0)
    assert blocked_reprint == []
    assert isinstance(label_commands[0], InsertPlcTriggerEventCommand)
    assert isinstance(label_commands[1], UpdateBatchSummaryCommand)
    label_writes = writes(label_commands)
    assert_write(label_writes[0], REGISTER_LABEL_SUCCESS_RESPONSE, 1)
    assert_write(label_writes[1], REGISTER_LABEL_SUCCESS_REQUEST, 0)
    assert_write(label_writes[2], REGISTER_REPRINT_RESPONSE, 0)
    assert any(isinstance(command, RePrintCommand) for command in label_commands)
    assert workflow.batch_counters.label_success_count == 1


def test_d2_level_is_processed_once_until_plc_returns_to_zero():
    workflow = PrinterWorkflow()

    first = workflow.handle_event(poll(d2=1))
    repeated = workflow.handle_event(poll(sequence=2, d2=1))
    workflow.handle_event(poll(sequence=3, d2=0))
    second = workflow.handle_event(poll(sequence=4, d2=1))

    first_writes = writes(first)
    assert_write(first_writes[-2], REGISTER_LABEL_SUCCESS_RESPONSE, 1)
    assert_write(first_writes[-1], REGISTER_LABEL_SUCCESS_REQUEST, 0)
    assert repeated == []
    second_writes = writes(second)
    assert_write(second_writes[-2], REGISTER_LABEL_SUCCESS_RESPONSE, 1)
    assert_write(second_writes[-1], REGISTER_LABEL_SUCCESS_REQUEST, 0)


def test_end_batch_only_closes_local_batch_after_2xx():
    workflow = PrinterWorkflow()
    start_active_batch(workflow)
    failed_trigger = workflow.handle_event(poll(sequence=3, d4=1))
    failed_command = failed_trigger[1]
    assert isinstance(failed_command, EndBatchCommand)

    failed = workflow.handle_event(
        completion(failed_command, "end_batch", status_code=503, success=False)
    )
    assert len(failed) == 2
    assert_write(failed[0], REGISTER_END_BATCH_RESPONSE, 3)
    assert_write(failed[1], REGISTER_END_BATCH_REQUEST, 0)
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
    succeeded_writes = writes(succeeded)
    assert_write(succeeded_writes[-2], REGISTER_END_BATCH_RESPONSE, 1)
    assert_write(succeeded_writes[-1], REGISTER_END_BATCH_REQUEST, 0)
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

    assert isinstance(reset_commands[0], UpsertCommunicationEventCommand)
    reset_writes = writes(reset_commands)
    expected = [
        (REGISTER_START_BATCH_REQUEST, 0),
        (REGISTER_PRINT_NEXT_REQUEST, 0),
        (REGISTER_LABEL_SUCCESS_REQUEST, 0),
        (REGISTER_REPRINT_REQUEST, 0),
        (REGISTER_RESET_RESPONSE, 1),
        (REGISTER_RESET_REQUEST, 0),
    ]
    for command, (address, value) in zip(reset_writes, expected, strict=True):
        assert_write(command, address, value)
    assert stale == []


def test_only_one_server_request_is_started_per_poll_using_priority_order():
    workflow = PrinterWorkflow()

    commands = workflow.handle_event(poll(d0=1, d1=1, d3=1, d4=1, d6=5))

    assert commands[0] == write(REGISTER_END_BATCH_RESPONSE, 0)
    assert isinstance(commands[1], EndBatchCommand)
