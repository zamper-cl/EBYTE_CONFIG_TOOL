# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import sys

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ebyte_dtu import __version__
from ebyte_dtu.e860_window import E860Window
from ebyte_dtu.window import MainWindow


class DeviceDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Elegir equipo")
        self.choice: str | None = None
        layout = QVBoxLayout(self)
        label = QLabel(
            f"Seleccione el equipo que quiere configurar. Versión {__version__}."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        row = QHBoxLayout()
        self.e95_button = QPushButton("E95-DTU")
        self.e860_button = QPushButton("E860-DTU")
        self.e95_button.clicked.connect(lambda: self._pick("e95"))
        self.e860_button.clicked.connect(lambda: self._pick("e860"))
        row.addWidget(self.e95_button)
        row.addWidget(self.e860_button)
        layout.addLayout(row)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName("E95-DTU")
    app.setApplicationName("Configurador E95-DTU")
    dialog = DeviceDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted or dialog.choice is None:
        return
    window = MainWindow() if dialog.choice == "e95" else E860Window()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
