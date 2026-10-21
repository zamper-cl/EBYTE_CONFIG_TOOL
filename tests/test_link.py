# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import unittest

from ebyte_dtu.link import (
    PING,
    PONG,
    LinkError,
    append_modbus_crc,
    encode_text,
    format_frame,
    is_ping,
    is_pong,
    parse_hex,
    payload_from_input,
    silence_seconds,
)


class LinkTest(unittest.TestCase):
    def test_modbus_crc_example(self):
        body = bytes.fromhex("01030000000A")
        self.assertEqual(append_modbus_crc(body).hex(), "01030000000ac5cd")
        framed = payload_from_input(
            "01 03 00 00 00 0A", hexadecimal=True, add_crc=True
        )
        self.assertEqual(framed.hex(), "01030000000ac5cd")
        self.assertIn("CRC Modbus OK", format_frame(framed))
        self.assertIn("CRC Modbus incorrecto", format_frame(body + b"\x00\x00"))
        self.assertNotIn("CRC", format_frame(b"abc"))

    def test_hex_parse(self):
        expected = bytes.fromhex("01030000000A")
        self.assertEqual(parse_hex("01 03 00 00 00 0A"), expected)
        self.assertEqual(parse_hex("01030000000A"), expected)
        self.assertEqual(parse_hex("0x01, 0x03"), bytes.fromhex("0103"))
        with self.assertRaises(LinkError):
            parse_hex("010")
        with self.assertRaises(LinkError):
            parse_hex("zz")

    def test_text_encoding(self):
        self.assertEqual(encode_text("ping"), PING)
        self.assertEqual(encode_text("ñ"), b"\xf1")
        with self.assertRaises(LinkError):
            encode_text("你")
        with self.assertRaises(LinkError):
            payload_from_input("", hexadecimal=False, add_crc=False)

    def test_ping_pong_detection(self):
        self.assertTrue(is_ping(b"ping"))
        self.assertTrue(is_ping(b"ping\r\n"))
        self.assertTrue(is_ping(b"\nping\n"))
        self.assertFalse(is_ping(PONG))
        self.assertFalse(is_ping(b"pingpong"))
        self.assertFalse(is_ping(bytes.fromhex("01030000000A")))
        self.assertTrue(is_pong(b"pong"))
        self.assertTrue(is_pong(b"pong\r\n"))
        self.assertFalse(is_pong(PING))

    def test_silence_gap(self):
        self.assertAlmostEqual(silence_seconds(1200), 3.5 * 11 / 1200)
        self.assertEqual(silence_seconds(115200), 0.015)
        self.assertEqual(silence_seconds(9600), 0.015)


if __name__ == "__main__":
    unittest.main()
