# E95-DTU configurator

PyQt6 program for the E95-DTU(900SL22-485) and E95-DTU(900SL30-485) on Linux.

## Run and test

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ebyte_dtu
.venv/bin/python -m unittest discover -s tests -v
```

The system Python is externally managed. Install dependencies inside `.venv`. The interface has no browser: check window changes with `QT_QPA_PLATFORM=offscreen`.

## Code

- `ebyte_dtu/protocol.py`: registers `00H`–`08H`, packing, and frequency `850.125 + channel` MHz.
- `ebyte_dtu/serial_session.py`: serial port. The Configuration and Link tabs share one session.
- `ebyte_dtu/link.py`: text, hexadecimal, Modbus CRC16, and ping-pong (`ping` / `pong`).
- `ebyte_dtu/window.py`: window, tabs, and the option for channels below 915 MHz.
- `tests/`: protocol, link, and `ttyUSB` selection tests.

Reading and writing require configuration mode: M1 on, M0 off, PC port at 9600 8N1. Link and ping-pong require transparent mode, using the baud rate and parity stored in the radio.

The startup channel is 65 (915.125 MHz). Without the option on the last Configuration tab, the selector does not offer frequencies of 915 MHz or below. Factory values from the manual stay in `factory_params` and are not changed to move that startup channel.

## Keep separate

The project code is Copyright (C) 2026 Zamper.io and is under GPL-3.0 (`LICENSE`). `bin_ebyte/` holds the original Ebyte executable; do not modify it, relicense it, or publish it. Ebyte manuals and figures live in `docs/` and stay out of the repository. `docs/img/modo-config.jpeg` is an original photo and is included.
