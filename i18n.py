import os
import sys
import json


class I18n:
    def __init__(self, language: str = "vi-VN", i18n_dir: str = "i18n"):
        self.language = language
        self.i18n_dir = self._resolve_i18n_dir(i18n_dir)
        self.translations = {}
        self._load(language)

    @staticmethod
    def _resolve_i18n_dir(preferred_dir: str) -> str:
        candidates = [
            preferred_dir,
            os.path.join(preferred_dir, "i18n"),
            os.path.join(os.path.dirname(preferred_dir), "i18n"),
            os.path.join(os.path.dirname(preferred_dir), "_internal", "i18n"),
            os.path.join(os.path.dirname(sys.executable), "i18n"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "i18n"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "i18n"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n"),
        ]
        for c in candidates:
            if c and os.path.isdir(c) and os.path.exists(os.path.join(c, "vi-VN.json")):
                return c
        return preferred_dir

    def _load(self, language: str):
        filepath = os.path.join(self.i18n_dir, f"{language}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception as e:
                from core.logger import get_logger
                get_logger().error(f"[i18n] Load error: {e}")

    def t(self, key: str, **kwargs) -> str:
        text = self.translations.get(key, key)
        if kwargs:
            for k, v in kwargs.items():
                text = text.replace(f"{{{k}}}", str(v))
        return text

    def set_language(self, language: str):
        self.language = language
        self._load(language)
