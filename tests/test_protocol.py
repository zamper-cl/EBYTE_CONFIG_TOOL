# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import unittest

from ebyte_dtu.protocol import (
    AIR_RATES_KBPS,
    BAUD_RATES,
    MODEL_SL22,
    MODEL_SL30,
    PACKET_SIZES,
    WOR_CYCLES_MS,
    ProtocolError,
    RadioParams,
    build_pid_command,
    build_read_command,
    build_write_command,
    ensure_echo,
    factory_params,
    format_bytes,
    frequency_mhz,
    lowest_channel_above,
    model_from_pid,
    parse_pid_response,
    parse_register_response,
)


def screenshot_params() -> RadioParams:
    """Valores visibles en la captura de RF_Setting para el 900SL30."""
    return RadioParams(
        model=MODEL_SL30,
        address=33,
        net_id=0,
        baud_rate=9600,
        parity="8N1",
        air_rate_kbps=2.4,
        packet_size=64,
        channel_rssi=False,
        power_index=3,
        channel=80,
        packet_rssi=False,
        fixed_point=False,
        relay=False,
        lbt=False,
        wor_transmitter=False,
        wor_cycle_ms=2000,
        key=45612,
    )


class ProtocolTest(unittest.TestCase):
    def test_screenshot_registers(self):
        params = screenshot_params()
        self.assertEqual(params.to_registers().hex(), "00210062835003b22c")
        self.assertEqual(params.power_dbm(), 21)
        self.assertEqual(params.frequency_mhz(), 930.125)
        self.assertEqual(frequency_mhz(80), 930.125)

    def test_screenshot_roundtrip_and_write_frame(self):
        params = screenshot_params()
        restored = RadioParams.from_registers(params.to_registers(), model=MODEL_SL30)
        self.assertEqual(restored, params)
        frame = build_write_command(params)
        self.assertEqual(frame[:3], bytes((0xC0, 0x00, 0x09)))
        self.assertEqual(frame[3:], params.to_registers())
        self.assertIn("0x62", format_bytes(frame))

    def test_factory_defaults(self):
        params = factory_params(MODEL_SL22)
        self.assertEqual(params.model, MODEL_SL22)
        self.assertEqual(params.channel, 0x17)
        self.assertEqual(params.baud_rate, 9600)
        self.assertEqual(params.parity, "8N1")
        self.assertEqual(params.air_rate_kbps, 2.4)
        self.assertEqual(params.packet_size, 240)
        self.assertEqual(params.power_index, 0)
        self.assertEqual(params.power_dbm(), 22)
        self.assertEqual(params.to_registers().hex(), "000000620017000000")
        self.assertEqual(factory_params().power_dbm(), 30)

    def test_option_roundtrip(self):
        for baud in BAUD_RATES:
            for parity in ("8N1", "8O1", "8E1"):
                for air in AIR_RATES_KBPS:
                    original = RadioParams(
                        baud_rate=baud, parity=parity, air_rate_kbps=air
                    )
                    self.assertEqual(
                        RadioParams.from_registers(original.to_registers()), original
                    )
        for size in PACKET_SIZES:
            for power in range(4):
                for cycle in WOR_CYCLES_MS:
                    original = RadioParams(
                        packet_size=size,
                        power_index=power,
                        wor_cycle_ms=cycle,
                        channel_rssi=True,
                        packet_rssi=True,
                        fixed_point=True,
                        relay=True,
                        lbt=True,
                        wor_transmitter=True,
                        reg1_reserved=0b101,
                        address=65535,
                        net_id=255,
                        channel=83,
                        key=65535,
                    )
                    self.assertEqual(
                        RadioParams.from_registers(original.to_registers()), original
                    )

    def test_parity_11_decodes_as_8n1(self):
        params = factory_params()
        raw = bytearray(params.to_registers())
        raw[3] = (raw[3] & 0b11100111) | (0b11 << 3)
        restored = RadioParams.from_registers(bytes(raw))
        self.assertEqual(restored.parity, "8N1")
        self.assertEqual(restored.to_registers()[3] & 0b11000, 0)

    def test_invalid_channel_and_air_code(self):
        params = factory_params()
        params.channel = 84
        with self.assertRaises(ValueError):
            params.to_registers()
        raw = bytearray(factory_params().to_registers())
        raw[3] = raw[3] & 0b11111000  # bits 2-0 = 000, código de aire no definido
        with self.assertRaises(ProtocolError):
            RadioParams.from_registers(bytes(raw))

    def test_error_frame_and_echo(self):
        with self.assertRaises(ProtocolError):
            parse_register_response(bytes((0xFF, 0xFF, 0xFF)))
        with self.assertRaises(ProtocolError):
            parse_pid_response(bytes((0xFF, 0xFF, 0xFF)))
        with self.assertRaises(ProtocolError):
            parse_register_response(bytes((0xC1, 0x00, 0x09, 0x00)))

        sent = screenshot_params().to_registers()
        response = bytes((0xC1, 0x00, 0x09)) + sent
        self.assertEqual(parse_register_response(response), sent)
        ensure_echo(sent, response)
        with self.assertRaises(ProtocolError):
            ensure_echo(sent, bytes((0xC1, 0x00, 0x09)) + bytes(9))

    def test_commands_and_pid(self):
        self.assertEqual(build_read_command(), bytes((0xC1, 0x00, 0x09)))
        self.assertEqual(build_pid_command(), bytes((0xC1, 0x80, 0x07)))
        pid = b"900SL30"
        self.assertEqual(parse_pid_response(bytes((0xC1, 0x80, 0x07)) + pid), pid)
        self.assertEqual(model_from_pid(pid), MODEL_SL30)
        self.assertEqual(model_from_pid(b"xxSL22x"), MODEL_SL22)
        self.assertIsNone(model_from_pid(bytes(7)))

    def test_json_roundtrip(self):
        params = screenshot_params()
        self.assertEqual(RadioParams.from_dict(params.to_dict()), params)
        broken = params.to_dict()
        del broken["key"]
        with self.assertRaises(ValueError):
            RadioParams.from_dict(broken)

    def test_lowest_channel_above_915_mhz(self):
        channel = lowest_channel_above()
        self.assertEqual(channel, 65)
        self.assertGreater(frequency_mhz(channel), 915)
        self.assertLessEqual(frequency_mhz(channel - 1), 915)
        self.assertEqual(frequency_mhz(channel), 915.125)


class E95WindowChannelTest(unittest.TestCase):
    def test_channel_starts_at_65_and_a_lower_value_does_not_stick(self):
        from PyQt6.QtWidgets import QApplication

        from ebyte_dtu.window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        try:
            self.assertEqual(window.channel_spin.value(), 65)
            self.assertEqual(window.channel_frequency.text(), "915.125 MHz")
            window._allow_any_channel = False
            window.apply_params(RadioParams(channel=18))
            self.assertEqual(window.channel_spin.value(), 65)
            self.assertEqual(window.channel_frequency.text(), "915.125 MHz")
            window._allow_any_channel = True
            window.apply_params(RadioParams(channel=18))
            self.assertEqual(window.channel_spin.value(), 18)
        finally:
            window.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
