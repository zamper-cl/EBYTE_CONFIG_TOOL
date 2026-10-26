# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
"""Ventana de configuración del E860-DTU por comandos AT."""

from __future__ import annotations

import json
import queue
from pathlib import Path

from PyQt6.QtCore import QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ebyte_dtu.e860 import (
    AIR_SPEEDS,
    AT_TIMEOUT_S,
    CHANNEL_MAX,
    CHANNEL_MIN,
    EXIT_AT,
    KEY_MAX,
    PC_BAUD,
    PC_PARITY,
    READ_COMMANDS,
    REBOOT,
    RESTORE,
    _TEXT_FIELDS,
    START_CHANNEL,
    UART_BAUD_RATES,
    WORK_MODES,
    WORK_ROLES,
    AtUnavailable,
    PasswordRequired,
    SwitchParams,
    default_params,
    format_at,
    indexed_label,
    password_command,
    parse_response,
    query_command,
    write_commands,
)
from ebyte_dtu.protocol import frequency_mhz, lowest_channel_above
from ebyte_dtu.serial_session import SerialSession, list_ports, preferred_port


class E860Worker(QThread):
    log_message = pyqtSignal(str)
    opened = pyqtSignal(str)
    closed = pyqtSignal()
    entered = pyqtSignal()
    password_required = pyqtSignal()
    params_read = pyqtSignal(object)
    params_written = pyqtSignal()
    exited = pyqtSignal()
    restored = pyqtSignal()
    restarted = pyqtSignal()
    failed = pyqtSignal(str)
    idle = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._session = SerialSession()
        self._password_pending = False

    def submit(self, operation: str, payload: object = None) -> None:
        self._queue.put((operation, payload))

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._session.close()
                break
            operation, payload = item
            try:
                self._handle(operation, payload)
            except PasswordRequired:
                self.password_required.emit()
            except Exception as exc:
                self.failed.emit(str(exc))

    def _handle(self, operation: str, payload: object) -> None:
        if operation == "open":
            port, baud = payload  # type: ignore[misc]
            self._open(str(port), int(baud))
        elif operation == "close":
            self._close()
        elif operation == "enter":
            password = payload if isinstance(payload, str) else None
            self._enter(password)
        elif operation == "cancel_enter":
            self._password_pending = False
            self.log_message.emit("Entrada a AT cancelada.")
            self.idle.emit()
        elif operation == "read":
            self._read()
        elif operation == "write":
            if not isinstance(payload, SwitchParams):
                raise TypeError("Los parámetros a grabar no son válidos.")
            self._write(payload)
        elif operation == "exit":
            self._command(EXIT_AT, "Salió del modo AT.")
            self.exited.emit()
        elif operation == "restore":
            self._command(RESTORE, "El equipo volvió a los valores de fábrica.")
            self.restored.emit()
        elif operation == "restart":
            self._command(REBOOT, "El equipo se está reiniciando.")
            self.restarted.emit()
        else:
            raise RuntimeError(f"Operación desconocida: {operation}")

    def _open(self, port: str, baud: int) -> None:
        self._password_pending = False
        self._session.open(port, baudrate=baud, parity=PC_PARITY, timeout=AT_TIMEOUT_S)
        self.opened.emit(port)
        self.log_message.emit(f"Puerto {port} abierto a {baud} bps {PC_PARITY}.")

    def _close(self) -> None:
        self._password_pending = False
        self._session.close()
        self.closed.emit()
        self.log_message.emit("Puerto cerrado.")

    def _enter(self, password: str | None) -> None:
        if not self._session.is_open:
            raise RuntimeError("El puerto no está abierto.")
        if not self._password_pending:
            try:
                self._exchange(query_command("VER"))
            except PasswordRequired:
                self._password_pending = True
                if not password:
                    raise
            else:
                self._finish_enter()
                return
        if not password:
            raise PasswordRequired("El equipo pidió la contraseña de configuración.")
        self._exchange(password_command(password))
        self._password_pending = False
        self._finish_enter()

    def _finish_enter(self) -> None:
        self._password_pending = False
        self.log_message.emit("Modo AT activo.")
        self.entered.emit()

    def _read(self) -> None:
        params = SwitchParams()
        for name in READ_COMMANDS:
            try:
                value = self._exchange(query_command(name))
            except AtUnavailable:
                if name not in _TEXT_FIELDS:
                    raise
                value = ""
            params.apply_read(name, value)
        params.validate()
        self.params_read.emit(params)
        self.log_message.emit("Parámetros leídos.")

    def _write(self, params: SwitchParams) -> None:
        for command in write_commands(params):
            self._exchange(command)
        self.params_written.emit()
        self.log_message.emit(
            "Parámetros grabados. Si cambió la velocidad del equipo, "
            "cierre el puerto y ábralo a esa velocidad."
        )

    def _command(self, command: bytes, done: str) -> None:
        self._exchange(command)
        self.log_message.emit(done)

    def _exchange(self, command: bytes) -> str:
        if not self._session.is_open:
            raise RuntimeError("El puerto no está abierto.")
        self._session.clear_input()
        self.log_message.emit("TX " + format_at(command))
        self._session.write(command)
        raw = self._session.read_for(AT_TIMEOUT_S)
        self.log_message.emit("RX " + (format_at(raw) if raw else "(vacío)"))
        return parse_response(raw)


