# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Registros 00H–08H del E95-DTU(900SLxx-485)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

BASE_FREQUENCY_MHZ = 850.125
DECLARED_BAND_CHANNEL_MAX = 80
CHANNEL_MIN = 0
CHANNEL_MAX = 83
ADDRESS_MAX = 65535
NET_ID_MAX = 255
KEY_MAX = 65535

MODEL_SL30 = "E95-DTU(900SL30-485)"
MODEL_SL22 = "E95-DTU(900SL22-485)"
MODELS = (MODEL_SL30, MODEL_SL22)

# El mismo índice de bits (00…11) nombra potencias distintas según el modelo.
POWER_DBM: dict[str, tuple[int, int, int, int]] = {
    MODEL_SL30: (30, 27, 24, 21),
    MODEL_SL22: (22, 17, 13, 10),
}

BAUD_RATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
PARITIES = ("8N1", "8O1", "8E1")
AIR_RATES_KBPS = (2.4, 4.8, 9.6, 19.2, 38.4, 62.5)
PACKET_SIZES = (240, 128, 64, 32)
WOR_CYCLES_MS = (500, 1000, 1500, 2000, 2500, 3000, 3500, 4000)

_PARITY_TO_BITS = {"8N1": 0b00, "8O1": 0b01, "8E1": 0b10}
_BITS_TO_PARITY = {0b00: "8N1", 0b01: "8O1", 0b10: "8E1", 0b11: "8N1"}
_AIR_TO_BITS = {
    2.4: 0b010,
    4.8: 0b011,
    9.6: 0b100,
    19.2: 0b101,
    38.4: 0b110,
    62.5: 0b111,
}
_BITS_TO_AIR = {bits: rate for rate, bits in _AIR_TO_BITS.items()}

READ_COMMAND = bytes((0xC1, 0x00, 0x09))
PID_COMMAND = bytes((0xC1, 0x80, 0x07))
REGISTER_COUNT = 9
PID_LENGTH = 7
_ERROR_RESPONSE = bytes((0xFF, 0xFF, 0xFF))


class ProtocolError(Exception):
    """El radio rechazó el marco o la respuesta no coincide con el comando."""


@dataclass
class RadioParams:
    address: int = 0
    net_id: int = 0
    baud_rate: int = 9600
    parity: str = "8N1"
    air_rate_kbps: float = 2.4
    packet_size: int = 240
    channel_rssi: bool = False
    power_index: int = 0
    channel: int = 0x17
    packet_rssi: bool = False
    fixed_point: bool = False
    relay: bool = False
    lbt: bool = False
    wor_transmitter: bool = False
    wor_cycle_ms: int = 500
    key: int = 0
    model: str = MODEL_SL30
    reg1_reserved: int = 0

    def validate(self) -> None:
        if self.model not in POWER_DBM:
            raise ValueError(f"Modelo desconocido: {self.model}")
        if not 0 <= self.address <= ADDRESS_MAX:
            raise ValueError(f"La dirección debe estar entre 0 y {ADDRESS_MAX}.")
        if not 0 <= self.net_id <= NET_ID_MAX:
            raise ValueError(f"El NET ID debe estar entre 0 y {NET_ID_MAX}.")
        if self.baud_rate not in BAUD_RATES:
            raise ValueError(f"Velocidad de serie no válida: {self.baud_rate}")
        if self.parity not in _PARITY_TO_BITS:
            raise ValueError(f"Paridad no válida: {self.parity}")
        if self.air_rate_kbps not in _AIR_TO_BITS:
            raise ValueError(f"Velocidad de aire no válida: {self.air_rate_kbps}")
        if self.packet_size not in PACKET_SIZES:
            raise ValueError(f"Tamaño de paquete no válido: {self.packet_size}")
        if not 0 <= self.power_index <= 3:
            raise ValueError("El índice de potencia debe estar entre 0 y 3.")
        if not CHANNEL_MIN <= self.channel <= CHANNEL_MAX:
            raise ValueError(
                f"El canal debe estar entre {CHANNEL_MIN} y {CHANNEL_MAX}."
            )
        if not 0 <= self.key <= KEY_MAX:
            raise ValueError(f"La clave debe estar entre 0 y {KEY_MAX}.")
        if self.wor_cycle_ms not in WOR_CYCLES_MS:
            raise ValueError(f"Ciclo WOR no válido: {self.wor_cycle_ms}")
        if not 0 <= self.reg1_reserved <= 0b111:
            raise ValueError("Los bits reservados de REG1 no caben en 3 bits.")

    def frequency_mhz(self) -> float:
        return frequency_mhz(self.channel)

    def power_dbm(self) -> int:
        return POWER_DBM[self.model][self.power_index]

    def to_registers(self) -> bytes:
        self.validate()
        reg0 = (
            (BAUD_RATES.index(self.baud_rate) << 5)
            | (_PARITY_TO_BITS[self.parity] << 3)
            | _AIR_TO_BITS[self.air_rate_kbps]
        )
        reg1 = (
            (PACKET_SIZES.index(self.packet_size) << 6)
            | ((1 if self.channel_rssi else 0) << 5)
            | ((self.reg1_reserved & 0b111) << 2)
            | (self.power_index & 0b11)
        )
        reg3 = (
            ((1 if self.packet_rssi else 0) << 7)
            | ((1 if self.fixed_point else 0) << 6)
            | ((1 if self.relay else 0) << 5)
            | ((1 if self.lbt else 0) << 4)
            | ((1 if self.wor_transmitter else 0) << 3)
            | WOR_CYCLES_MS.index(self.wor_cycle_ms)
        )
        return bytes(
            (
                (self.address >> 8) & 0xFF,
                self.address & 0xFF,
                self.net_id & 0xFF,
                reg0,
                reg1,
                self.channel & 0xFF,
                reg3,
                (self.key >> 8) & 0xFF,
                self.key & 0xFF,
            )
        )

    @classmethod
    def from_registers(cls, data: bytes, model: str = MODEL_SL30) -> RadioParams:
        if len(data) != REGISTER_COUNT:
            raise ProtocolError(
                f"Se esperaban {REGISTER_COUNT} bytes de registro y llegaron {len(data)}."
            )
        reg0, reg1, reg3 = data[3], data[4], data[6]
        baud_bits = (reg0 >> 5) & 0b111
        parity_bits = (reg0 >> 3) & 0b11
        air_bits = reg0 & 0b111
        packet_bits = (reg1 >> 6) & 0b11
        wor_bits = reg3 & 0b111
        if air_bits not in _BITS_TO_AIR:
            raise ProtocolError(f"Código de velocidad de aire no válido: {air_bits:03b}")
        params = cls(
            address=(data[0] << 8) | data[1],
            net_id=data[2],
            baud_rate=BAUD_RATES[baud_bits],
            parity=_BITS_TO_PARITY[parity_bits],
            air_rate_kbps=_BITS_TO_AIR[air_bits],
            packet_size=PACKET_SIZES[packet_bits],
            channel_rssi=bool((reg1 >> 5) & 0b1),
            power_index=reg1 & 0b11,
            channel=data[5],
            packet_rssi=bool((reg3 >> 7) & 0b1),
            fixed_point=bool((reg3 >> 6) & 0b1),
            relay=bool((reg3 >> 5) & 0b1),
            lbt=bool((reg3 >> 4) & 0b1),
            wor_transmitter=bool((reg3 >> 3) & 0b1),
            wor_cycle_ms=WOR_CYCLES_MS[wor_bits],
            key=(data[7] << 8) | data[8],
            model=model,
            reg1_reserved=(reg1 >> 2) & 0b111,
        )
        params.validate()
        return params

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RadioParams:
        known = {item.name for item in fields(cls)}
        missing = [name for name in known if name not in data]
        if missing:
            raise ValueError("Faltan campos en el archivo: " + ", ".join(missing))
        params = cls(**{name: data[name] for name in known})
        params.validate()
        return params


