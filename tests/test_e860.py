# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ebyte_dtu.e860 import (
    AIR_SPEEDS,
    CHANNEL_MAX,
    EXIT_AT,
    KEY_MAX,
    PC_BAUD,
    REBOOT,
    RESTORE,
    START_CHANNEL,
    WORK_MODES,
    WORK_ROLES,
    AtError,
    AtUnavailable,
    PasswordRequired,
    SwitchParams,
    default_params,
    indexed_label,
    password_command,
    parse_channel,
    parse_key,
    parse_response,
    parse_uart,
    query_command,
    set_command,
    write_commands,
)


class AtCommandTest(unittest.TestCase):
    def test_query_and_set_frames(self):
        self.assertEqual(query_command("CHANNEL"), b"AT+CHANNEL\r\n")
        self.assertEqual(query_command("VER"), b"AT+VER\r\n")
        self.assertEqual(set_command("KEY", "42"), b"AT+KEY=42\r\n")
        self.assertEqual(EXIT_AT, b"AT+EXAT\r\n")
        self.assertEqual(RESTORE, b"AT+RESTORE\r\n")
        self.assertEqual(REBOOT, b"AT+REBT\r\n")

    def test_password_command_rejects_spaces_and_newlines(self):
        self.assertEqual(password_command("clave1"), b"AT+PASSWORDSET=clave1\r\n")
        with self.assertRaises(ValueError):
            password_command("clave 1")
        with self.assertRaises(ValueError):
            password_command("clave\r\n1")
        with self.assertRaises(ValueError):
            password_command("")

    def test_write_commands_keep_uart_tail_and_send_it_last(self):
        params = default_params()
        params.baud_rate = 9600
        params.uart_extra = "8,N,1"
        params.channel = 65
        params.key = 7
        commands = write_commands(params)
        self.assertEqual(
            commands,
            [
                b"AT+CHANNEL=65\r\n",
                b"AT+KEY=7\r\n",
                b"AT+UART=9600,8,N,1\r\n",
            ],
        )

    def test_write_uart_without_extra_fields(self):
        params = default_params()
        params.baud_rate = 115200
        params.uart_extra = ""
        self.assertEqual(write_commands(params)[-1], b"AT+UART=115200\r\n")


class AtResponseTest(unittest.TestCase):
    def test_parses_ok_value_and_ignores_the_echo(self):
        self.assertEqual(parse_response(b"AT+CHANNEL\r\n+OK=65\r\n"), "65")
        self.assertEqual(parse_response(b"\r\n+OK=FW-9251-0-10\r\n"), "FW-9251-0-10")
        self.assertEqual(parse_response("+OK"), "")
        self.assertEqual(parse_response("+OK=\r\n"), "")

    def test_error_and_password(self):
        with self.assertRaises(PasswordRequired):
            parse_response(b"+ERR=-5\r\n")
        with self.assertRaises(AtUnavailable):
            parse_response(b"\r\n+ERR=-1\r\n")
        with self.assertRaises(AtError):
            parse_response(b"\r\n+ERR=1\r\n")
        with self.assertRaises(AtError):
            parse_response(b"+ERR\r\n")
        with self.assertRaises(AtError):
            parse_response(b"")

    def test_uart_splits_the_baud_from_the_tail(self):
        self.assertEqual(parse_uart("9600,8,N,1"), (9600, "8,N,1"))
        self.assertEqual(parse_uart("115200"), (115200, ""))
        with self.assertRaises(AtError):
            parse_uart("300")

    def test_channel_and_key_limits(self):
        self.assertEqual(parse_channel("0"), 0)
        self.assertEqual(parse_channel("80"), CHANNEL_MAX)
        with self.assertRaises(AtError):
            parse_channel("81")
        self.assertEqual(parse_key("0"), 0)
        self.assertEqual(parse_key(str(KEY_MAX)), KEY_MAX)
        with self.assertRaises(AtError):
            parse_key(str(KEY_MAX + 1))

    def test_indexed_labels_follow_the_official_order(self):
        self.assertEqual(indexed_label("1", WORK_ROLES), "Maestro")
        self.assertEqual(indexed_label("未配对", WORK_ROLES), "Sin emparejar")
        self.assertEqual(indexed_label("0", WORK_MODES), "Modo 1")
        self.assertEqual(indexed_label("模式2", WORK_MODES), "Modo 2")
        self.assertEqual(indexed_label("1", AIR_SPEEDS), "9.6K")
        self.assertEqual(indexed_label("2.4K", AIR_SPEEDS), "2.4K")
        self.assertEqual(indexed_label("otro", WORK_ROLES), "otro")


