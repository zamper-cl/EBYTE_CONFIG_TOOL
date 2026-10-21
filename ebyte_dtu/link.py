# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Armado de tramas de enlace: texto, hexadecimal, CRC Modbus y ping-pong."""

from __future__ import annotations

PING = b"ping"
PONG = b"pong"
PING_TIMEOUT_S = 3.0
_MIN_SILENCE_S = 0.015


class LinkError(ValueError):
    """El texto o el hexadecimal no se puede convertir en bytes."""


def modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_modbus_crc(data: bytes) -> bytes:
    crc = modbus_crc(data)
    return data + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def modbus_crc_status(frame: bytes) -> bool | None:
    """True si el CRC cierra, False si no, None si el marco es demasiado corto."""
    if len(frame) < 4:
        return None
    return modbus_crc(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


def silence_seconds(baud: int) -> float:
    """Mayor entre 15 ms y 3,5 tiempos de carácter (11 bits)."""
    if baud <= 0:
        raise ValueError("El baud rate tiene que ser mayor que cero.")
    character = 11 / baud
    return max(_MIN_SILENCE_S, 3.5 * character)


def parse_hex(text: str) -> bytes:
    stripped = text.strip()
    if not stripped:
        raise LinkError("No hay datos para enviar.")
    tokens = stripped.replace(",", " ").split()
    if len(tokens) == 1 and _is_hex_digits(tokens[0]):
        if len(tokens[0]) % 2:
            raise LinkError("El hexadecimal debe tener una cantidad par de dígitos.")
        return bytes.fromhex(tokens[0])
    out = bytearray()
    for token in tokens:
        item = token[2:] if token.lower().startswith("0x") else token
        if len(item) == 0 or len(item) > 2 or not _is_hex_digits(item):
            raise LinkError(f"Byte hexadecimal no válido: {token}")
        out.append(int(item, 16))
    return bytes(out)


def encode_text(text: str) -> bytes:
    if text == "":
        raise LinkError("No hay datos para enviar.")
    try:
        return text.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise LinkError("El texto tiene un carácter que no cabe en un byte.") from exc


def payload_from_input(text: str, *, hexadecimal: bool, add_crc: bool) -> bytes:
    data = parse_hex(text) if hexadecimal else encode_text(text)
    if not data:
        raise LinkError("No hay datos para enviar.")
    if add_crc:
        return append_modbus_crc(data)
    return data


def is_ping(frame: bytes) -> bool:
    return frame.strip(b"\r\n\x00 ") == PING


def is_pong(frame: bytes) -> bool:
    return frame.strip(b"\r\n\x00 ") == PONG


def format_frame(frame: bytes) -> str:
    hex_part = " ".join(f"{byte:02X}" for byte in frame)
    ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in frame)
    crc = modbus_crc_status(frame)
    if crc is True:
        crc_text = "  CRC Modbus OK"
    elif crc is False:
        crc_text = "  CRC Modbus incorrecto"
    else:
        crc_text = ""
    return f"{hex_part}  |  {ascii_part}{crc_text}"


def _is_hex_digits(text: str) -> bool:
    return bool(text) and all(char in "0123456789abcdefABCDEF" for char in text)
