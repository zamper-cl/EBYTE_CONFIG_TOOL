# Copyright (C) 2026 Zamper.io
# Licensed under the GNU General Public License v3.0. See LICENSE.
import sys

from PyQt6.QtWidgets import QApplication

from ebyte_dtu.window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName("E95-DTU")
    app.setApplicationName("Configurador E95-DTU")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
