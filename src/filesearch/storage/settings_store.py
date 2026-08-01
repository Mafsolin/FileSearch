from __future__ import annotations

import json
import os
import re
import uuid
import time
from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values

from filesearch.app_paths import env_path, settings_path
from filesearch.app_paths import database_path as default_database_path
from filesearch.domain.models import ProviderProfile, VisionProfile
from filesearch.providers.validation import normalize_base_url

ROUTERAI_ID = "routerai"
DEFAULT_ROUTERAI = ProviderProfile(
    id=ROUTERAI_ID,
    name="RouterAI",
    base_url="https://routerai.ru/api/v1",
    model="google/gemini-embedding-2",
    key_name="FILESEARCH_ROUTERAI_API_KEY",
    builtin=True,
)
DEFAULT_ROUTERAI_VISION = VisionProfile("routerai-vision", "RouterAI Vision", "https://routerai.ru/api/v1", "qwen/qwen3.7-flash", "FILESEARCH_ROUTERAI_API_KEY", True)


class SettingsStore:
    def __init__(self, path: Path | None = None, secrets_path: Path | None = None) -> None:
        self.path = path or settings_path()
        self.secrets_path = secrets_path or env_path()
        self.warning: str | None = None

    def pop_warning(self) -> str | None:
        warning, self.warning = self.warning, None
        return warning

    def load_profiles(self) -> list[ProviderProfile]:
        raw = self._load_json()
        profiles = [DEFAULT_ROUTERAI]
        seen = {DEFAULT_ROUTERAI.id}
        invalid = 0
        for item in raw.get("providers", []):
            if not isinstance(item, dict):
                invalid += 1
                continue
            required = {"id", "name", "base_url", "model", "key_name"}
            if not required.issubset(item):
                invalid += 1
                continue
            try:
                values = {key: item[key].strip() for key in required if isinstance(item[key], str)}
                if len(values) != len(required) or any(not values[key] for key in required):
                    raise ValueError("empty provider field")
                if values["id"] in seen:
                    raise ValueError("duplicate provider id")
                values["base_url"] = normalize_base_url(values["base_url"])
                raw_vision = item.get("vision_model")
                vision_model = raw_vision.strip() if isinstance(raw_vision, str) and raw_vision.strip() else None
                profiles.append(ProviderProfile(**values, builtin=False, vision_model=vision_model))
                seen.add(values["id"])
            except (TypeError, ValueError):
                invalid += 1
                continue
        if invalid:
            self._warn(f"Пропущено некорректных профилей провайдеров: {invalid}.")
        return [self._selected_model(p, False) for p in profiles]

    def save_profiles(self, profiles: list[ProviderProfile]) -> None:
        custom = [profile.__dict__ for profile in profiles if not profile.builtin]
        raw = self._load_json()
        raw["providers"] = custom
        self._save_json(raw)

    def load_vision_profiles(self) -> list[VisionProfile]:
        raw = self._load_json(); result = [DEFAULT_ROUTERAI_VISION]; seen = {DEFAULT_ROUTERAI_VISION.id}; invalid = 0
        for item in raw.get("vision_providers", []):
            if not isinstance(item, dict): invalid += 1; continue
            try:
                fields = [item[key].strip() if isinstance(item[key], str) else "" for key in ("id", "name", "base_url", "model", "key_name")]
                if not all(fields) or fields[0] in seen: raise ValueError("invalid vision profile")
                fields[2] = normalize_base_url(fields[2])
                result.append(VisionProfile(*fields, False)); seen.add(fields[0])
            except (KeyError, TypeError, ValueError): invalid += 1; continue
        if invalid: self._warn(f"Пропущено некорректных vision-профилей: {invalid}.")
        return [self._selected_model(p, True) for p in result]

    def provider_models(self, profile, vision: bool = False) -> list[str]:
        key = "vision_provider_models" if vision else "provider_models"
        catalogs = self._load_json().get(key, {})
        if not isinstance(catalogs, dict):
            self._warn(f"Некорректный каталог моделей {key}; использована модель профиля.")
            return [profile.model]
        values = catalogs.get(profile.id, [profile.model])
        if not isinstance(values, (list, tuple)):
            self._warn(f"Некорректный список моделей профиля {profile.id}; использована модель профиля.")
            return [profile.model]
        result = [str(x).strip() for x in values if str(x).strip()]
        return list(dict.fromkeys(result)) or [profile.model]

    def save_provider_models(self, profile_id: str, models: list[str], active: str, vision: bool = False) -> None:
        models = list(dict.fromkeys(x.strip() for x in models if x.strip()))
        if not models: raise ValueError("У провайдера должна остаться хотя бы одна модель.")
        if active not in models: active = models[0]
        raw = self._load_json(); list_key = "vision_provider_models" if vision else "provider_models"; active_key = "vision_active_models" if vision else "provider_active_models"
        stored_catalogs = raw.get(list_key, {})
        catalogs = dict(stored_catalogs) if isinstance(stored_catalogs, dict) else {}
        catalogs[profile_id] = models; raw[list_key] = catalogs
        stored_active = raw.get(active_key, {})
        active_models = dict(stored_active) if isinstance(stored_active, dict) else {}
        active_models[profile_id] = active; raw[active_key] = active_models; self._save_json(raw)

    def _selected_model(self, profile, vision: bool):
        raw = self._load_json(); active_key = "vision_active_models" if vision else "provider_active_models"
        active_models = raw.get(active_key, {})
        if not isinstance(active_models, dict):
            self._warn(f"Некорректный выбор активных моделей {active_key}; использована модель профиля.")
            active_models = {}
        models = self.provider_models(profile, vision); active = active_models.get(profile.id, profile.model)
        return replace(profile, model=active if active in models else models[0])

    def save_vision_profiles(self, profiles: list[VisionProfile]) -> None:
        raw = self._load_json(); raw["vision_providers"] = [p.__dict__ for p in profiles if not p.builtin]; self._save_json(raw)

    def active_vision_provider_id(self) -> str:
        return self._load_json().get("active_vision_provider", DEFAULT_ROUTERAI_VISION.id)

    def set_active_vision_provider_id(self, value: str) -> None:
        raw = self._load_json(); raw["active_vision_provider"] = value; self._save_json(raw)

    @staticmethod
    def new_vision_profile(name: str, base_url: str, model: str) -> VisionProfile:
        identifier = uuid.uuid4().hex
        return VisionProfile(identifier, name.strip(), normalize_base_url(base_url), model.strip(), f"FILESEARCH_VISION_{identifier.upper()}_API_KEY")

    def active_provider_id(self) -> str:
        return self._load_json().get("active_provider", ROUTERAI_ID)

    def set_active_provider_id(self, provider_id: str) -> None:
        raw = self._load_json()
        raw["active_provider"] = provider_id
        self._save_json(raw)

    def theme(self) -> str:
        value = self._load_json().get("theme", "light")
        return value if value in ("light", "dark") else "light"

    def set_theme(self, value: str) -> None:
        raw = self._load_json()
        raw["theme"] = value
        self._save_json(raw)

    def animations_enabled(self) -> bool:
        return bool(self._load_json().get("animations", True))

    def set_animations_enabled(self, value: bool) -> None:
        raw = self._load_json()
        raw["animations"] = bool(value)
        self._save_json(raw)

    def vision_indexing_enabled(self) -> bool:
        return bool(self._load_json().get("vision_indexing_enabled", True))

    def set_vision_indexing_enabled(self, value: bool) -> None:
        raw = self._load_json()
        raw["vision_indexing_enabled"] = bool(value)
        self._save_json(raw)

    def load_roots(self) -> list[Path]:
        return [Path(item) for item in self._load_json().get("roots", [])]

    def save_roots(self, roots: list[Path]) -> None:
        normalized = []
        for value in roots:
            root = Path(value).expanduser().resolve()
            if any(root == other or root in other.parents or other in root.parents for other in normalized):
                raise ValueError("Нельзя добавлять одинаковые или вложенные папки в один индекс.")
            normalized.append(root)
        raw = self._load_json()
        raw["roots"] = [str(root) for root in normalized]
        self._save_json(raw)

    def search_root_enabled(self, root: Path) -> bool:
        disabled = set(self._load_json().get("disabled_search_roots", []))
        return str(Path(root).resolve()) not in disabled

    def set_search_root_enabled(self, root: Path, enabled: bool) -> None:
        raw=self._load_json(); disabled=set(raw.get("disabled_search_roots", [])); value=str(Path(root).resolve())
        if enabled: disabled.discard(value)
        else: disabled.add(value)
        raw["disabled_search_roots"]=sorted(disabled); self._save_json(raw)

    def enabled_search_roots(self) -> list[Path]:
        return [root for root in self.load_roots() if self.search_root_enabled(root)]

    def index_path(self) -> Path:
        value = self._load_json().get("index_path")
        return Path(value).expanduser().resolve() if value else default_database_path()

    def set_index_path(self, path: Path) -> None:
        raw = self._load_json()
        raw["index_path"] = str(Path(path).expanduser().resolve())
        self._save_json(raw)

    def set_index(self, path: Path, roots: list[Path]) -> None:
        """Atomically pair a portable index with exactly the roots it contains."""
        normalized: list[Path] = []
        for value in roots:
            root = Path(value).expanduser().resolve()
            if any(root == other or root in other.parents or other in root.parents for other in normalized):
                raise ValueError("Индекс содержит одинаковые или пересекающиеся корневые папки.")
            normalized.append(root)
        raw = self._load_json()
        raw["index_path"] = str(Path(path).expanduser().resolve())
        raw["roots"] = [str(root) for root in normalized]
        self._save_json(raw)

    def get_key(self, profile: ProviderProfile) -> str:
        """Prefer the key the user saved; fall back to the environment.

        The other order let a stale shell variable silently shadow the key
        entered in the UI, which surfaces as an unexplained 401.
        """
        stored = (dotenv_values(self.secrets_path, interpolate=False).get(profile.key_name) or "").strip()
        return stored or (os.getenv(profile.key_name, "") or "").strip()

    def set_key(self, profile: ProviderProfile, value: str) -> None:
        values = dict(dotenv_values(self.secrets_path, interpolate=False)) if self.secrets_path.exists() else {}
        values[profile.key_name] = value.strip()
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.secrets_path, self._serialize_env(values))

    def delete_key(self, profile) -> None:
        values = dict(dotenv_values(self.secrets_path, interpolate=False)) if self.secrets_path.exists() else {}
        values.pop(profile.key_name, None)
        self._atomic_write(self.secrets_path, self._serialize_env(values))

    @staticmethod
    def _serialize_env(values: dict) -> str:
        """Quote dotenv values without losing newlines, comments or ${...}."""
        lines = []
        for key, raw in values.items():
            value = "" if raw is None else str(raw)
            quoted = value.replace("'", "\\'")
            lines.append(f"{key}='{quoted}'")
        return "\n".join(lines) + ("\n" if lines else "")

    def consent_fingerprint(self, profile: ProviderProfile, vision: VisionProfile | None = None) -> str:
        """Identify exactly what the user agreed to send, and where.

        The vision endpoint receives scanned pages in full, so its URL and model
        belong in the fingerprint: pointing vision at a different host must ask
        again rather than inherit the embedding provider's consent.
        """
        parts = [profile.id, normalize_base_url(profile.base_url), profile.model, profile.vision_model or ""]
        if vision is not None:
            parts += [vision.id, normalize_base_url(vision.base_url), vision.model]
        return "|".join(parts)

    def has_consent(self, profile: ProviderProfile, vision: VisionProfile | None = None) -> bool:
        return self.consent_fingerprint(profile, vision) in self._load_json().get("privacy_consents", [])

    def grant_consent(self, profile: ProviderProfile, vision: VisionProfile | None = None) -> None:
        raw = self._load_json()
        items = set(raw.get("privacy_consents", []))
        items.add(self.consent_fingerprint(profile, vision))
        raw["privacy_consents"] = sorted(items)
        self._save_json(raw)

    @staticmethod
    def new_profile(name: str, base_url: str, model: str, vision_model: str | None = None) -> ProviderProfile:
        identifier = uuid.uuid4().hex
        key_name = "FILESEARCH_PROVIDER_" + re.sub("[^A-Z0-9_]", "_", identifier.upper()) + "_API_KEY"
        return ProviderProfile(identifier, name.strip(), normalize_base_url(base_url), model.strip(), key_name, False, vision_model.strip() if vision_model and vision_model.strip() else None)

    def _load_json(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("settings.json must contain an object")
            return value
        except (OSError, json.JSONDecodeError, ValueError):
            quarantine = self.path.with_name(self.path.name + f".corrupt-{int(time.time())}")
            try:
                self.path.replace(quarantine)
                self.warning = (
                    "Файл настроек повреждён и был перенесён в "
                    f"{quarantine}. FileSearch запущен с безопасными настройками по умолчанию."
                )
            except OSError:
                self.warning = (
                    f"Файл настроек {self.path} повреждён и не может быть прочитан. "
                    "FileSearch запущен с безопасными настройками по умолчанию."
                )
            return {}

    def _warn(self, message: str) -> None:
        if not self.warning:
            self.warning = message
        elif message not in self.warning:
            self.warning += "\n" + message

    def _save_json(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
