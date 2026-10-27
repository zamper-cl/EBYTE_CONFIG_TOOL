# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Hilo de trabajo y ventana de configuración local."""

from __future__ import annotations

import json
import queue
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ebyte_dtu import __version__
from ebyte_dtu.link import (
    PING,
    PING_TIMEOUT_S,
    PONG,
    LinkError,
    format_frame,
    is_ping,
    is_pong,
    payload_from_input,
    silence_seconds,
)
from ebyte_dtu.protocol import (
    AIR_RATES_KBPS,
    BAUD_RATES,
    CHANNEL_MAX,
    CHANNEL_MIN,
    MODELS,
    PACKET_SIZES,
    PARITIES,
    POWER_DBM,
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
    frequency_text,
    lowest_channel_above,
    model_from_pid,
    parse_pid_response,
    parse_register_response,
)
from ebyte_dtu.serial_session import (
    CONFIG_BAUD,
    TIMEOUT_S,
    SerialSession,
    list_ports,
    preferred_port,
)


class RadioWorker(QThread):
    log_message = pyqtSignal(str)
    opened = pyqtSignal(str)
    closed = pyqtSignal()
    params_read = pyqtSignal(object, object)
    params_written = pyqtSignal()
    failed = pyqtSignal(str)
    settled = pyqtSignal()
    link_log = pyqtSignal(str)
    link_opened = pyqtSignal(str)
    link_closed = pyqtSignal()
    link_failed = pyqtSignal(str)
    link_frame = pyqtSignal(bytes)
    link_sent = pyqtSignal(bytes)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._session = SerialSession()
        self._port = ""
        self._baud = CONFIG_BAUD
        self._parity = "8N1"
        self._ping_pong = False
        self._rx_buf = bytearray()

    def submit(self, operation: str, payload: object = None) -> None:
        self._queue.put((operation, payload))

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            if self._session.is_open:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    try:
                        self._poll_link()
                    except Exception as exc:
                        self._drop_link(str(exc))
                    continue
            else:
                item = self._queue.get()
            if item is None:
                self._flush_rx()
                self._session.close()
                break
            operation, payload = item
            try:
                self._handle(operation, payload)
            except Exception as exc:
                if operation in {"open_link", "send_link", "set_ping_pong"}:
                    self.link_failed.emit(str(exc))
                    self.settled.emit()
                else:
                    self.failed.emit(str(exc))

    def _handle(self, operation: str, payload: object) -> None:
        if operation == "open":
            self._open_config(str(payload))
        elif operation == "close":
            self._close_port()
        elif operation == "read":
            self._read(str(payload))
        elif operation == "write":
            if not isinstance(payload, RadioParams):
                raise TypeError("Los parámetros a grabar no son válidos.")
            self._write(payload)
        elif operation == "open_link":
            port, baud, parity, ping_pong = payload  # type: ignore[misc]
            self._open_link(str(port), int(baud), str(parity), bool(ping_pong))
        elif operation == "send_link":
            if not isinstance(payload, bytes):
                raise TypeError("No hay bytes para enviar.")
            self._send_link(payload)
        elif operation == "set_ping_pong":
            self._ping_pong = bool(payload)
        else:
            raise RuntimeError(f"Operación desconocida: {operation}")

    def _open_config(self, port: str) -> None:
        self._ensure_port(port, CONFIG_BAUD, "8N1")

    def _open_link(self, port: str, baud: int, parity: str, ping_pong: bool) -> None:
        self._ping_pong = ping_pong
        self._ensure_port(port, baud, parity)

    def _ensure_port(self, port: str, baud: int, parity: str) -> None:
        timeout = silence_seconds(baud)
        already = (
            self._session.is_open
            and self._port == port
            and self._baud == baud
            and self._parity == parity
        )
        if already:
            self._announce(True)
            return
        if self._session.is_open and self._port == port:
            self._flush_rx()
            self._session.configure(baud, parity, timeout)
        else:
            if self._session.is_open:
                self._flush_rx()
                self._session.close()
            self._session.open(port, baudrate=baud, parity=parity, timeout=timeout)
            self._rx_buf.clear()
        self._port = port
        self._baud = baud
        self._parity = parity
        self._announce(False)

    def _announce(self, already: bool) -> None:
        self.opened.emit(self._port)
        self.link_opened.emit(f"{self._port} a {self._baud} bps {self._parity}")
        if already:
            return
        message = f"Puerto {self._port} abierto a {self._baud} bps {self._parity}."
        self.log_message.emit(message)
        self.link_log.emit(message)

    def _close_port(self) -> None:
        self._flush_rx()
        self._session.close()
        self._port = ""
        self.closed.emit()
        self.link_closed.emit()
        self.log_message.emit("Puerto cerrado.")
        self.link_log.emit("Puerto cerrado.")
        self.settled.emit()

    def _send_link(self, data: bytes) -> None:
        if not self._session.is_open:
            raise RuntimeError("El puerto no está abierto.")
        self._session.write(data)
        self.link_sent.emit(data)

    def _poll_link(self) -> None:
        chunk = self._session.read_some()
        if chunk:
            self._rx_buf.extend(chunk)
            return
        self._flush_rx()

    def _flush_rx(self) -> None:
        if not self._rx_buf:
            return
        frame = bytes(self._rx_buf)
        self._rx_buf.clear()
        self.link_frame.emit(frame)
        if self._ping_pong and is_ping(frame):
            self._session.write(PONG)
            self.link_sent.emit(PONG)

    def _drop_link(self, message: str) -> None:
        self._rx_buf.clear()
        self._port = ""
        self._session.close()
        self.closed.emit()
        self.link_closed.emit()
        self.link_failed.emit(message)
        self.settled.emit()

    def _exchange(self, command: bytes) -> bytes:
        self._session.set_timeout(TIMEOUT_S)
        try:
            self.log_message.emit("TX " + format_bytes(command))
            response = self._session.transact(command)
            self.log_message.emit("RX " + format_bytes(response))
            return response
        finally:
            if self._session.is_open:
                self._session.set_timeout(silence_seconds(self._baud))

    def _read(self, model: str) -> None:
        response = self._exchange(build_read_command())
        registers = parse_register_response(response)
        params = RadioParams.from_registers(registers, model=model)
        pid: bytes | None = None
        try:
            pid_response = self._exchange(build_pid_command())
            pid = parse_pid_response(pid_response)
        except (TimeoutError, ProtocolError, RuntimeError) as exc:
            self.log_message.emit(f"PID no disponible: {exc}")
        self.params_read.emit(params, pid)

    def _write(self, params: RadioParams) -> None:
        command = build_write_command(params)
        response = self._exchange(command)
        ensure_echo(params.to_registers(), response)
        self.log_message.emit("Parámetros grabados.")
        self.params_written.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Configurador E95-DTU {__version__}")
        self.resize(980, 720)
        self._loading = False
        self._port_open = False
        self._link_open = False
        self._busy = False
        self._reserved = 0
        self._waiting_pong = False
        self._allow_any_channel = False
        self._held_channel: int | None = None

        self._worker = RadioWorker()
        self._worker.log_message.connect(self._append_log)
        self._worker.opened.connect(self._on_opened)
        self._worker.closed.connect(self._on_closed)
        self._worker.params_read.connect(self._on_params_read)
        self._worker.params_written.connect(self._on_job_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.settled.connect(self._on_job_finished)
        self._worker.link_log.connect(self._append_link)
        self._worker.link_opened.connect(self._on_link_opened)
        self._worker.link_closed.connect(self._on_link_closed)
        self._worker.link_failed.connect(self._on_link_failed)
        self._worker.link_frame.connect(self._on_link_frame)
        self._worker.link_sent.connect(self._on_link_sent)
        self._worker.start()

        self._pong_timer = QTimer(self)
        self._pong_timer.setSingleShot(True)
        self._pong_timer.timeout.connect(self._pong_timeout)
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(5000)
        self._repeat_timer.timeout.connect(self._repeat_send)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        tabs = QTabWidget()
        tabs.addTab(self._build_config_tab(), "Configuración")
        tabs.addTab(self._build_link_tab(), "Enlace")
        tabs.addTab(self._build_help_tab(), "Ayuda")
        tabs.addTab(self._build_channel_policy_tab(), "Configuración")
        self._tabs = tabs
        tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(tabs)

        self._refresh_ports()
        self._load_channel_policy()
        self.apply_params(factory_params())
        self._apply_channel_range(lowest_channel_above(), keep_illegal=False)
        self._copy_link_settings()
        self._sync_port_buttons()
        self._sync_link_buttons()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._worker.stop()
        self._worker.wait(5000)
        super().closeEvent(event)

    def apply_params(self, params: RadioParams) -> None:
        self._loading = True
        try:
            self._select_combo(self.model_combo, params.model)
            self._refill_power()
            self._select_combo(self.baud_combo, params.baud_rate)
            self._select_combo(self.parity_combo, params.parity)
            self._select_combo(self.air_combo, params.air_rate_kbps)
            self._select_combo(self.packet_combo, params.packet_size)
            self._select_combo(self.wor_role_combo, params.wor_transmitter)
            self._select_combo(self.wor_cycle_combo, params.wor_cycle_ms)
            self._select_combo(self.power_combo, params.power_index)
            self._select_combo(self.mode_combo, params.fixed_point)
            self._select_combo(self.relay_combo, params.relay)
            self._sync_usage_from_relay(params.relay)
            self._select_combo(self.lbt_combo, params.lbt)
            self._select_combo(self.packet_rssi_combo, params.packet_rssi)
            self._select_combo(self.channel_rssi_combo, params.channel_rssi)
            self.address_spin.setValue(params.address)
            self._apply_channel_range(params.channel, keep_illegal=False)
            self.net_id_spin.setValue(params.net_id)
            self.key_spin.setValue(params.key)
            self._reserved = params.reg1_reserved
        finally:
            self._loading = False
        self._update_preview()

    def current_params(self) -> RadioParams:
        return RadioParams(
            address=self.address_spin.value(),
            net_id=self.net_id_spin.value(),
            baud_rate=self.baud_combo.currentData(),
            parity=self.parity_combo.currentData(),
            air_rate_kbps=self.air_combo.currentData(),
            packet_size=self.packet_combo.currentData(),
            channel_rssi=self.channel_rssi_combo.currentData(),
            power_index=self.power_combo.currentData(),
            channel=self.channel_spin.value(),
            packet_rssi=self.packet_rssi_combo.currentData(),
            fixed_point=self.mode_combo.currentData(),
            relay=self.relay_combo.currentData(),
            lbt=self.lbt_combo.currentData(),
            wor_transmitter=self.wor_role_combo.currentData(),
            wor_cycle_ms=self.wor_cycle_combo.currentData(),
            key=self.key_spin.value(),
            model=self.model_combo.currentData(),
            reg1_reserved=self._reserved,
        )

    def _build_config_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addLayout(self._build_port_row())
        root.addWidget(self._build_info_box())
        root.addLayout(self._build_buttons())
        root.addWidget(self._build_fields())

        notice = QLabel(
            "El radio debe estar en modo configuración (M1 encendido, M0 apagado). "
            "El puerto de la PC se abre siempre a 9600 8N1."
        )
        notice.setWordWrap(True)
        root.addWidget(notice)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Registro de TX/RX")
        self.log.setFont(_mono_font())
        self.log.setMinimumHeight(140)
        root.addWidget(self.log)
        return page

    def _build_link_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Puerto"))
        self.link_port_combo = QComboBox()
        self.link_port_combo.setMinimumWidth(220)
        port_row.addWidget(self.link_port_combo, 1)
        self.link_refresh_button = QPushButton("Actualizar")
        self.link_refresh_button.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.link_refresh_button)
        self.link_port_button = QPushButton("Abrir puerto")
        self.link_port_button.clicked.connect(self._toggle_link_port)
        port_row.addWidget(self.link_port_button)
        self.link_port_state = QLabel("Cerrado")
        port_row.addWidget(self.link_port_state)
        root.addLayout(port_row)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("Velocidad"))
        self.link_baud_combo = _combo(BAUD_RATES, lambda value: f"{value} bps")
        settings.addWidget(self.link_baud_combo)
        settings.addWidget(QLabel("Paridad"))
        self.link_parity_combo = _combo(PARITIES, str)
        settings.addWidget(self.link_parity_combo)
        self.copy_settings_button = QPushButton("Copiar de la configuración")
        self.copy_settings_button.clicked.connect(self._copy_link_settings)
        settings.addWidget(self.copy_settings_button)
        settings.addStretch(1)
        root.addLayout(settings)

        notice = QLabel(
            "El radio debe estar en modo transparente (M0 y M1 apagados). "
            "La velocidad y la paridad de este puerto tienen que coincidir con las del radio."
        )
        notice.setWordWrap(True)
        root.addWidget(notice)

        root.addWidget(QLabel("Datos a enviar"))
        self.payload_edit = QPlainTextEdit()
        self.payload_edit.setPlaceholderText("Texto, o hexadecimal como 01 03 00 00 00 0A")
        self.payload_edit.setFont(_mono_font())
        self.payload_edit.setMaximumHeight(80)
        self.payload_edit.textChanged.connect(self._update_link_preview)
        root.addWidget(self.payload_edit)

        mode_row = QHBoxLayout()
        self.link_text = QRadioButton("Texto")
        self.link_hex = QRadioButton("Hexadecimal")
        self.link_text.setChecked(True)
        self.link_text.toggled.connect(self._update_link_preview)
        self.link_hex.toggled.connect(self._update_link_preview)
        mode_row.addWidget(self.link_text)
        mode_row.addWidget(self.link_hex)
        self.crc_check = QCheckBox("Agregar CRC16 Modbus")
        self.crc_check.toggled.connect(self._update_link_preview)
        mode_row.addWidget(self.crc_check)
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self._send_payload)
        mode_row.addWidget(self.send_button)
        self.repeat_button = QPushButton("Enviar cada 5 segundos")
        self.repeat_button.clicked.connect(self._toggle_repeat)
        mode_row.addWidget(self.repeat_button)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        self.link_preview = QLineEdit()
        self.link_preview.setReadOnly(True)
        self.link_preview.setFont(_mono_font())
        self.link_preview.setPlaceholderText("Bytes que se van a enviar")
        root.addWidget(self.link_preview)

        ping_row = QHBoxLayout()
        self.ping_pong_check = QCheckBox("Modo ping-pong")
        self.ping_pong_check.toggled.connect(self._on_ping_pong_toggled)
        ping_row.addWidget(self.ping_pong_check)
        self.ping_button = QPushButton("Enviar ping")
        self.ping_button.clicked.connect(self._send_ping)
        ping_row.addWidget(self.ping_button)
        self.ping_state = QLabel("Inactivo")
        ping_row.addWidget(self.ping_state)
        ping_row.addStretch(1)
        root.addLayout(ping_row)

        self.link_log = QPlainTextEdit()
        self.link_log.setReadOnly(True)
        self.link_log.setPlaceholderText("Tramas enviadas y recibidas")
        self.link_log.setFont(_mono_font())
        self.link_log.setMinimumHeight(160)
        root.addWidget(self.link_log)
        return page

    def composed_payload(self) -> bytes:
        return payload_from_input(
            self.payload_edit.toPlainText(),
            hexadecimal=self.link_hex.isChecked(),
            add_crc=self.crc_check.isChecked(),
        )

    def _build_port_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Puerto"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        row.addWidget(self.port_combo, 1)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self._refresh_ports)
        self.refresh_button = refresh
        row.addWidget(refresh)
        self.port_button = QPushButton("Abrir puerto")
        self.port_button.clicked.connect(self._toggle_port)
        row.addWidget(self.port_button)
        self.port_state = QLabel("Cerrado")
        row.addWidget(self.port_state)
        return row

    def _build_info_box(self) -> QGroupBox:
        box = QGroupBox("Equipo")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("Modelo"), 0, 0)
        self.model_combo = QComboBox()
        for model in MODELS:
            self.model_combo.addItem(model, model)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        grid.addWidget(self.model_combo, 0, 1)

        grid.addWidget(QLabel("PID"), 1, 0)
        self.pid_line = QLineEdit("—")
        self.pid_line.setReadOnly(True)
        grid.addWidget(self.pid_line, 1, 1)

        grid.addWidget(QLabel("Frecuencia"), 2, 0)
        self.frequency_line = QLineEdit()
        self.frequency_line.setReadOnly(True)
        grid.addWidget(self.frequency_line, 2, 1)

        grid.addWidget(QLabel("Parámetro"), 3, 0)
        self.parameter_line = QLineEdit()
        self.parameter_line.setReadOnly(True)
        self.parameter_line.setFont(_mono_font())
        grid.addWidget(self.parameter_line, 3, 1)
        grid.setColumnStretch(1, 1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.read_button = QPushButton("Leer")
        self.write_button = QPushButton("Grabar")
        self.factory_button = QPushButton("Restaurar fábrica")
        self.save_button = QPushButton("Guardar archivo")
        self.open_file_button = QPushButton("Abrir archivo")
        self.read_button.clicked.connect(self._read)
        self.write_button.clicked.connect(self._write)
        self.factory_button.clicked.connect(self._restore_factory)
        self.save_button.clicked.connect(self._save_file)
        self.open_file_button.clicked.connect(self._open_file)
        for button in (
            self.read_button,
            self.write_button,
            self.factory_button,
            self.save_button,
            self.open_file_button,
        ):
            row.addWidget(button)
        return row

    def _build_fields(self) -> QGroupBox:
        box = QGroupBox("Configuración local")
        outer = QVBoxLayout(box)
        usage_row = QHBoxLayout()
        usage_row.addWidget(QLabel("Modo de uso"))
        self.usage_combo = _combo(
            ("transparent", "wor", "relay"),
            lambda value: {
                "transparent": "Transparente",
                "wor": "WOR",
                "relay": "Repetidor",
            }[value],
        )
        self.usage_combo.setToolTip(
            "Transparente y WOR solo cambian la pantalla. "
            "Repetidor activa el reenvío por LoRa."
        )
        self.usage_combo.currentIndexChanged.connect(self._on_usage_changed)
        usage_row.addWidget(self.usage_combo, 1)
        outer.addLayout(usage_row)
        self.usage_note = QLabel(
            "Esta estación no envía ni recibe Modbus. Solo retransmite por LoRa "
            "lo que llega, de una red a la otra."
        )
        self.usage_note.setWordWrap(True)
        outer.addWidget(self.usage_note)
        grid = QGridLayout()
        outer.addLayout(grid)

        self.baud_combo = _combo(BAUD_RATES, lambda value: f"{value} bps")
        self.parity_combo = _combo(PARITIES, str)
        self.air_combo = _combo(AIR_RATES_KBPS, lambda value: f"{value:g} kbps")
        self.packet_combo = _combo(PACKET_SIZES, lambda value: f"{value} bytes")
        self.wor_role_combo = _combo(
            (False, True), lambda value: "Transmisor" if value else "Receptor"
        )
        self.wor_cycle_combo = _combo(WOR_CYCLES_MS, lambda value: f"{value} ms")
        self.power_combo = QComboBox()
        self.mode_combo = _combo(
            (False, True), lambda value: "Punto fijo" if value else "Normal"
        )
        self.relay_combo = _bool_combo()
        self.lbt_combo = _bool_combo()
        self.packet_rssi_combo = _bool_combo()
        self.channel_rssi_combo = _bool_combo()
        self.address_spin = _spin(0, 65535)
        self.channel_spin = _spin(CHANNEL_MIN, CHANNEL_MAX)
        self.channel_spin.valueChanged.connect(self._on_channel_changed)
        channel_box = QWidget()
        channel_layout = QHBoxLayout(channel_box)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(self.channel_spin)
        self.channel_frequency = QLabel(f"{frequency_mhz(0):.3f} MHz")
        channel_layout.addWidget(self.channel_frequency)
        channel_layout.addStretch(1)
        self.net_id_spin = _spin(0, 255)
        self.key_spin = _spin(0, 65535)

        fields = (
            ("Velocidad serie", self.baud_combo),
            ("Rol WOR", self.wor_role_combo),
            ("Repetidor", self.relay_combo),
            ("Dirección", self.address_spin),
            ("Paridad", self.parity_combo),
            ("Ciclo WOR", self.wor_cycle_combo),
            ("LBT", self.lbt_combo),
            ("Canal", channel_box),
            ("Velocidad de aire", self.air_combo),
            ("Potencia", self.power_combo),
            ("RSSI de paquete", self.packet_rssi_combo),
            ("NET ID", self.net_id_spin),
            ("Tamaño de paquete", self.packet_combo),
            ("Modo de transmisión", self.mode_combo),
            ("RSSI de canal", self.channel_rssi_combo),
            ("Clave", self.key_spin),
        )
        self._field_labels = {}
        for index, (label, widget) in enumerate(fields):
            row = index // 4
            column = (index % 4) * 2
            label_widget = QLabel(label)
            self._field_labels[widget] = label_widget
            grid.addWidget(label_widget, row, column)
            grid.addWidget(widget, row, column + 1)
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._on_field_changed)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._on_field_changed)
        for column in (1, 3, 5, 7):
            grid.setColumnStretch(column, 1)
        self._apply_usage_visibility()
        return box

    def _apply_usage_visibility(self) -> None:
        mode = self.usage_combo.currentData()
        show_wor = mode == "wor"
        for widget in (self.wor_role_combo, self.wor_cycle_combo):
            widget.setVisible(show_wor)
            self._field_labels[widget].setVisible(show_wor)
        self.relay_combo.setVisible(False)
        self._field_labels[self.relay_combo].setVisible(False)
        show_net = mode != "relay"
        self.net_id_spin.setVisible(show_net)
        self._field_labels[self.net_id_spin].setVisible(show_net)
        address_label = self._field_labels[self.address_spin]
        if mode == "relay":
            address_label.setText("Par NETID")
            self.address_spin.setToolTip(
                "El byte alto y el bajo son los dos NETID. "
                "Los identificadores 02 y 10 se escriben como 0x020A, es decir 522."
            )
        else:
            address_label.setText("Dirección")
            self.address_spin.setToolTip("")
        self.usage_note.setVisible(mode == "relay")

    def _on_usage_changed(self) -> None:
        self._apply_usage_visibility()
        if self._loading:
            return
        self._select_combo(self.relay_combo, self.usage_combo.currentData() == "relay")
        self._on_field_changed()

    def _sync_usage_from_relay(self, relay: bool) -> None:
        current = self.usage_combo.currentData()
        if relay:
            target = "relay"
        elif current == "relay":
            target = "transparent"
        else:
            return
        self._select_combo(self.usage_combo, target)

    def _build_help_tab(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(_help_heading("Cómo usar el programa"))
        layout.addWidget(
            _help_body(
                "La pestaña Configuración lee y graba parámetros con el radio en "
                "modo 2: M1 encendido y M0 apagado. El puerto de la PC queda en "
                "9600 8N1, aunque la velocidad guardada sea otra.\n"
                "La pestaña Enlace envía texto o hexadecimal, y el ping-pong, con "
                "el radio en modo transparente: M0 y M1 apagados. La velocidad y "
                "la paridad tienen que coincidir con las del radio.\n"
                "Las dos pestañas comparten el mismo puerto serie."
            )
        )
        layout.addWidget(_help_heading("Conexión"))
        layout.addWidget(
            _help_body(
                "Alimente el radio con 8 a 28 V, conecte la antena SMA y el "
                "USB a RS485. En el borne, G es la tierra de señal, A va a la A "
                "del equipo y B va a la B."
            )
        )
        self.help_install_image = _FitImage(_IMG_DIR / "quickstart-install.jpg")
        layout.addWidget(self.help_install_image)
        layout.addWidget(_help_heading("Partes"))
        self.help_parts_image = _FitImage(_IMG_DIR / "parts.jpg")
        layout.addWidget(self.help_parts_image)
        layout.addWidget(_parts_legend())
        layout.addWidget(_help_heading("Modos de trabajo"))
        layout.addWidget(
            _help_body(
                "Para cambiar el modo de trabajo se presiona el botón Mode "
                "hasta que cambie la luz. El radio conserva el modo al quitar "
                "la alimentación. De fábrica está en modo transparente."
            )
        )
        layout.addWidget(_modes_table())
        layout.addWidget(
            _help_body(
                "Modo 0, transparente. M0 y M1 apagados. Lo que entra por el "
                "puerto serie sale por el aire, y lo que llega por el aire sale "
                "por el puerto serie. Es el valor de fábrica y el que se usa "
                "para Modbus y para el enlace.\n"
                "Modo 1, WOR. M0 encendido y M1 apagado. El camino de los datos "
                "es el mismo, pero el radio puede dormir y despertar por el aire.\n"
                "Modo 2, configuración. M1 encendido y M0 apagado. Solo en este "
                "modo se leen y graban los registros, siempre a 9600 8N1.\n"
                "Modo 3, sueño. M0 y M1 encendidos. No transmite ni recibe."
            )
        )
        layout.addWidget(_help_heading("Modo de uso"))
        layout.addWidget(
            _help_body(
                "El selector Modo de uso no cambia las luces del equipo. Solo "
                "muestra los controles que corresponden.\n"
                "Transparente oculta el rol y el ciclo WOR. Sirve para el uso "
                "habitual.\n"
                "WOR muestra el rol y el ciclo. Hay que dejar el radio en modo 1 "
                "para que esos valores actúen.\n"
                "Repetidor activa el reenvío. La estación no envía ni recibe "
                "Modbus: solo retransmite por LoRa lo que llega, de una red a la "
                "otra. La dirección pasa a ser el par de NETID."
            )
        )
        layout.addWidget(_help_heading("Qué es WOR"))
        layout.addWidget(
            _help_body(
                "WOR (Wake on Radio) reduce el consumo. El receptor no escucha "
                "todo el tiempo: despierta cada cierto ciclo, entre 500 y 4000 ms. "
                "Un ciclo más largo gasta menos y demora más los datos. El emisor "
                "y el receptor tienen que usar el mismo ciclo.\n"
                "El transmisor agrega un preámbulo de despertar antes de enviar, "
                "para que el receptor dormido alcance a oírlo.\n"
                "El receptor, después de entregar un paquete por el puerto serie, "
                "permanece despierto 1000 ms. En ese lapso se puede contestar. "
                "Cada byte recibido por el serie reinicia esos 1000 ms."
            )
        )
        layout.addWidget(_help_heading("Qué es LBT"))
        layout.addWidget(
            _help_body(
                "LBT (Listen Before Talk) escucha el canal antes de transmitir. "
                "Si hay tráfico, espera, y así evita pisar otra emisión. La espera "
                "puede retrasar los datos. A los 2 segundos transmite igual."
            )
        )
        layout.addWidget(_help_heading("Modo de transmisión"))
        layout.addWidget(
            _help_body(
                "Normal envía por el aire, tal como llegan, los bytes del puerto "
                "serie. Los recibe cualquier radio del mismo canal, dirección y "
                "NET ID. La dirección FFFF es de difusión: la oyen todas las "
                "estaciones de ese canal.\n"
                "Punto fijo usa los tres primeros bytes de cada envío como "
                "destino: dirección alta, dirección baja y canal. Solo el radio "
                "con esa dirección y ese canal entrega el resto del mensaje. "
                "Esos tres bytes no forman parte de los datos útiles."
            )
        )
        layout.addWidget(_help_heading("Modo de configuración"))
        layout.addWidget(
            _help_body(
                "Solo este modo permite configurar el equipo: M1 encendido y "
                "M0 apagado. Leer y Grabar usan el puerto a 9600 8N1."
            )
        )
        self.help_config_image = _FitImage(_IMG_DIR / "modo-config.jpeg")
        layout.addWidget(self.help_config_image)
        layout.addWidget(_help_heading("Frecuencia"))
        layout.addWidget(
            _help_body(
                "La frecuencia es 850.125 MHz más el número de canal. El canal 0 "
                "corresponde a 850.125 MHz y el canal 80 a 930.125 MHz. El "
                "registro admite hasta el canal 83. Por defecto solo se pueden "
                "elegir canales de más de 915 MHz. La pestaña Configuración "
                "permite habilitar el resto."
            )
        )
        layout.addStretch(1)
        scroll.setWidget(content)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return page

    def _build_channel_policy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.allow_any_channel = QCheckBox(
            "Permitir cualquier canal, incluso por debajo de 915 MHz"
        )
        self.allow_any_channel.toggled.connect(self._on_allow_any_channel)
        layout.addWidget(self.allow_any_channel)
        floor = lowest_channel_above()
        note = QLabel(
            "Por ley solo se pueden elegir canales de más de 915 MHz. "
            f"El canal {floor} corresponde a {frequency_mhz(floor):.3f} MHz. "
            "Al activar esta opción se pueden elegir todos los canales del "
            "registro, desde 850.125 MHz."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _refresh_ports(self) -> None:
        self._fill_port_combo(self.port_combo)
        self._fill_port_combo(self.link_port_combo)

    def _fill_port_combo(self, combo: QComboBox) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        ports = list_ports()
        if not ports:
            combo.addItem("No hay puertos", None)
        else:
            for port in ports:
                combo.addItem(port, port)
            chosen = preferred_port(ports, current if isinstance(current, str) else None)
            if chosen is not None:
                self._select_combo(combo, chosen)
        combo.blockSignals(False)

    def _toggle_port(self) -> None:
        if self._busy:
            return
        if self._port_open:
            self._submit("close")
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Puerto", "No hay un puerto serie para abrir.")
            return
        self._submit("open", port)

    def _read(self) -> None:
        if not self._require_port():
            return
        self._submit("read", self.model_combo.currentData())

    def _write(self) -> None:
        if not self._require_port():
            return
        try:
            params = self.current_params()
        except ValueError as exc:
            QMessageBox.warning(self, "Parámetros", str(exc))
            return
        self._submit("write", params)

    def _restore_factory(self) -> None:
        if self._busy:
            return
        answer = QMessageBox.question(
            self,
            "Restaurar fábrica",
            "Esto carga los parámetros de fábrica en el formulario. "
            "Si el puerto está abierto, también se graban en el radio. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        params = factory_params(self.model_combo.currentData())
        floor = self._channel_floor()
        if params.channel < floor:
            params.channel = floor
        self.apply_params(params)
        if self._port_open:
            self._submit("write", params)
        else:
            self._append_log(
                "Parámetros de fábrica cargados en el formulario. "
                "Abra el puerto y pulse Grabar para enviarlos."
            )

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar parámetros", "parametros-e95.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = self.current_params().to_dict()
            Path(path).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Guardar archivo", str(exc))
            return
        self._append_log(f"Parámetros guardados en {path}.")

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir parámetros", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            params = RadioParams.from_dict(data)
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            QMessageBox.warning(self, "Abrir archivo", str(exc))
            return
        self.pid_line.setText("—")
        self.apply_params(params)
        self._append_log(
            f"Archivo cargado desde {path}. Pulse Grabar para enviarlo al radio."
        )

    def _require_port(self) -> bool:
        if self._busy:
            return False
        if not self._port_open:
            QMessageBox.warning(self, "Puerto", "Abra el puerto antes de continuar.")
            return False
        return True

    def _on_opened(self, port: str) -> None:
        self._port_open = True
        self._link_open = True
        self._select_combo(self.port_combo, port)
        self._select_combo(self.link_port_combo, port)
        self.port_state.setText(f"Abierto: {port}")
        self._sync_port_buttons()

    def _on_closed(self) -> None:
        self._mark_port_closed()

    def _on_link_opened(self, description: str) -> None:
        self._port_open = True
        self._link_open = True
        self.link_port_state.setText(f"Abierto: {description}")
        if self.ping_pong_check.isChecked():
            self.ping_state.setText("Escuchando ping.")
        self._on_job_finished()

    def _on_link_closed(self) -> None:
        self._mark_port_closed()

    def _mark_port_closed(self) -> None:
        self._port_open = False
        self._link_open = False
        self._waiting_pong = False
        self._pong_timer.stop()
        self._stop_repeat()
        self.port_state.setText("Cerrado")
        self.link_port_state.setText("Cerrado")
        if not self.ping_pong_check.isChecked():
            self.ping_state.setText("Inactivo")
        self._sync_port_buttons()

    def _on_link_failed(self, message: str) -> None:
        self._stop_repeat()
        self._append_link(message)
        self._on_job_finished()
        QMessageBox.warning(self, "Enlace", message)

    def _on_link_frame(self, frame: bytes) -> None:
        self._append_link("RX " + format_frame(frame))
        if self._waiting_pong and is_pong(frame):
            self._waiting_pong = False
            self._pong_timer.stop()
            self.ping_state.setText("Pong recibido.")
            self._append_link("Pong recibido.")

    def _on_link_sent(self, data: bytes) -> None:
        if data == PONG:
            self._append_link("TX " + format_frame(data) + "  (respuesta automática)")
        elif data == PING:
            self._append_link("TX " + format_frame(data))
        else:
            self._append_link("TX " + format_frame(data))

    def _pong_timeout(self) -> None:
        if not self._waiting_pong:
            return
        self._waiting_pong = False
        self.ping_state.setText("Sin respuesta.")
        self._append_link("Sin respuesta.")

    def _on_params_read(self, params: object, pid: object) -> None:
        if not isinstance(params, RadioParams):
            self._on_failed("La lectura no devolvió parámetros.")
            return
        loaded = params
        if isinstance(pid, bytes):
            self.pid_line.setText(format_bytes(pid))
            detected = model_from_pid(pid)
            if detected is not None:
                loaded = RadioParams.from_registers(loaded.to_registers(), model=detected)
                self._append_log(f"Modelo reconocido en el PID: {detected}.")
        else:
            self.pid_line.setText("—")
        reported = loaded.channel
        self.apply_params(loaded)
        floor = self._channel_floor()
        if reported < floor:
            self._append_log(
                f"El equipo informó el canal {reported}. "
                f"El selector queda en el {self.channel_spin.value()} "
                f"({frequency_mhz(self.channel_spin.value()):.3f} MHz)."
            )
        self._append_log("Parámetros leídos.")
        self._on_job_finished()

    def _on_job_finished(self) -> None:
        self._busy = False
        self._sync_port_buttons()

    def _on_failed(self, message: str) -> None:
        self._append_log(message)
        self._on_job_finished()
        QMessageBox.warning(self, "Radio", message)

    def _on_model_changed(self) -> None:
        self._refill_power()
        self._on_field_changed()

    def _on_field_changed(self) -> None:
        if self._loading:
            return
        self._update_preview()

    def _channel_floor(self) -> int:
        if self._allow_any_channel:
            return CHANNEL_MIN
        return lowest_channel_above()

    def _apply_channel_range(self, value: int, *, keep_illegal: bool) -> None:
        floor = self._channel_floor()
        if keep_illegal and value < floor:
            self._held_channel = value
            low = value
        else:
            self._held_channel = None
            low = floor
            if value < floor:
                value = floor
        self.channel_spin.blockSignals(True)
        self.channel_spin.setRange(low, CHANNEL_MAX)
        self.channel_spin.setValue(value)
        self.channel_spin.blockSignals(False)
        self._update_channel_tooltip()
        if not self._loading:
            self._update_preview()

    def _update_channel_tooltip(self) -> None:
        if self._allow_any_channel:
            text = "0 a 83. La banda declarada es 0 a 80 (850.125 a 930.125 MHz)."
        else:
            floor = lowest_channel_above()
            text = (
                f"Solo canales de más de 915 MHz: desde el {floor} "
                f"({frequency_mhz(floor):.3f} MHz) hasta el {CHANNEL_MAX}. "
                "La banda declarada termina en el canal 80."
            )
        self.channel_spin.setToolTip(text)

    def _on_channel_changed(self, value: int) -> None:
        if not self._loading:
            floor = self._channel_floor()
            if value < floor and value != self._held_channel:
                self._held_channel = None
                self.channel_spin.blockSignals(True)
                self.channel_spin.setRange(floor, CHANNEL_MAX)
                self.channel_spin.setValue(floor)
                self.channel_spin.blockSignals(False)
        self._on_field_changed()

    def _load_channel_policy(self) -> None:
        raw = QSettings().value("allow_any_channel", False)
        allowed = raw is True or str(raw).lower() in ("true", "1")
        self._allow_any_channel = allowed
        self.allow_any_channel.blockSignals(True)
        self.allow_any_channel.setChecked(allowed)
        self.allow_any_channel.blockSignals(False)

    def _on_allow_any_channel(self, checked: bool) -> None:
        self._allow_any_channel = checked
        QSettings().setValue("allow_any_channel", checked)
        self._apply_channel_range(self.channel_spin.value(), keep_illegal=False)

    def _refill_power(self) -> None:
        model = self.model_combo.currentData()
        levels = POWER_DBM.get(model, ())
        current = self.power_combo.currentIndex()
        self.power_combo.blockSignals(True)
        self.power_combo.clear()
        for index, dbm in enumerate(levels):
            self.power_combo.addItem(f"{dbm} dBm", index)
        if self.power_combo.count():
            self.power_combo.setCurrentIndex(
                min(max(current, 0), self.power_combo.count() - 1)
            )
        self.power_combo.blockSignals(False)

    def _update_preview(self) -> None:
        self.channel_frequency.setText(
            f"{frequency_mhz(self.channel_spin.value()):.3f} MHz"
        )
        try:
            params = self.current_params()
        except ValueError as exc:
            self.parameter_line.setText(str(exc))
            return
        self.frequency_line.setText(frequency_text(params.channel))
        self.parameter_line.setText(format_bytes(build_write_command(params)))

    def _sync_port_buttons(self) -> None:
        self.port_button.setText("Cerrar puerto" if self._port_open else "Abrir puerto")
        enabled = not self._busy
        self.port_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled and not self._port_open)
        self.port_combo.setEnabled(enabled and not self._port_open)
        self.read_button.setEnabled(enabled and self._port_open)
        self.write_button.setEnabled(enabled and self._port_open)
        self.factory_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.open_file_button.setEnabled(enabled)
        self._sync_link_buttons()

    def _sync_link_buttons(self) -> None:
        enabled = not self._busy
        self.link_port_button.setText(
            "Cerrar puerto" if self._link_open else "Abrir puerto"
        )
        self.link_port_button.setEnabled(enabled)
        self.link_refresh_button.setEnabled(enabled and not self._link_open)
        self.link_port_combo.setEnabled(enabled and not self._link_open)
        self.link_baud_combo.setEnabled(enabled and not self._link_open)
        self.link_parity_combo.setEnabled(enabled and not self._link_open)
        self.copy_settings_button.setEnabled(enabled and not self._link_open)
        self.send_button.setEnabled(enabled and self._link_open)
        self.repeat_button.setEnabled(enabled and self._link_open)
        self.ping_button.setEnabled(enabled and self._link_open)
        self.ping_pong_check.setEnabled(enabled)

    def _copy_link_settings(self) -> None:
        self._select_combo(self.link_baud_combo, self.baud_combo.currentData())
        self._select_combo(self.link_parity_combo, self.parity_combo.currentData())

    def _toggle_link_port(self) -> None:
        if self._busy:
            return
        if self._link_open:
            self._submit("close")
            return
        port = self.link_port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Enlace", "No hay un puerto serie para abrir.")
            return
        baud = self.link_baud_combo.currentData()
        parity = self.link_parity_combo.currentData()
        self._submit("open_link", (port, baud, parity, self.ping_pong_check.isChecked()))

    def _send_payload(self) -> bool:
        if not self._link_open:
            QMessageBox.warning(self, "Enlace", "Abra el puerto antes de enviar.")
            return False
        try:
            data = self.composed_payload()
        except LinkError as exc:
            QMessageBox.warning(self, "Enlace", str(exc))
            return False
        self._submit("send_link", data, busy=False)
        return True

    def _toggle_repeat(self) -> None:
        if self._repeat_timer.isActive():
            self._stop_repeat()
            return
        if not self._send_payload():
            return
        self._repeat_timer.start()
        self.repeat_button.setText("Detener")

    def _repeat_send(self) -> None:
        if not self._link_open or not self._send_payload():
            self._stop_repeat()

    def _stop_repeat(self) -> None:
        self._repeat_timer.stop()
        if getattr(self, "repeat_button", None) is not None:
            self.repeat_button.setText("Enviar cada 5 segundos")

    def _on_tab_changed(self, index: int) -> None:
        if self._tabs.tabText(index) != "Enlace":
            self._stop_repeat()

    def _send_ping(self) -> None:
        if not self._link_open:
            QMessageBox.warning(self, "Enlace", "Abra el puerto antes de enviar ping.")
            return
        if not self.ping_pong_check.isChecked():
            QMessageBox.warning(
                self,
                "Enlace",
                "Active el modo ping-pong en los dos equipos.",
            )
            return
        self._waiting_pong = True
        self.ping_state.setText("Esperando pong…")
        self._pong_timer.start(int(PING_TIMEOUT_S * 1000))
        self._submit("send_link", PING, busy=False)

    def _on_ping_pong_toggled(self, checked: bool) -> None:
        self._submit("set_ping_pong", checked, busy=False)
        if checked and self._link_open:
            self.ping_state.setText("Escuchando ping.")
        elif not checked and not self._waiting_pong:
            self.ping_state.setText("Inactivo")

    def _update_link_preview(self, *_args: object) -> None:
        text = self.payload_edit.toPlainText()
        if not text.strip():
            self.link_preview.clear()
            return
        try:
            self.link_preview.setText(format_bytes(self.composed_payload()))
        except LinkError as exc:
            self.link_preview.setText(str(exc))

    def _append_link(self, message: str) -> None:
        self.link_log.appendPlainText(message)

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _submit(self, operation: str, payload: object = None, busy: bool = True) -> None:
        if busy:
            self._busy = True
            self._sync_port_buttons()
        self._worker.submit(operation, payload)

    @staticmethod
    def _select_combo(combo: QComboBox, value: object) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return


def _combo(values, label) -> QComboBox:
    combo = QComboBox()
    for value in values:
        combo.addItem(label(value), value)
    return combo


def _bool_combo() -> QComboBox:
    return _combo((False, True), lambda value: "Activado" if value else "Desactivado")


def _spin(low: int, high: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(low, high)
    return spin


def _mono_font() -> QFont:
    font = QFont("monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def _image_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "docs" / "img"
    return Path(__file__).resolve().parents[1] / "docs" / "img"


_IMG_DIR = _image_dir()

_PARTS = (
    ("1", "Mode", "Botón de cambio de modo"),
    ("2", "ANT", "Antena SMA-K, rosca externa"),
    ("3", "DC", "Alimentación de 8 a 28 V"),
    ("4", "RS485", "Bornes G, A y B"),
    ("5", "PWR", "Se enciende con la alimentación"),
    ("6", "TXD", "Parpadea al enviar"),
    ("7", "RXD", "Parpadea al recibir"),
    ("8", "M0", "Indicador de modo"),
    ("9", "M1", "Indicador de modo"),
)

_MODES = (
    ("Modo", "Nombre", "M1", "M0"),
    ("0", "Transparente", "Apagado", "Apagado"),
    ("1", "WOR", "Apagado", "Encendido"),
    ("2", "Configuración", "Encendido", "Apagado"),
    ("3", "Sueño", "Encendido", "Encendido"),
)


class _FitImage(QLabel):
    """Reduce la imagen si no entra en la pestaña y no la agranda."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._source = QPixmap(str(path))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        if self._source.isNull():
            self.setText(f"No se encontró la imagen {path.name}")
            self.setWordWrap(True)
        else:
            self.setPixmap(self._source)

    def hasHeightForWidth(self) -> bool:
        return not self._source.isNull()

    def _display_width(self, available: int) -> int:
        return min(max(available, 1), self._source.width())

    def heightForWidth(self, width: int) -> int:
        if self._source.isNull() or self._source.width() <= 0 or width <= 0:
            return super().heightForWidth(width)
        display = self._display_width(width)
        return max(1, round(self._source.height() * display / self._source.width()))

    def sizeHint(self) -> QSize:
        if self._source.isNull():
            return super().sizeHint()
        return self._source.size()

    def minimumSizeHint(self) -> QSize:
        if self._source.isNull():
            return super().minimumSizeHint()
        return QSize(160, self.heightForWidth(160))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._source.isNull():
            return
        width = self._display_width(self.width())
        current = self.pixmap()
        if current is not None and current.width() == width:
            return
        if width == self._source.width():
            self.setPixmap(self._source)
            return
        self.setPixmap(
            self._source.scaledToWidth(
                width, Qt.TransformationMode.SmoothTransformation
            )
        )


def _help_heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    font.setPointSize(font.pointSize() + 1)
    label.setFont(font)
    return label


def _help_body(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def _parts_legend() -> QWidget:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    for column, title in enumerate(("N.º", "Nombre", "Función")):
        header = QLabel(title)
        header.setFont(_bold_font())
        grid.addWidget(header, 0, column)
    for row, (number, name, role) in enumerate(_PARTS, start=1):
        grid.addWidget(QLabel(number), row, 0)
        grid.addWidget(QLabel(name), row, 1)
        grid.addWidget(QLabel(role), row, 2)
    box = QWidget()
    box.setLayout(grid)
    return box


def _modes_table() -> QWidget:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    for row, values in enumerate(_MODES):
        for column, value in enumerate(values):
            label = QLabel(value)
            if row == 0:
                label.setFont(_bold_font())
            grid.addWidget(label, row, column)
    box = QWidget()
    box.setLayout(grid)
    return box


def _bold_font() -> QFont:
    font = QFont()
    font.setBold(True)
    return font
