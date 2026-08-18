"""Temporary Stage 23 migration: make Apply Strategy to All copy full baseline strategy."""
from pathlib import Path

path = Path("crypto_strategy_lab/gui/profile_editor.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        'copy_rules_btn=QPushButton("Apply Rules to All")',
        'copy_strategy_btn=QPushButton("Apply Strategy to All Profiles")',
    ),
    (
        'buttons.addWidget(copy_rules_btn)',
        'buttons.addWidget(copy_strategy_btn)',
    ),
    (
        'copy_btn.clicked.connect(lambda:setattr(self,"clipboard",deepcopy(self.profiles[self.current]))); paste_btn.clicked.connect(self._paste); reset_btn.clicked.connect(self._reset); copy_rules_btn.clicked.connect(self._apply_rules_to_all); self.list.currentRowChanged.connect(self._select); self.mode.currentTextChanged.connect(self.changed); self.mode.currentIndexChanged.connect(self._update_mode_help)',
        'copy_btn.clicked.connect(lambda:setattr(self,"clipboard",deepcopy(self.profiles[self.current]))); paste_btn.clicked.connect(self._paste); reset_btn.clicked.connect(self._reset); copy_strategy_btn.clicked.connect(self._apply_strategy_to_all); self.list.currentRowChanged.connect(self._select); self.mode.currentTextChanged.connect(self.changed); self.mode.currentIndexChanged.connect(self._update_mode_help)',
    ),
    (
        '    def _apply_rules_to_all(self):\n        """Apply current profile\'s entry rules to all other profiles."""\n        current_rules=self.profiles[self.current].entry_rules\n        for key in PROFILE_KEYS:\n            if key!=self.current:\n                self.profiles[key]=replace(self.profiles[key], entry_rules=deepcopy(current_rules))\n        self._refresh_list();self.changed.emit()\n',
        '    def _apply_strategy_to_all(self):\n        """Copy the current profile\'s complete baseline strategy to every profile.\n\n        Profile identity controls stay profile-specific: enabled and flip_direction\n        are preserved for each target profile. Every other StrategyProfile field is\n        copied from the current profile, so new strategy fields are included\n        automatically without maintaining a separate allow-list.\n        """\n        source=deepcopy(self.profiles[self.current])\n        for key in PROFILE_KEYS:\n            if key==self.current:\n                continue\n            target=self.profiles[key]\n            self.profiles[key]=replace(source, enabled=target.enabled, flip_direction=target.flip_direction)\n        self._refresh_list();self.changed.emit()\n',
    ),
]

for old, new in replacements:
    if old not in text:
        raise RuntimeError(f"Expected Stage 23 fragment not found: {old[:120]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
