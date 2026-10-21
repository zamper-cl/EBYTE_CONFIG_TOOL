# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import unittest

from ebyte_dtu.serial_session import preferred_port


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
