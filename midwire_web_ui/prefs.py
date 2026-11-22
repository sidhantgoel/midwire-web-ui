"""Settings that survive a reboot, kept in one JSON file."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from .models import Preferences, PreferencesUpdate, ProxyOptions

log = logging.getLogger(__name__)


def profile_key(vendor_id: str, product_id: str) -> str:
    return f"{vendor_id}:{product_id}"


class PreferenceStore:
    def __init__(self, path: Path):
        self._path = path
        # Requests run on worker threads and auto-start on another.
        self._lock = threading.Lock()

    def load(self) -> Preferences:
        with self._lock:
            return self._read()

    def update(self, update: PreferencesUpdate) -> Preferences:
        with self._lock:
            prefs = self._read()
            prefs = Preferences(**update.model_dump(), profiles=prefs.profiles)
            self._write(prefs)
            return prefs

    def remember(self, key: str, options: ProxyOptions) -> None:
        with self._lock:
            prefs = self._read()
            prefs.profiles[key] = options
            self._write(prefs)

    def forget(self, key: str) -> Preferences:
        with self._lock:
            prefs = self._read()
            if prefs.profiles.pop(key, None) is not None:
                self._write(prefs)
            return prefs

    def _read(self) -> Preferences:
        try:
            return Preferences.model_validate_json(self._path.read_text())
        except FileNotFoundError:
            return Preferences()
        except (OSError, ValidationError, ValueError) as exc:
            # A damaged file must not stop the UI from loading. Keep it aside
            # so nothing the user set is silently destroyed.
            log.error("Ignoring unreadable settings file %s: %s", self._path, exc)
            try:
                os.replace(self._path, self._path.with_suffix(".json.bad"))
            except OSError:
                pass
            return Preferences()

    def _write(self, prefs: Preferences) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(prefs.model_dump(), indent=2) + "\n")
        os.replace(tmp, self._path)
