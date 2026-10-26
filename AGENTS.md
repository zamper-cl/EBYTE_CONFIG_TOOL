# E95-DTU and E860-DTU configurator

PyQt6 program for the E95-DTU(900SL22-485), E95-DTU(900SL30-485), and E860-DTU(X0X0-900SLxx)-V2 on Linux. Startup asks which device to configure.

## Run and test

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ebyte_dtu
.venv/bin/python -m unittest discover -s tests -v
```

The system Python is externally managed. Install dependencies inside `.venv`. The interface has no browser: check window changes with `QT_QPA_PLATFORM=offscreen`.

## Code

- `ebyte_dtu/protocol.py`: E95 registers `00H`–`08H`, packing, and frequency `850.125 + channel` MHz.
- `ebyte_dtu/e860.py`: E860 AT commands. PC port defaults to 115200 8N1. Writes channel, key, then UART baud. Channel maximum is 80.
- `ebyte_dtu/serial_session.py`: serial port. The E95 Configuration and Link tabs share one session. The E860 window has its own.
- `ebyte_dtu/link.py`: text, hexadecimal, Modbus CRC16, and ping-pong (`ping` / `pong`). The E860 has no link tab.
- `ebyte_dtu/window.py`: E95 window, tabs, and the option for channels below 915 MHz.
- `ebyte_dtu/e860_window.py`: E860 window. It reads the same channel option.
- `ebyte_dtu/__main__.py`: dialog that chooses E95 or E860.
- `tests/`: protocol, E860 AT, link, and `ttyUSB` selection tests.

E95 reading and writing require configuration mode: M1 on, M0 off, PC port at 9600 8N1. Link and ping-pong require transparent mode, using the baud rate and parity stored in the radio.

E860 configuration is AT over RS485 at 115200 8N1. Queries are `AT+NAME` without `?`. `+++` and a bare `AT` get no reply. `+ERR=1` is a rejected command, `+ERR=-1` means that field does not apply, and `+ERR=-5` asks for `AT+PASSWORDSET`. Firmware upgrade stays in Ebyte's separate tool.

The startup channel is 65 (915.125 MHz) for both devices. Without the channel option, the selector does not offer frequencies of 915 MHz or below. E95 factory values from the manual stay in `factory_params` and are not changed to move that startup channel. The E860 band ends at channel 80 (930.125 MHz).

## Keep separate

The project code is Copyright (C) 2026 Zamper.io and is under GPL-3.0 (`LICENSE`). `bin_ebyte/` holds the original Ebyte executable; do not modify it, relicense it, or publish it. Ebyte manuals and figures live in `docs/` and stay out of the repository. `docs/img/modo-config.jpeg` is an original photo and is included.
