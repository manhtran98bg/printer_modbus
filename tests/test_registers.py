from __future__ import annotations

from src.infrastructure.modbus import registers


def test_register_addresses():
    assert registers.REGISTER_BATCH_STATE == 0
    assert registers.REGISTER_PRINT_NEXT_REQUEST == 1
    assert registers.REGISTER_ATTACK_LABEL_STATE == 2
    assert registers.REGISTER_RE_PRINT_REQUEST == 3
    assert registers.REGISTER_ATTACK_BATCH_DONE == 4
    assert registers.REGISTER_PENDING_RESET == 5
    assert registers.REGISTER_BATCH_STATE_ACK == 10
    assert registers.REGISTER_PRINT_NEXT_ACK == 11
    assert registers.REGISTER_ATTACK_LABEL_ACK == 12
    assert registers.REGISTER_RE_PRINT_ACK == 13
    assert registers.REGISTER_ATTACK_BATCH_ACK == 14
    assert registers.REGISTER_BATCH_SEQUENCE_ID == 17
    assert registers.REGISTER_BATCH_LABEL_COUNT == 18
