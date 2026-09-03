"""Persistent registry of every Click controller ever seen (devices.json)."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("click_bridge")


class Registry:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        self._last_save = 0.0
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))
            self._last_save = time.monotonic()
        except Exception as e:
            log.warning("could not write %s: %s", self.path.name, e)

    def record_sighting(self, mac, name):
        now = datetime.now().isoformat(timespec="seconds")
        entry = self.data.setdefault(mac, {})
        is_new = "first_seen" not in entry
        if is_new:
            entry["first_seen"] = now
        entry["last_seen"] = now
        if name and not entry.get("name"):
            entry["name"] = name
        # throttle disk writes: always on a brand-new device, else every 30 s
        if is_new or (time.monotonic() - self._last_save) > 30:
            self._save()

    def record_details(self, mac, details):
        entry = self.data.setdefault(mac, {})
        for k, v in details.items():
            if v:
                entry[k] = v
        self._save()

    def flush(self):
        self._save()