class SwitchParamsTest(unittest.TestCase):
    def test_default_channel_is_915_mhz(self):
        params = default_params()
        self.assertEqual(params.channel, START_CHANNEL)
        self.assertEqual(params.baud_rate, PC_BAUD)
        self.assertEqual(params.frequency_mhz(), 915.125)
        self.assertEqual(SwitchParams(channel=80).frequency_mhz(), 930.125)

    def test_apply_read_and_json_roundtrip(self):
        params = SwitchParams()
        params.apply_read("VER", "1.0")
        params.apply_read("DEV_TYPE", "E860-DTU(2020-900SL22)-V2")
        params.apply_read("SN", "ABC")
        params.apply_read("WORK_ROLE", "1")
        params.apply_read("WORK_MODE", "0")
        params.apply_read("MATED_NUM", "2")
        params.apply_read("MATED_DEV_TYPE", "E860-DTU(2020-900SL30)-V2")
        params.apply_read("AIR_SPEED", "2.4K")
        params.apply_read("UART", "9600,8,N,1")
        params.apply_read("KEY", "15")
        params.apply_read("CHANNEL", "70")
        restored = SwitchParams.from_dict(params.to_dict())
        self.assertEqual(restored, params)
        self.assertEqual(restored.uart_extra, "8,N,1")
        self.assertEqual(restored.channel, 70)
        self.assertEqual(indexed_label(restored.work_role, WORK_ROLES), "Maestro")

    def test_json_rejects_a_channel_outside_the_band(self):
        data = default_params().to_dict()
        data["channel"] = 81
        with self.assertRaises(ValueError):
            SwitchParams.from_dict(data)


class E860WindowTest(unittest.TestCase):
    def test_window_starts_at_channel_65_and_stops_at_80(self):
        from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QTabWidget

        from ebyte_dtu.__main__ import DeviceDialog
        from ebyte_dtu.e860_window import E860Window

        app = QApplication.instance() or QApplication([])
        window = E860Window()
        try:
            window.show()
            app.processEvents()
            self.assertEqual(window.channel_spin.value(), START_CHANNEL)
            self.assertEqual(window.channel_spin.maximum(), CHANNEL_MAX)
            window._allow_any_channel = False
            window.apply_params(SwitchParams(channel=0))
            self.assertEqual(window.channel_spin.value(), START_CHANNEL)
            self.assertEqual(window.channel_frequency.text(), "915.125 MHz")
            self.assertEqual(window.channel_frequency.text(), "915.125 MHz")
            self.assertEqual(window.port_baud_combo.currentData(), PC_BAUD)
            self.assertEqual(window.device_baud_combo.currentData(), PC_BAUD)
            self.assertFalse(window.enter_button.isEnabled())
            tabs = window.findChild(QTabWidget)
            self.assertEqual(tabs.tabText(1), "Ayuda")
            labels = [label.text() for label in window.findChildren(QLabel)]
            self.assertIn("Pareo de uno a uno", labels)
            self.assertIn("PWR", labels)
            self.assertTrue(any("Maestro: fijo." in text for text in labels))
            window._allow_any_channel = False
            window._apply_channel_range(10, keep_illegal=True)
            self.assertEqual(window.channel_spin.value(), 10)
            window._allow_any_channel = True
            window._apply_channel_range(10, keep_illegal=False)
            self.assertEqual(window.channel_spin.minimum(), 0)
            self.assertEqual(window.channel_spin.value(), 10)
            dialog = DeviceDialog()
            dialog.e860_button.click()
            self.assertEqual(dialog.choice, "e860")
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        finally:
            window.close()
            app.processEvents()
