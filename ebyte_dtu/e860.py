# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Comandos AT del E860-DTU(X0X0-900SLxx)-V2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from ebyte_dtu.protocol import frequency_mhz

PC_BAUD = 115200
PC_PARITY = "8N1"
UART_BAUD_RATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
CHANNEL_MIN = 0
CHANNEL_MAX = 80
KEY_MAX = 65535
START_CHANNEL = 65
AT_TIMEOUT_S = 1.5

EXIT_AT = b"AT+EXAT\r\n"
RESTORE = b"AT+RESTORE\r\n"
REBOOT = b"AT+REBT\r\n"

READ_COMMANDS = (
    "VER",
    "DEV_TYPE",
    "SN",
    "WORK_ROLE",
    "WORK_MODE",
    "MATED_NUM",
    "MATED_DEV_TYPE",
    "AIR_SPEED",
    "UART",
    "KEY",
    "CHANNEL",
)

WORK_ROLES = ("Sin emparejar", "Maestro", "Esclavo")
WORK_MODES = ("Modo 1", "Modo 2")
_DEVICE_LABELS = {
    "未配对": "Sin emparejar",
    "主机": "Maestro",
    "从机": "Esclavo",
    "模式1": "Modo 1",
    "模式2": "Modo 2",
}
AIR_SPEEDS = ("2.4K", "9.6K")

_TEXT_FIELDS = {
    "VER": "version",
    "DEV_TYPE": "device_type",
    "SN": "serial_number",
    "WORK_ROLE": "work_role",
    "WORK_MODE": "work_mode",
    "MATED_NUM": "mated_count",
    "MATED_DEV_TYPE": "mated_model",
    "AIR_SPEED": "air_speed",
}


class AtError(Exception):
    """El equipo rechazó el comando o la respuesta no se entiende."""


class PasswordRequired(AtError):
    """El equipo respondió +ERR=-5 y hace falta AT+PASSWORDSET."""


class AtUnavailable(AtError):
    """El equipo respondió +ERR=-1: ese dato no aplica."""


