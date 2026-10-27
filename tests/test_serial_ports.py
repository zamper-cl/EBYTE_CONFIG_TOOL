# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import unittest

from ebyte_dtu.serial_session import _port_sort_key, preferred_port


class PreferredPortTest(unittest.TestCase):
    def test_selects_ttyusb_over_serial_ports(self):
        ports = ["/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyACM0"]
        self.assertEqual(preferred_port(ports, "/dev/ttyS0"), "/dev/ttyUSB0")
        self.assertEqual(preferred_port(ports, None), "/dev/ttyUSB0")

    def test_keeps_current_ttyusb(self):
        ports = ["/dev/ttyUSB0", "/dev/ttyUSB1"]
        self.assertEqual(preferred_port(ports, "/dev/ttyUSB1"), "/dev/ttyUSB1")

    def test_keeps_current_when_there_is_no_usb(self):
        ports = ["/dev/ttyS0", "/dev/ttyACM0"]
        self.assertEqual(preferred_port(ports, "/dev/ttyACM0"), "/dev/ttyACM0")
        self.assertEqual(preferred_port(ports, None), "/dev/ttyS0")
        self.assertIsNone(preferred_port([], None))

    def test_keeps_current_com_port(self):
        ports = ["COM1", "COM3", "COM10"]
        self.assertEqual(preferred_port(ports, "COM3"), "COM3")
        self.assertEqual(preferred_port(ports, None), "COM1")

    def test_com_ports_sort_by_number(self):
        names = ["COM10", "COM2", "COM1"]
        self.assertEqual(sorted(names, key=_port_sort_key), ["COM1", "COM2", "COM10"])