def frequency_mhz(channel: int) -> float:
    return BASE_FREQUENCY_MHZ + channel


LEGAL_MIN_FREQUENCY_MHZ = 915.0


def lowest_channel_above(limit_mhz: float = LEGAL_MIN_FREQUENCY_MHZ) -> int:
    """Primer canal cuya frecuencia es mayor que limit_mhz."""
    for channel in range(CHANNEL_MIN, CHANNEL_MAX + 1):
        if frequency_mhz(channel) > limit_mhz:
            return channel
    raise ValueError(f"Ningún canal supera {limit_mhz} MHz.")


def frequency_text(channel: int) -> str:
    text = f"{frequency_mhz(channel):.3f} MHz"
    if channel > DECLARED_BAND_CHANNEL_MAX:
        text += " (fuera de la banda declarada, que termina en el canal 80)"
    return text


def factory_params(model: str = MODEL_SL30) -> RadioParams:
    """Valores de la tabla 6.3: REG0 0x62, canal 0x17, resto en cero."""
    params = RadioParams(model=model)
    params.validate()
    return params


def build_read_command() -> bytes:
    return READ_COMMAND


def build_write_command(params: RadioParams) -> bytes:
    return bytes((0xC0, 0x00, REGISTER_COUNT)) + params.to_registers()


def build_pid_command() -> bytes:
    return PID_COMMAND


def format_bytes(data: bytes) -> str:
    return " ".join(f"0x{byte:02x}" for byte in data)


def _reject_error_frame(response: bytes) -> None:
    if response[:3] == _ERROR_RESPONSE:
        raise ProtocolError("El radio respondió FF FF FF (formato incorrecto).")


def parse_register_response(response: bytes) -> bytes:
    _reject_error_frame(response)
    header = bytes((0xC1, 0x00, REGISTER_COUNT))
    if len(response) < 3 + REGISTER_COUNT or response[:3] != header:
        raise ProtocolError("Respuesta inesperada: " + format_bytes(response))
    return response[3 : 3 + REGISTER_COUNT]


def parse_pid_response(response: bytes) -> bytes:
    _reject_error_frame(response)
    if len(response) < 3 + PID_LENGTH or response[:3] != PID_COMMAND:
        raise ProtocolError("Respuesta de PID inesperada: " + format_bytes(response))
    return response[3 : 3 + PID_LENGTH]


def ensure_echo(sent: bytes, response: bytes) -> None:
    echo = parse_register_response(response)
    if echo != sent:
        raise ProtocolError("El radio no confirmó los mismos registros.")


def model_from_pid(pid: bytes) -> str | None:
    text = pid.decode("ascii", errors="ignore").upper()
    if "SL30" in text:
        return MODEL_SL30
    if "SL22" in text:
        return MODEL_SL22
    return None
