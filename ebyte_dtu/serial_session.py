# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Puerto serie a 9600 8N1 para el modo configuración."""

from __future__ import annotations

import glob

import serial

CONFIG_BAUD = 9600
TIMEOUT_S = 1.0
_PORT_PATTERNS = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS*")
_PARITY = {
    "8N1": serial.PARITY_NONE,
    "8O1": serial.PARITY_ODD,
    "8E1": serial.PARITY_EVEN,
}


def list_ports() -> list[str]:
    ports: list[str] = []
    for pattern in _PORT_PATTERNS:
        ports.extend(sorted(glob.glob(pattern)))
    return ports


def preferred_port(ports: list[str], current: str | None = None) -> str | None:
    """Prefiere un ttyUSB. Conserva el actual si ya es uno de ellos."""
    usb = [port for port in ports if port.rsplit("/", 1)[-1].startswith("ttyUSB")]
    if current in usb:
        return current
    if usb:
        return usb[0]
    if current in ports:
        return current
    return ports[0] if ports else None


class SerialSession:
    def __init__(self) -> None:
        self._ser: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(
        self,
        port: str,
        baudrate: int = CONFIG_BAUD,
        parity: str = "8N1",
        timeout: float = TIMEOUT_S,
    ) -> None:
        if parity not in _PARITY:
            raise ValueError(f"Paridad no válida: {parity}")
        self.close()
        opened = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=_PARITY[parity],
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
        )
        self._ser = opened

    def configure(self, baudrate: int, parity: str, timeout: float) -> None:
        if not self.is_open or self._ser is None:
            raise RuntimeError("El puerto no está abierto.")
        if parity not in _PARITY:
            raise ValueError(f"Paridad no válida: {parity}")
        self._ser.baudrate = baudrate
        self._ser.parity = _PARITY[parity]
        self._ser.timeout = timeout

    def set_timeout(self, timeout: float) -> None:
        if self._ser is not None:
            self._ser.timeout = timeout

    def close(self) -> None:
        current = self._ser
        self._ser = None
        if current is not None and current.is_open:
            current.close()

    def write(self, data: bytes) -> None:
        if not self.is_open or self._ser is None:
            raise RuntimeError("El puerto no está abierto.")
        self._ser.write(data)
        self._ser.flush()

    def read_some(self) -> bytes:
        """Lee lo que ya llegó. Si no hay nada, espera el timeout y puede devolver b''."""
        if not self.is_open or self._ser is None:
            return b""
        waiting = self._ser.in_waiting
        if waiting:
            return self._ser.read(waiting)
        return self._ser.read(1)

    def transact(self, command: bytes) -> bytes:
        if not self.is_open or self._ser is None:
            raise RuntimeError("El puerto no está abierto.")
        expected = 3 + command[2]
        self._ser.reset_input_buffer()
        self._ser.write(command)
        self._ser.flush()
        buffer = bytearray()
        while len(buffer) < expected:
            chunk = self._ser.read(expected - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
            if buffer[:3] == b"\xff\xff\xff":
                return bytes(buffer[:3])
        if len(buffer) < expected:
            raise TimeoutError(
                f"Tiempo de espera agotado tras {TIMEOUT_S:.0f} s. "
                f"Se recibieron {len(buffer)} bytes."
            )
        return bytes(buffer)
