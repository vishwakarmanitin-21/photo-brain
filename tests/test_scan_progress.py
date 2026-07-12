import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.scan_view import ScanView


class WeightedProgressTests(unittest.TestCase):
    """UX-09: one weighted bar that advances monotonically across phases,
    with a 'Phase N/M' label — never resets to 0 mid-scan."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self, total=8):
        v = ScanView()
        self.addCleanup(v.deleteLater)
        v.reset(total_phases=total)
        return v

    def test_phase_label_shows_ordinal(self):
        v = self._view(8)
        v.update_phase("Computing file hashes...")
        v.update_phase("Fingerprinting and scoring...")
        self.assertIn("Phase 2/8", v._phase_label.text())
        self.assertIn("Fingerprinting", v._phase_label.text())

    def test_progress_is_monotonic_and_never_resets(self):
        v = self._view(4)
        values = []
        for phase in range(4):
            v.update_phase(f"phase {phase}")
            for cur in (0, 5, 10):
                v.update_progress("x", cur, 10)
                values.append(v._progress.value())
        # Non-decreasing throughout — the old bug reset to 0 each phase.
        for a, b in zip(values, values[1:]):
            self.assertLessEqual(a, b, f"progress went backwards: {values}")

    def test_within_phase_fraction_maps_into_phase_slice(self):
        v = self._view(4)
        v.update_phase("p1")           # phase 1 of 4 → slice [0, 25)
        v.update_progress("x", 5, 10)  # halfway through phase 1
        self.assertEqual(int((0 + 0.5) / 4 * 100), v._progress.value())  # 12

    def test_fewer_phases_when_faces_disabled(self):
        v = self._view(7)
        v.update_phase("hash")
        self.assertIn("1/7", v._phase_label.text())


if __name__ == "__main__":
    unittest.main()
