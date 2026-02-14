"""Application bootstrap."""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoBrain")
    app.setOrganizationName("PhotoBrain")

    window = MainWindow()
    window.setWindowTitle("PhotoBrain Desktop")
    window.resize(1200, 800)
    window.show()

    return app.exec()