@dataclass
class SwitchParams:
    version: str = ""
    device_type: str = ""
    serial_number: str = ""
    work_role: str = ""
    work_mode: str = ""
    mated_count: str = ""
    mated_model: str = ""
    air_speed: str = ""
    baud_rate: int = PC_BAUD
    uart_extra: str = ""
    channel: int = START_CHANNEL
    key: int = 0

    def validate(self) -> None:
        if self.baud_rate not in UART_BAUD_RATES:
            raise ValueError(f"Velocidad de serie no válida: {self.baud_rate}")
        if not CHANNEL_MIN <= self.channel <= CHANNEL_MAX:
            raise ValueError(
                f"El canal debe estar entre {CHANNEL_MIN} y {CHANNEL_MAX}."
            )
        if not 0 <= self.key <= KEY_MAX:
            raise ValueError(f"La clave debe estar entre 0 y {KEY_MAX}.")
        if any(mark in self.uart_extra for mark in ("\r", "\n")):
            raise ValueError("El resto de AT+UART no puede incluir un fin de línea.")

    def frequency_mhz(self) -> float:
        return frequency_mhz(self.channel)

    def apply_read(self, name: str, value: str) -> None:
        if name in _TEXT_FIELDS:
            setattr(self, _TEXT_FIELDS[name], value.strip())
            return
        if name == "UART":
            self.baud_rate, self.uart_extra = parse_uart(value)
            return
        if name == "CHANNEL":
            self.channel = parse_channel(value)
            return
        if name == "KEY":
            self.key = parse_key(value)
            return
        raise AtError(f"Comando no esperado: {name}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SwitchParams:
        known = {item.name for item in fields(cls)}
        missing = [name for name in known if name not in data]
        if missing:
            raise ValueError("Faltan campos en el archivo: " + ", ".join(missing))
        params = cls(**{name: data[name] for name in known})
        params.validate()
        return params


def default_params() -> SwitchParams:
    params = SwitchParams()
    params.validate()
    return params


def query_command(name: str) -> bytes:
    _check_name(name)
    return f"AT+{name}\r\n".encode("ascii")


def set_command(name: str, value: str) -> bytes:
    _check_name(name)
    if any(mark in value for mark in ("\r", "\n")):
        raise ValueError("El valor AT no puede incluir un fin de línea.")
    return f"AT+{name}={value}\r\n".encode("ascii")


def password_command(password: str) -> bytes:
    if not password or any(ord(char) < 33 or ord(char) > 126 for char in password):
        raise ValueError(
            "La contraseña de configuración debe ser ASCII imprimible, sin espacios."
        )
    return f"AT+PASSWORDSET={password}\r\n".encode("ascii")


def write_commands(params: SwitchParams) -> list[bytes]:
    """Graba canal y clave antes que la velocidad, para no cortar el enlace."""
    params.validate()
    return [
        set_command("CHANNEL", str(params.channel)),
        set_command("KEY", str(params.key)),
        set_command("UART", format_uart(params.baud_rate, params.uart_extra)),
    ]


def parse_response(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        text = payload.decode("ascii", errors="replace")
    else:
        text = payload
    lines = [
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    status = [line for line in lines if line.startswith("+OK") or line.startswith("+ERR")]
    if not status:
        shown = text.strip() or "(vacío)"
        raise AtError("Respuesta inesperada: " + shown)
    line = status[-1]
    if line == "+ERR=-5" or line.startswith("+ERR=-5"):
        raise PasswordRequired("El equipo pidió la contraseña de configuración.")
    if line == "+ERR=-1" or line.startswith("+ERR=-1"):
        raise AtUnavailable("El equipo no tiene ese dato.")
    if line.startswith("+ERR"):
        raise AtError("El equipo respondió " + line)
    if line == "+OK":
        return ""
    if line.startswith("+OK="):
        return line[4:].strip()
    raise AtError("Respuesta inesperada: " + line)


def parse_uart(value: str) -> tuple[int, str]:
    head, separator, extra = value.strip().partition(",")
    if not head.strip():
        raise AtError("AT+UART no trajo la velocidad.")
    try:
        baud = int(head.strip())
    except ValueError as exc:
        raise AtError(f"Velocidad de UART no válida: {head.strip()}") from exc
    if baud not in UART_BAUD_RATES:
        raise AtError(f"Velocidad de UART no válida: {baud}")
    return baud, extra.strip() if separator else ""


def format_uart(baud: int, extra: str) -> str:
    if baud not in UART_BAUD_RATES:
        raise ValueError(f"Velocidad de serie no válida: {baud}")
    if extra:
        return f"{baud},{extra}"
    return str(baud)


def parse_channel(value: str) -> int:
    try:
        channel = int(value.strip())
    except ValueError as exc:
        raise AtError(f"Canal no válido: {value.strip()}") from exc
    if not CHANNEL_MIN <= channel <= CHANNEL_MAX:
        raise AtError(f"El canal debe estar entre {CHANNEL_MIN} y {CHANNEL_MAX}.")
    return channel


def parse_key(value: str) -> int:
    try:
        key = int(value.strip())
    except ValueError as exc:
        raise AtError(f"Clave no válida: {value.strip()}") from exc
    if not 0 <= key <= KEY_MAX:
        raise AtError(f"La clave debe estar entre 0 y {KEY_MAX}.")
    return key


def indexed_label(value: str, labels: tuple[str, ...]) -> str:
    """Traduce un índice o el texto chino del equipo a la etiqueta en español."""
    text = value.strip()
    if text in _DEVICE_LABELS:
        return _DEVICE_LABELS[text]
    if text in labels:
        return text
    if text.isdigit():
        index = int(text)
        if 0 <= index < len(labels):
            return labels[index]
    return text


def format_at(data: bytes) -> str:
    return data.decode("ascii", errors="replace").replace("\r", "\\r").replace("\n", "\\n")


def _check_name(name: str) -> None:
    if not name or any(not char.isalnum() and char != "_" for char in name):
        raise ValueError(f"Nombre de comando no válido: {name}")
