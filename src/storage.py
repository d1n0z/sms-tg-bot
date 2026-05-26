import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonStorageCorruptionError(RuntimeError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"JSON store '{path}' is corrupted: {reason}")


def normalize_access_code(value: str) -> str:
    return value.strip().upper()


def normalize_requester_id(value: str) -> str:
    return value.strip()


def _parse_datetime(raw_value: Any) -> datetime | None:
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        parsed = datetime.fromisoformat(str(raw_value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True, frozen=True)
class AccessCode:
    code: str
    service_key: str
    created_at: datetime
    reserved_by: str | None = None
    reserved_at: datetime | None = None
    consumed_by: str | None = None
    consumed_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccessCode":
        return cls(
            code=normalize_access_code(str(data["code"])),
            service_key=str(data["service_key"]).strip().lower(),
            created_at=_parse_datetime(data["created_at"]) or datetime.now(timezone.utc),
            reserved_by=normalize_requester_id(str(data["reserved_by"]))
            if data.get("reserved_by")
            else None,
            reserved_at=_parse_datetime(data.get("reserved_at")),
            consumed_by=normalize_requester_id(str(data["consumed_by"]))
            if data.get("consumed_by")
            else None,
            consumed_at=_parse_datetime(data.get("consumed_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "service_key": self.service_key,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "reserved_by": self.reserved_by,
            "reserved_at": self.reserved_at.astimezone(timezone.utc).isoformat()
            if self.reserved_at is not None
            else None,
            "consumed_by": self.consumed_by,
            "consumed_at": self.consumed_at.astimezone(timezone.utc).isoformat()
            if self.consumed_at is not None
            else None,
        }

    def is_consumed(self) -> bool:
        return self.consumed_by is not None

    def is_reserved(self) -> bool:
        return self.reserved_by is not None and not self.is_consumed()

    def state(self) -> str:
        if self.is_consumed():
            return "consumed"
        if self.is_reserved():
            return "reserved"
        return "available"


@dataclass(slots=True, frozen=True)
class UserSession:
    requester_id: str
    user_id: int
    chat_id: int
    username: str | None
    full_name: str | None
    service_key: str
    access_code: str
    state: str
    country_key: str | None
    country_name: str | None
    activation_id: str | None
    phone_number: str | None
    created_at: datetime
    updated_at: datetime
    sms_requested_at: datetime | None = None
    cancel_unlocked_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserSession":
        created_at = _parse_datetime(data["created_at"]) or datetime.now(timezone.utc)
        return cls(
            requester_id=normalize_requester_id(str(data["requester_id"])),
            user_id=int(data["user_id"]),
            chat_id=int(data["chat_id"]),
            username=data.get("username"),
            full_name=data.get("full_name"),
            service_key=str(data["service_key"]).strip().lower(),
            access_code=normalize_access_code(str(data["access_code"])),
            state=str(data["state"]).strip().lower(),
            country_key=str(data["country_key"]).strip().lower()
            if data.get("country_key")
            else None,
            country_name=str(data["country_name"]).strip()
            if data.get("country_name")
            else None,
            activation_id=str(data["activation_id"]).strip()
            if data.get("activation_id")
            else None,
            phone_number=str(data["phone_number"]).strip()
            if data.get("phone_number")
            else None,
            created_at=created_at,
            updated_at=_parse_datetime(data.get("updated_at")) or created_at,
            sms_requested_at=_parse_datetime(data.get("sms_requested_at")),
            cancel_unlocked_at=_parse_datetime(data.get("cancel_unlocked_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requester_id": self.requester_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "username": self.username,
            "full_name": self.full_name,
            "service_key": self.service_key,
            "access_code": self.access_code,
            "state": self.state,
            "country_key": self.country_key,
            "country_name": self.country_name,
            "activation_id": self.activation_id,
            "phone_number": self.phone_number,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "updated_at": self.updated_at.astimezone(timezone.utc).isoformat(),
            "sms_requested_at": self.sms_requested_at.astimezone(timezone.utc).isoformat()
            if self.sms_requested_at is not None
            else None,
            "cancel_unlocked_at": self.cancel_unlocked_at.astimezone(timezone.utc).isoformat()
            if self.cancel_unlocked_at is not None
            else None,
        }

    def is_waiting_sms(self) -> bool:
        return self.state == "waiting_sms"

    def is_awaiting_country(self) -> bool:
        return self.state == "awaiting_country"


class JsonStorage:
    def __init__(
        self,
        *,
        access_code_store_path: Path,
        user_session_store_path: Path,
        user_locale_store_path: Path,
    ) -> None:
        self.access_code_store_path = access_code_store_path
        self.user_session_store_path = user_session_store_path
        self.user_locale_store_path = user_locale_store_path
        self._code_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._locale_lock = asyncio.Lock()

    async def add_access_codes(self, codes: list[AccessCode]) -> None:
        if not codes:
            return
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={}, strict=True)
            for access_code in codes:
                data[access_code.code] = access_code.to_dict()
            self._write_json(self.access_code_store_path, data)

    async def get_access_code(self, code: str) -> AccessCode | None:
        normalized_code = normalize_access_code(code)
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={})
            raw_value = data.get(normalized_code)
            if not isinstance(raw_value, dict):
                return None
            return AccessCode.from_dict(raw_value)

    async def list_access_codes(self) -> list[AccessCode]:
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={})

        items: list[AccessCode] = []
        for raw_value in data.values():
            if not isinstance(raw_value, dict):
                continue
            try:
                items.append(AccessCode.from_dict(raw_value))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(items, key=lambda item: (item.state(), item.service_key, item.code))

    async def delete_access_code(self, code: str) -> bool:
        normalized_code = normalize_access_code(code)
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={}, strict=True)
            removed = data.pop(normalized_code, None)
            if removed is None:
                return False
            self._write_json(self.access_code_store_path, data)
            return True

    async def reserve_access_code(
        self,
        code: str,
        requester_id: str,
    ) -> tuple[str, AccessCode | None]:
        normalized_code = normalize_access_code(code)
        normalized_requester_id = normalize_requester_id(requester_id)
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={}, strict=True)
            raw_value = data.get(normalized_code)
            if not isinstance(raw_value, dict):
                return "missing", None

            access_code = AccessCode.from_dict(raw_value)
            if access_code.is_consumed():
                return "consumed", access_code
            if access_code.reserved_by and access_code.reserved_by != normalized_requester_id:
                return "reserved", access_code
            if access_code.reserved_by == normalized_requester_id:
                return "reserved_by_self", access_code

            updated = AccessCode(
                code=access_code.code,
                service_key=access_code.service_key,
                created_at=access_code.created_at,
                reserved_by=normalized_requester_id,
                reserved_at=datetime.now(timezone.utc),
                consumed_by=access_code.consumed_by,
                consumed_at=access_code.consumed_at,
            )
            data[normalized_code] = updated.to_dict()
            self._write_json(self.access_code_store_path, data)
            return "ok", updated

    async def consume_access_code(
        self,
        code: str,
        requester_id: str,
    ) -> tuple[str, AccessCode | None]:
        normalized_code = normalize_access_code(code)
        normalized_requester_id = normalize_requester_id(requester_id)
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={}, strict=True)
            raw_value = data.get(normalized_code)
            if not isinstance(raw_value, dict):
                return "missing", None

            access_code = AccessCode.from_dict(raw_value)
            if access_code.is_consumed():
                return "consumed", access_code
            if access_code.reserved_by not in (None, normalized_requester_id):
                return "reserved", access_code

            now = datetime.now(timezone.utc)
            updated = AccessCode(
                code=access_code.code,
                service_key=access_code.service_key,
                created_at=access_code.created_at,
                reserved_by=access_code.reserved_by or normalized_requester_id,
                reserved_at=access_code.reserved_at or now,
                consumed_by=normalized_requester_id,
                consumed_at=now,
            )
            data[normalized_code] = updated.to_dict()
            self._write_json(self.access_code_store_path, data)
            return "ok", updated

    async def release_access_code_reservation(
        self,
        code: str,
        requester_id: str,
    ) -> bool:
        normalized_code = normalize_access_code(code)
        normalized_requester_id = normalize_requester_id(requester_id)
        async with self._code_lock:
            data = self._load_json(self.access_code_store_path, default={}, strict=True)
            raw_value = data.get(normalized_code)
            if not isinstance(raw_value, dict):
                return False

            access_code = AccessCode.from_dict(raw_value)
            if access_code.is_consumed() or access_code.reserved_by != normalized_requester_id:
                return False

            updated = AccessCode(
                code=access_code.code,
                service_key=access_code.service_key,
                created_at=access_code.created_at,
            )
            data[normalized_code] = updated.to_dict()
            self._write_json(self.access_code_store_path, data)
            return True

    async def upsert_user_session(self, session: UserSession) -> None:
        async with self._session_lock:
            data = self._load_json(self.user_session_store_path, default={}, strict=True)
            data[session.requester_id] = session.to_dict()
            self._write_json(self.user_session_store_path, data)

    async def get_user_session(self, requester_id: str) -> UserSession | None:
        normalized_requester_id = normalize_requester_id(requester_id)
        async with self._session_lock:
            data = self._load_json(self.user_session_store_path, default={})
            raw_value = data.get(normalized_requester_id)
            if not isinstance(raw_value, dict):
                return None
            return UserSession.from_dict(raw_value)

    async def list_user_sessions(self) -> list[UserSession]:
        async with self._session_lock:
            data = self._load_json(self.user_session_store_path, default={})

        sessions: list[UserSession] = []
        for raw_value in data.values():
            if not isinstance(raw_value, dict):
                continue
            try:
                sessions.append(UserSession.from_dict(raw_value))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(sessions, key=lambda item: item.requester_id)

    async def clear_user_session(self, requester_id: str) -> bool:
        normalized_requester_id = normalize_requester_id(requester_id)
        async with self._session_lock:
            data = self._load_json(self.user_session_store_path, default={}, strict=True)
            removed = data.pop(normalized_requester_id, None)
            if removed is None:
                return False
            self._write_json(self.user_session_store_path, data)
            return True

    async def get_locale(self, user_id: int, default_locale: str = "ru") -> str:
        async with self._locale_lock:
            data = self._load_json(self.user_locale_store_path, default={})
            locale = data.get(str(user_id), default_locale)
            if locale not in {"ru", "en"}:
                return default_locale
            return locale

    async def has_locale(self, user_id: int) -> bool:
        async with self._locale_lock:
            data = self._load_json(self.user_locale_store_path, default={})
            return data.get(str(user_id)) in {"ru", "en"}

    async def set_locale(self, user_id: int, locale: str) -> None:
        async with self._locale_lock:
            data = self._load_json(self.user_locale_store_path, default={}, strict=True)
            data[str(user_id)] = locale
            self._write_json(self.user_locale_store_path, data)

    def _load_json(self, path: Path, *, default: Any, strict: bool = False) -> Any:
        if not path.exists():
            return default

        raw_content = path.read_text(encoding="utf-8").strip()
        if not raw_content:
            return default

        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            if strict:
                raise JsonStorageCorruptionError(path, str(exc)) from exc
            return default

        if isinstance(default, dict) and not isinstance(data, dict):
            if strict:
                raise JsonStorageCorruptionError(path, "expected a JSON object")
            return default
        return data

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temp_name = temporary_file.name
        os.replace(temp_name, path)