class E860Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Configurador E860-DTU")
        self.resize(980, 720)
        self._loading = False
        self._port_open = False
        self._port_name = ""
        self._at_mode = False
        self._busy = False
        self._awaiting_password = False
        self._params = default_params()
        self._allow_any_channel = False
        self._held_channel: int | None = None

        self._worker = E860Worker()
        self._worker.log_message.connect(self._append_log)
        self._worker.opened.connect(self._on_opened)
        self._worker.closed.connect(self._on_closed)
        self._worker.entered.connect(self._on_entered)
        self._worker.password_required.connect(self._on_password_required)
        self._worker.params_read.connect(self._on_params_read)
        self._worker.params_written.connect(self._on_job_finished)
        self._worker.exited.connect(self._on_exited)
        self._worker.restored.connect(self._on_left_at)
        self._worker.restarted.connect(self._on_left_at)
        self._worker.failed.connect(self._on_failed)
        self._worker.idle.connect(self._on_job_finished)
        self._worker.start()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        tabs = QTabWidget()
        tabs.addTab(self._build_config_tab(), "Configuración")
        tabs.addTab(self._build_help_tab(), "Ayuda")
        root.addWidget(tabs)

        self._refresh_ports()
        self._load_channel_policy()
        self.apply_params(default_params())
        self._apply_channel_range(START_CHANNEL, keep_illegal=False)
        self._sync_buttons()

    def _build_config_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addLayout(self._build_port_row())
        notice = QLabel(
            "Conecte el RS485 del E860. El puerto de la PC abre a 115200 8N1 "
            "y puede usar otra velocidad si el equipo ya quedó en esa. "
            "Entrar en AT comprueba el enlace con AT+VER. "
            "El equipo no usa +++ ni el signo de pregunta."
        )
        notice.setWordWrap(True)
        root.addWidget(notice)
        root.addLayout(self._build_buttons())
        root.addWidget(self._build_info())
        root.addWidget(self._build_fields())
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Registro de TX/RX")
        self.log.setFont(_mono_font())
        self.log.setMinimumHeight(140)
        root.addWidget(self.log)
        return page

    def _build_help_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(_help_heading("Botón STATE"))
        layout.addWidget(
            _help_body(
                "Mantener STATE 2 segundos entra en pareo: suena un pitido y "
                "STATE parpadea rápido.\n"
                "Mantenerlo más de 6 segundos vuelve a fábrica.\n"
                "Mantenerlo también alterna entre el estado de pareo y el de "
                "reinicio.\n"
                "En pareo, una pulsación corta sale de ese modo.\n"
                "Antes de repetir el pareo en otro modo, hay que volver a fábrica."
            )
        )
        layout.addWidget(_help_heading("Pareo de uno a uno"))
        layout.addWidget(
            _help_body(
                "Sirve para dos equipos. El DI de cada uno controla el DO del otro.\n"
                "1. Mantener STATE del maestro 2 segundos. Un pitido y STATE parpadea.\n"
                "2. Mantener STATE del esclavo 2 segundos. Un pitido y STATE parpadea.\n"
                "3. El pareo es automático: los dos pitan dos veces.\n"
                "4. Pulsar STATE en los dos para salir.\n"
                "El maestro queda con LINK y STATE encendidos. El esclavo queda "
                "con LINK encendido y STATE parpadeando lento.\n"
                "Los equipos de 2, 4 y 8 canales se emparejan igual: cada DI "
                "controla el DO del mismo número."
            )
        )
        layout.addWidget(_help_heading("Pareo de uno a varios"))
        layout.addWidget(
            _help_body(
                "Un maestro puede emparejar hasta 200 esclavos. El DI del maestro "
                "controla el DO de todos los esclavos, y el DI de cualquier "
                "esclavo controla el DO del maestro.\n"
                "El primer esclavo tiene que tener la misma cantidad de canales "
                "que el maestro. Los siguientes pueden tener la misma cantidad o "
                "más; si tienen más, solo se controlan los primeros canales del maestro.\n"
                "1. Mantener STATE del maestro 2 segundos.\n"
                "2. Mantener STATE del primer esclavo 2 segundos. Al pitar dos "
                "veces, pulsar STATE de ese esclavo para salir.\n"
                "3. Repetir con cada esclavo. Al terminar el último, pulsar STATE "
                "en el maestro y en ese esclavo.\n"
                "El maestro queda con STATE fijo. Cada esclavo queda con STATE "
                "parpadeando lento."
            )
        )
        layout.addWidget(_help_heading("Pareo con distinta cantidad de canales"))
        layout.addWidget(
            _help_body(
                "La suma de canales de los esclavos no puede pasar la del maestro. "
                "Por ejemplo, un maestro de 8 canales admite cuatro esclavos de 2.\n"
                "El pareo es el mismo que de uno a varios, en orden. El maestro "
                "asigna sus canales según ese orden. Si el esclavo 1 es de 2 "
                "canales, usa DI1, DI2, DO1 y DO2 del maestro. El esclavo 2 usa "
                "los siguientes.\n"
                "LINK amarillo del maestro parpadea tantas veces como esclavos "
                "conectados, con un ciclo de 300 ms, y después queda apagado 1 s. "
                "Tres esclavos se ven como tres destellos y una pausa."
            )
        )
        layout.addWidget(_help_heading("Estados del LED"))
        layout.addWidget(_led_table())
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return page

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._worker.stop()
        self._worker.wait(5000)
        super().closeEvent(event)

    def apply_params(self, params: SwitchParams) -> None:
        self._loading = True
        self._params = params
        try:
            self._select_combo(self.device_baud_combo, params.baud_rate)
            self._apply_channel_range(params.channel, keep_illegal=False)
            self.key_spin.setValue(params.key)
            self.version_line.setText(_shown(params.version))
            self.model_line.setText(_shown(params.device_type))
            self.sn_line.setText(_shown(params.serial_number))
            self.role_line.setText(_shown(indexed_label(params.work_role, WORK_ROLES)))
            self.mode_line.setText(_shown(indexed_label(params.work_mode, WORK_MODES)))
            self.mated_count_line.setText(_shown(params.mated_count))
            self.mated_model_line.setText(_shown(params.mated_model))
            self.air_line.setText(_shown(indexed_label(params.air_speed, AIR_SPEEDS)))
        finally:
            self._loading = False
        self._update_frequency()

    def current_params(self) -> SwitchParams:
        params = SwitchParams(
            version=self._params.version,
            device_type=self._params.device_type,
            serial_number=self._params.serial_number,
            work_role=self._params.work_role,
            work_mode=self._params.work_mode,
            mated_count=self._params.mated_count,
            mated_model=self._params.mated_model,
            air_speed=self._params.air_speed,
            baud_rate=self.device_baud_combo.currentData(),
            uart_extra=self._params.uart_extra,
            channel=self.channel_spin.value(),
            key=self.key_spin.value(),
        )
        params.validate()
        return params

    def _build_port_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Puerto"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        row.addWidget(self.port_combo, 1)
        self.refresh_button = QPushButton("Actualizar")
        self.refresh_button.clicked.connect(self._refresh_ports)
        row.addWidget(self.refresh_button)
        row.addWidget(QLabel("Velocidad de la PC"))
        self.port_baud_combo = _combo(UART_BAUD_RATES, lambda value: f"{value} bps")
        self._select_combo(self.port_baud_combo, PC_BAUD)
        row.addWidget(self.port_baud_combo)
        row.addWidget(QLabel(PC_PARITY))
        self.port_button = QPushButton("Abrir puerto")
        self.port_button.clicked.connect(self._toggle_port)
        row.addWidget(self.port_button)
        self.port_state = QLabel("Cerrado")
        row.addWidget(self.port_state)
        return row

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.enter_button = QPushButton("Entrar en AT")
        self.enter_button.clicked.connect(self._enter)
        self.read_button = QPushButton("Leer")
        self.read_button.clicked.connect(self._read)
        self.write_button = QPushButton("Grabar")
        self.write_button.clicked.connect(self._write)
        self.exit_button = QPushButton("Salir de AT")
        self.exit_button.clicked.connect(lambda: self._submit("exit"))
        self.restore_button = QPushButton("Restaurar fábrica")
        self.restore_button.clicked.connect(self._restore)
        self.restart_button = QPushButton("Reiniciar")
        self.restart_button.clicked.connect(self._restart)
        self.save_button = QPushButton("Guardar archivo")
        self.save_button.clicked.connect(self._save_file)
        self.open_file_button = QPushButton("Abrir archivo")
        self.open_file_button.clicked.connect(self._open_file)
        for button in (
            self.enter_button,
            self.read_button,
            self.write_button,
            self.exit_button,
            self.restore_button,
            self.restart_button,
            self.save_button,
            self.open_file_button,
        ):
            row.addWidget(button)
        return row

    def _build_info(self) -> QGroupBox:
        box = QGroupBox("Equipo")
        form = QFormLayout(box)
        self.version_line = _read_line()
        self.model_line = _read_line()
        self.sn_line = _read_line()
        self.role_line = _read_line()
        self.mode_line = _read_line()
        self.mated_count_line = _read_line()
        self.mated_model_line = _read_line()
        self.air_line = _read_line()
        form.addRow("Versión", self.version_line)
        form.addRow("Modelo", self.model_line)
        form.addRow("SN", self.sn_line)
        form.addRow("Rol", self.role_line)
        form.addRow("Modo", self.mode_line)
        form.addRow("Emparejamientos", self.mated_count_line)
        form.addRow("Modelo emparejado", self.mated_model_line)
        form.addRow("Velocidad de aire", self.air_line)
        return box

    def _build_fields(self) -> QGroupBox:
        box = QGroupBox("Parámetros")
        form = QFormLayout(box)
        self.device_baud_combo = _combo(UART_BAUD_RATES, lambda value: f"{value} bps")
        form.addRow("Velocidad del equipo", self.device_baud_combo)
        channel_row = QHBoxLayout()
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(CHANNEL_MIN, CHANNEL_MAX)
        self.channel_spin.valueChanged.connect(self._on_channel_changed)
        channel_row.addWidget(self.channel_spin)
        self.channel_frequency = QLabel()
        channel_row.addWidget(self.channel_frequency)
        channel_row.addStretch(1)
        form.addRow("Canal", channel_row)
        self.key_spin = QSpinBox()
        self.key_spin.setRange(0, KEY_MAX)
        form.addRow("Clave", self.key_spin)
        self.allow_any_channel = QCheckBox(
            "Permitir cualquier canal, incluso por debajo de 915 MHz"
        )
        self.allow_any_channel.toggled.connect(self._on_allow_any_channel)
        form.addRow("", self.allow_any_channel)
        floor = lowest_channel_above()
        note = QLabel(
            "Por ley solo se pueden elegir canales de más de 915 MHz. "
            f"El canal {floor} corresponde a {frequency_mhz(floor):.3f} MHz. "
            "La banda del E860 va del canal 0 (850.125 MHz) al 80 (930.125 MHz)."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return box

    def _refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        ports = list_ports()
        if not ports:
            self.port_combo.addItem("No hay puertos", None)
        else:
            for port in ports:
                self.port_combo.addItem(port, port)
            chosen = preferred_port(ports, current if isinstance(current, str) else None)
            if chosen is not None:
                self._select_combo(self.port_combo, chosen)
        self.port_combo.blockSignals(False)

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
        self._submit("open", (port, self.port_baud_combo.currentData()))

    def _enter(self) -> None:
        if not self._require_port():
            return
        self._submit("enter", None)

    def _read(self) -> None:
        if not self._require_at():
            return
        self._submit("read")

    def _write(self) -> None:
        if not self._require_at():
            return
        try:
            params = self.current_params()
        except ValueError as exc:
            QMessageBox.warning(self, "Parámetros", str(exc))
            return
        self._submit("write", params)

    def _restore(self) -> None:
        if not self._confirm_at(
            "Restaurar fábrica",
            "Esto borra la configuración del equipo y la deja de fábrica. ¿Continuar?",
        ):
            return
        self._submit("restore")

    def _restart(self) -> None:
        if not self._confirm_at(
            "Reiniciar",
            "El equipo se va a reiniciar y saldrá del modo AT. ¿Continuar?",
        ):
            return
        self._submit("restart")

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar parámetros", "parametros-e860.json", "JSON (*.json)"
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
            params = SwitchParams.from_dict(data)
        except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
            QMessageBox.warning(self, "Abrir archivo", str(exc))
            return
        self.apply_params(params)
        self._append_log(
            f"Archivo cargado desde {path}. Entre en AT y pulse Grabar para enviarlo."
        )

    def _require_port(self) -> bool:
        if self._busy:
            return False
        if not self._port_open:
            QMessageBox.warning(self, "Puerto", "Abra el puerto antes de continuar.")
            return False
        return True

    def _require_at(self) -> bool:
        if not self._require_port():
            return False
        if not self._at_mode:
            QMessageBox.warning(self, "AT", "Entre en AT antes de continuar.")
            return False
        return True

    def _confirm_at(self, title: str, question: str) -> bool:
        if not self._require_at():
            return False
        answer = QMessageBox.question(
            self,
            title,
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_opened(self, port: str) -> None:
        self._port_open = True
        self._port_name = port
        self._at_mode = False
        self._select_combo(self.port_combo, port)
        self._on_job_finished()

    def _on_closed(self) -> None:
        self._port_open = False
        self._port_name = ""
        self._at_mode = False
        self._on_job_finished()

    def _on_entered(self) -> None:
        self._at_mode = True
        self._awaiting_password = False
        self._on_job_finished()

    def _on_exited(self) -> None:
        self._at_mode = False
        self._on_job_finished()

    def _on_left_at(self) -> None:
        self._at_mode = False
        self._on_job_finished()

    def _on_password_required(self) -> None:
        self._awaiting_password = True
        password, ok = QInputDialog.getText(
            self,
            "Contraseña",
            "El equipo pidió la contraseña de configuración.",
            QLineEdit.EchoMode.Password,
        )
        self._awaiting_password = False
        if not ok or not password.strip():
            self._submit("cancel_enter")
            return
        try:
            password_command(password.strip())
        except ValueError as exc:
            self._on_failed(str(exc))
            return
        self._submit("enter", password.strip())

    def _on_params_read(self, params: object) -> None:
        if not isinstance(params, SwitchParams):
            self._on_failed("La lectura no devolvió parámetros.")
            return
        reported = params.channel
        self.apply_params(params)
        floor = self._channel_floor()
        if reported < floor:
            self._append_log(
                f"El equipo informó el canal {reported}. "
                f"El selector queda en el {self.channel_spin.value()} "
                f"({frequency_mhz(self.channel_spin.value()):.3f} MHz)."
            )
        self._on_job_finished()

    def _on_failed(self, message: str) -> None:
        self._append_log(message)
        self._on_job_finished()
        if not self._awaiting_password:
            QMessageBox.warning(self, "E860", message)

    def _on_job_finished(self) -> None:
        self._busy = False
        self._sync_buttons()

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
            self._update_frequency()

    def _update_channel_tooltip(self) -> None:
        if self._allow_any_channel:
            text = "0 a 80 (850.125 a 930.125 MHz)."
        else:
            floor = lowest_channel_above()
            text = (
                f"Solo canales de más de 915 MHz: desde el {floor} "
                f"({frequency_mhz(floor):.3f} MHz) hasta el {CHANNEL_MAX}."
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
        self._update_frequency()

    def _update_frequency(self) -> None:
        self.channel_frequency.setText(
            f"{frequency_mhz(self.channel_spin.value()):.3f} MHz"
        )

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

    def _sync_buttons(self) -> None:
        enabled = not self._busy
        self.port_button.setText("Cerrar puerto" if self._port_open else "Abrir puerto")
        self.port_button.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled and not self._port_open)
        self.port_combo.setEnabled(enabled and not self._port_open)
        self.port_baud_combo.setEnabled(enabled and not self._port_open)
        self.enter_button.setEnabled(enabled and self._port_open and not self._at_mode)
        at = enabled and self._port_open and self._at_mode
        self.read_button.setEnabled(at)
        self.write_button.setEnabled(at)
        self.exit_button.setEnabled(at)
        self.restore_button.setEnabled(at)
        self.restart_button.setEnabled(at)
        self.save_button.setEnabled(enabled)
        self.open_file_button.setEnabled(enabled)
        self._refresh_port_state()

    def _refresh_port_state(self) -> None:
        if not self._port_open:
            self.port_state.setText("Cerrado")
            return
        text = f"Abierto: {self._port_name}"
        if self._at_mode:
            text += " · AT"
        self.port_state.setText(text)

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _submit(self, operation: str, payload: object = None) -> None:
        self._busy = True
        self._sync_buttons()
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


def _read_line() -> QLineEdit:
    line = QLineEdit()
    line.setReadOnly(True)
    return line


def _shown(value: str) -> str:
    return value if value else "—"


def _mono_font() -> QFont:
    font = QFont("monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


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


_LEDS = (
    ("Indicador", "Color", "Estado"),
    ("PWR", "Azul", "Encendido con alimentación. Apagado sin alimentación."),
    (
        "LINK",
        "Amarillo",
        "Uno a uno, o uno a varios con la misma cantidad de canales: "
        "encendido en el maestro si hay al menos un esclavo, y encendido en "
        "el esclavo cuando quedó conectado. Con distinta cantidad de canales, "
        "el maestro parpadea una vez por cada esclavo (300 ms) y después se "
        "apaga 1 s.",
    ),
    (
        "STATE",
        "Azul",
        "Maestro: fijo. Esclavo: parpadeo lento. Pareo: parpadeo rápido. "
        "Sin parear: apagado.",
    ),
    ("DI1–DI8", "Verde", "Encendido si hay entrada. Apagado si no hay entrada."),
    (
        "DO1–DO8",
        "Rojo",
        "Encendido mientras el relé está activo. Apagado si no hay salida.",
    ),
)


def _led_table() -> QWidget:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setColumnStretch(2, 1)
    for row, values in enumerate(_LEDS):
        for column, value in enumerate(values):
            label = QLabel(value)
            label.setWordWrap(True)
            if row == 0:
                font = label.font()
                font.setBold(True)
                label.setFont(font)
            grid.addWidget(label, row, column)
    box = QWidget()
    box.setLayout(grid)
    return box
