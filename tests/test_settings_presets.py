import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.dialogs import SettingsDialog, GROUPING_PRESETS


class SettingsPresetTests(unittest.TestCase):
    """UX-14: grouping is chosen by plain-language preset; the raw pHash
    number lives under Advanced but remains the source of truth."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dlg(self, threshold=17):
        d = SettingsDialog(threshold=threshold)
        self.addCleanup(d.deleteLater)
        return d

    def test_default_threshold_selects_recommended_preset(self):
        d = self._dlg(17)
        self.assertEqual("Similar shots (recommended)",
                         d._preset_combo.currentText())

    def test_choosing_preset_sets_threshold(self):
        d = self._dlg(17)
        d._preset_combo.setCurrentIndex(0)
        d._on_preset_chosen(0)  # "Only near-identical"
        self.assertEqual(GROUPING_PRESETS[0][1], d.threshold())

    def test_custom_threshold_shows_custom(self):
        d = self._dlg(15)  # not equal to any preset
        self.assertEqual("Custom", d._preset_combo.currentText())
        self.assertEqual(15, d.threshold())

    def test_advanced_hidden_by_default_and_toggles(self):
        d = self._dlg()
        self.assertFalse(d._advanced_box.isVisible())
        d._advanced_check.setChecked(True)
        self.assertTrue(d._advanced_box.isVisibleTo(d))

    def test_editing_threshold_flips_combo_to_custom(self):
        d = self._dlg(17)
        d._threshold_spin.setValue(3)
        self.assertEqual("Custom", d._preset_combo.currentText())
        self.assertEqual(3, d.threshold())


if __name__ == "__main__":
    unittest.main()
