import json
import logging
import os
from pathlib import Path


class CompanionSettings:

    DEFAULTS = {
        "include_prereleases": False,
    }

    def __init__(self):
        self._path = self._get_settings_path()
        self._values = self.DEFAULTS.copy()
        self.load()

    @staticmethod
    def _get_settings_path():
        appdata = os.getenv("APPDATA")

        if appdata:
            config_dir = Path(appdata) / "Switchology"
        else:
            config_dir = Path.home() / ".switchology"

        return config_dir / "companion.json"

    def load(self):
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                self._values.update(data)

        except FileNotFoundError:
            pass

        except (OSError, json.JSONDecodeError) as exc:
            logging.warning(
                f"Could not load settings: {exc}"
            )

    def save(self):
        try:
            self._path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_path = self._path.with_suffix(".tmp")

            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(
                    self._values,
                    f,
                    indent=2,
                )

            temp_path.replace(self._path)

        except OSError as exc:
            logging.warning(
                f"Could not save settings: {exc}"
            )

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        self._values[key] = value
        self.save()


settings = CompanionSettings()