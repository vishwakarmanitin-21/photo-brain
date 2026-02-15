"""Application bootstrap."""
import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from app.ui.main_window import MainWindow


def _icon_path() -> str:
    """Resolve path to the app icon bundled in assets/."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "photobrain.ico")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoBrain")
    app.setOrganizationName("PhotoBrain")

    icon = QIcon(_icon_path())
    app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowTitle("PhotoBrain Desktop")
    window.setWindowIcon(icon)
    window.resize(1200, 800)
    window.show()

    return app.exec()
