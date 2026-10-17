import struct
from pathlib import Path

HERE = Path(__file__).parent
STAMP = bytes([26, 10, 16, 10, 0, 0])


def summary():
    b = bytearray(98)
    b[:2] = b"\x31\x02"
    b[2:8] = STAMP
    b[8:14] = bytes([26, 10, 16, 10, 2, 0])
    b[44:60] = b"ET525A-TEST00001"
    struct.pack_into("<H", b, 40, 2)
    struct.pack_into("<H", b, 60, 1)
    b[62:68] = STAMP
    b[-1] = 0xA5
    return bytes(b)


def minutes():
    b = bytearray(22)
    struct.pack_into("<HH", b, 0, 60, 40)
    b[-1] = 0xFE
    return STAMP + struct.pack("<H", 2) + bytes(b) * 2


def fixture(root):
    p = root / "s"
    p.mkdir()
    (p / "0000001s.bys").write_bytes(summary())
    (p / "0000001m.bys").write_bytes(minutes())
    return p
