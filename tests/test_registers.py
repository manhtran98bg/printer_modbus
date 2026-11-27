from __future__ import annotations

from src.infrastructure.modbus import registers


def test_register_addresses():
    assert registers.REGISTER_START_BATCH_REQUEST == 0
    assert registers.REGISTER_PRINT_NEXT_REQUEST == 1
    assert registers.REGISTER_LABEL_SUCCESS_REQUEST == 2
    assert registers.REGISTER_REPRINT_REQUEST == 3
    assert registers.REGISTER_END_BATCH_REQUEST == 4
    assert registers.REGISTER_RESET_REQUEST == 5
    assert registers.REGISTER_BOX_COUNT == 6
    assert registers.REGISTER_START_BATCH_RESPONSE == 10
    assert registers.REGISTER_PRINT_NEXT_RESPONSE == 11
    assert registers.REGISTER_LABEL_SUCCESS_RESPONSE == 12
    assert registers.REGISTER_REPRINT_RESPONSE == 13
    assert registers.REGISTER_END_BATCH_RESPONSE == 14
    assert registers.REGISTER_RESET_RESPONSE == 15
    assert registers.REGISTER_AUTOBOX_COUNT == 18
