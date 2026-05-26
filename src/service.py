import asyncio
import contextlib
import math
import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from src.config import CountryConfig, Settings
from src.hero_sms import (
    HeroSmsClientProtocol,
    HeroSmsError,
    HeroSmsNoNumbersError,
)
from src.messages import DEFAULT_LOCALE, translate
from src.storage import AccessCode, JsonStorage, UserSession, normalize_access_code
from src.ui import country_keyboard, render_country_prompt_text


@dataclass(slots=True)
class FlowResult:
    status: str
    session: UserSession | None = None
    access_code: AccessCode | None = None
    remaining_seconds: int | None = None


class BotService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: JsonStorage,
        hero_sms: HeroSmsClientProtocol,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.hero_sms = hero_sms
        self._tasks: set[asyncio.Task[None]] = set()
        self._sms_task_lock = asyncio.Lock()
        self._active_sms_tasks: dict[str, asyncio.Task[None]] = {}
        self._starting_sms_requests: set[str] = set()

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.settings.tg_admins

    async def get_locale(self, user_id: int) -> str:
        return await self.storage.get_locale(user_id, default_locale=DEFAULT_LOCALE)

    async def set_locale(self, user_id: int, locale: str) -> None:
        await self.storage.set_locale(user_id, locale)

    async def has_locale(self, user_id: int) -> bool:
        return await self.storage.has_locale(user_id)

    async def bind_status_message(self, session: UserSession, message_id: int) -> UserSession:
        if session.status_message_id == message_id:
            return session
        updated_session = replace(session, status_message_id=message_id)
        await self.storage.upsert_user_session(updated_session)
        return updated_session

    async def get_user_session(self, user_id: int, bot: Bot | None = None) -> UserSession | None:
        requester_id = self.build_requester_id(user_id)
        session = await self.storage.get_user_session(requester_id)
        if session is None:
            return None
        if await self._cleanup_session_if_expired(session, bot=bot):
            return await self.storage.get_user_session(requester_id)
        return session

    async def list_access_codes(self, service_key: str | None = None) -> list[AccessCode]:
        codes = await self.storage.list_access_codes()
        if service_key is None:
            return codes
        service = self.settings.resolve_service_ref(service_key)
        normalized_service_key = (
            service.key if service is not None else service_key.strip().lower()
        )
        return [code for code in codes if code.service_key == normalized_service_key]

    async def create_access_code(
        self,
        *,
        service_key: str,
        custom_code: str | None = None,
    ) -> tuple[str, AccessCode | None]:
        service = self.settings.resolve_service_ref(service_key)
        if service is None:
            return "service_missing", None

        existing_codes = {item.code for item in await self.storage.list_access_codes()}
        code = normalize_access_code(custom_code) if custom_code else self._generate_access_code(existing_codes)
        if not code or code in existing_codes:
            return "duplicate", None

        access_code = AccessCode(
            code=code,
            service_key=service.key,
            created_at=datetime.now(timezone.utc),
        )
        await self.storage.add_access_codes([access_code])
        return "created", access_code

    async def create_access_codes(
        self,
        *,
        service_key: str,
        count: int,
    ) -> tuple[str, list[AccessCode] | None]:
        service = self.settings.resolve_service_ref(service_key)
        if service is None:
            return "service_missing", None
        if count <= 0:
            return "invalid_count", None

        existing_codes = {item.code for item in await self.storage.list_access_codes()}
        created: list[AccessCode] = []
        for _ in range(count):
            code = self._generate_access_code(existing_codes | {item.code for item in created})
            created.append(
                AccessCode(
                    code=code,
                    service_key=service.key,
                    created_at=datetime.now(timezone.utc),
                )
            )

        await self.storage.add_access_codes(created)
        return "created", created

    async def delete_access_code(self, code: str) -> bool:
        return await self.storage.delete_access_code(code)

    async def activate_access_code(
        self,
        *,
        user_id: int,
        chat_id: int,
        username: str | None,
        full_name: str | None,
        code: str,
    ) -> FlowResult:
        await self.cleanup_expired_sessions()
        requester_id = self.build_requester_id(user_id)
        normalized_code = normalize_access_code(code)
        current_session = await self.get_user_session(user_id)

        if current_session is not None:
            if current_session.is_waiting_sms():
                return FlowResult(status="waiting_sms", session=current_session)
            return FlowResult(status="awaiting_country", session=current_session)

        reserve_status, access_code = await self.storage.reserve_access_code(
            normalized_code,
            requester_id,
        )
        if reserve_status == "missing":
            return FlowResult(status="missing")
        if reserve_status == "consumed":
            return FlowResult(status="consumed", access_code=access_code)
        if reserve_status == "reserved":
            return FlowResult(status="reserved", access_code=access_code)
        if access_code is None:
            return FlowResult(status="missing")

        service = self.settings.get_service(access_code.service_key)
        if service is None:
            await self.storage.release_access_code_reservation(access_code.code, requester_id)
            return FlowResult(status="service_missing", access_code=access_code)

        existing_session = await self.storage.get_user_session(requester_id)
        if reserve_status == "reserved_by_self" and existing_session is not None:
            return FlowResult(status="awaiting_country", session=existing_session, access_code=access_code)

        now = datetime.now(timezone.utc)
        session = UserSession(
            requester_id=requester_id,
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            full_name=full_name,
            service_key=service.key,
            access_code=access_code.code,
            state="awaiting_country",
            country_key=None,
            country_name=None,
            activation_id=None,
            phone_number=None,
            created_at=now,
            updated_at=now,
        )
        await self.storage.upsert_user_session(session)
        return FlowResult(status="awaiting_country", session=session, access_code=access_code)

    async def reset_pending_code(self, user_id: int, bot: Bot | None = None) -> FlowResult:
        requester_id = self.build_requester_id(user_id)
        session = await self.get_user_session(user_id, bot=bot)
        if session is None:
            return FlowResult(status="missing")
        if session.is_waiting_sms():
            return FlowResult(status="waiting_sms", session=session)

        await self.storage.release_access_code_reservation(session.access_code, requester_id)
        await self.storage.clear_user_session(requester_id)
        return FlowResult(status="cleared", session=session)

    async def start_sms_request(
        self,
        *,
        bot: Bot,
        user_id: int,
        chat_id: int,
        country_key: str,
    ) -> FlowResult:
        await self.cleanup_expired_sessions(bot=bot)
        requester_id = self.build_requester_id(user_id)
        session = await self.get_user_session(user_id, bot=bot)
        if session is None:
            return FlowResult(status="missing")

        if session.is_waiting_sms():
            await self.ensure_sms_request_task(bot, user_id)
            return FlowResult(status="running", session=session)

        service = self.settings.get_service(session.service_key)
        if service is None:
            return FlowResult(status="service_missing", session=session)

        country = self.settings.get_country(country_key)
        if country is None or not self._country_allowed_for_service(service.key, country.key):
            return FlowResult(status="unknown_country", session=session)

        async with self._sms_task_lock:
            active_task = self._active_sms_tasks.get(requester_id)
            if requester_id in self._starting_sms_requests or (
                active_task is not None and not active_task.done()
            ):
                return FlowResult(status="running", session=session)
            self._starting_sms_requests.add(requester_id)

        purchase_failed = True
        try:
            purchase = await self.hero_sms.buy_number(service.hero_sms_code, country.provider_name)
            purchase_failed = False
        except asyncio.CancelledError:
            raise
        except HeroSmsNoNumbersError:
            return FlowResult(status="no_numbers", session=session)
        except HeroSmsError:
            return FlowResult(status="provider_error", session=session)
        except Exception:
            return FlowResult(status="provider_error", session=session)
        finally:
            if purchase_failed:
                async with self._sms_task_lock:
                    self._starting_sms_requests.discard(requester_id)

        now = datetime.now(timezone.utc)
        updated_session = replace(
            session,
            state="waiting_sms",
            country_key=country.key,
            country_name=country.provider_name,
            activation_id=purchase.activation_id,
            phone_number=purchase.phone_number,
            updated_at=now,
            sms_requested_at=now,
            cancel_unlocked_at=now
            + timedelta(seconds=self.settings.hero_sms_cancel_unlock_seconds),
        )
        await self.storage.upsert_user_session(updated_session)
        await self._ensure_wait_task(bot, updated_session)
        return FlowResult(status="started", session=updated_session)

    async def cancel_sms_request(self, user_id: int, bot: Bot | None = None) -> FlowResult:
        requester_id = self.build_requester_id(user_id)
        session = await self.get_user_session(user_id, bot=bot)
        if session is None or not session.is_waiting_sms() or not session.activation_id:
            return FlowResult(status="missing")

        remaining_seconds = self.get_cancel_remaining_seconds(session)
        if remaining_seconds > 0:
            return FlowResult(
                status="locked",
                session=session,
                remaining_seconds=remaining_seconds,
            )

        task_to_cancel: asyncio.Task[None] | None = None
        async with self._sms_task_lock:
            self._starting_sms_requests.discard(requester_id)
            active_task = self._active_sms_tasks.pop(requester_id, None)
            if active_task is not None and not active_task.done():
                active_task.cancel()
                task_to_cancel = active_task

        if task_to_cancel is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task_to_cancel

        with contextlib.suppress(Exception):
            await self.hero_sms.cancel_activation(session.activation_id)
        updated_session = await self._restore_country_selection(session, bot=bot)
        return FlowResult(status="cancelled", session=updated_session)

    async def ensure_sms_request_task(self, bot: Bot, user_id: int) -> None:
        session = await self.get_user_session(user_id, bot=bot)
        if session is None or not session.is_waiting_sms() or not session.activation_id:
            return
        await self._ensure_wait_task(bot, session)

    async def cleanup_expired_sessions(self, bot: Bot | None = None) -> None:
        sessions = await self.storage.list_user_sessions()
        for session in sessions:
            await self._cleanup_session_if_expired(session, bot=bot)

    async def resume_pending_requests(self, bot: Bot) -> None:
        await self.cleanup_expired_sessions(bot=bot)
        sessions = await self.storage.list_user_sessions()
        for session in sessions:
            if not session.is_waiting_sms() or not session.activation_id:
                continue
            await self._ensure_wait_task(bot, session)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.hero_sms.close()

    def get_service_name(self, service_key: str) -> str:
        service = self.settings.get_service(service_key)
        return service.name if service is not None else service_key

    def get_countries_for_service(self, service_key: str) -> list[CountryConfig]:
        return self.settings.get_countries_for_service(service_key)

    def get_cancel_remaining_seconds(self, session: UserSession) -> int:
        if session.cancel_unlocked_at is None:
            return 0
        delta = (session.cancel_unlocked_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, math.ceil(delta))

    def format_duration(self, total_seconds: int) -> str:
        seconds = max(0, int(total_seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        parts: list[str] = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def format_request_window(self, locale: str) -> str:
        total_seconds = max(0, int(self.settings.hero_sms_request_timeout_seconds))
        if total_seconds >= 60 and total_seconds % 60 == 0:
            minutes = total_seconds // 60
            if locale == "ru":
                return f"{minutes} минут"
            return f"{minutes} minutes"
        return self.format_duration(total_seconds)

    def describe_access_code_state(self, locale: str, access_code: AccessCode) -> str:
        key = {
            "available": "state_available",
            "reserved": "state_reserved",
            "consumed": "state_consumed",
        }[access_code.state()]
        return translate(locale, key)

    def split_message(self, text: str, limit: int = 3900) -> list[str]:
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text
        while len(remaining) > limit:
            split_at = remaining.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip("\n")
        if remaining:
            chunks.append(remaining)
        return chunks

    @staticmethod
    def build_requester_id(user_id: int) -> str:
        return f"tg:{user_id}"

    def _country_allowed_for_service(self, service_key: str, country_key: str) -> bool:
        allowed_countries = self.settings.get_countries_for_service(service_key)
        return any(country.key == country_key for country in allowed_countries)

    def _generate_access_code(self, used_codes: set[str], length: int = 12) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(length))
            if code not in used_codes:
                return code

    def _is_request_expired(self, session: UserSession) -> bool:
        if session.sms_requested_at is None:
            return True
        deadline = session.sms_requested_at + timedelta(
            seconds=self.settings.hero_sms_request_timeout_seconds
        )
        return datetime.now(timezone.utc) >= deadline

    def _is_code_reservation_expired(self, session: UserSession) -> bool:
        if not session.is_awaiting_country():
            return False
        deadline = session.updated_at + timedelta(
            seconds=self.settings.access_code_reservation_timeout_seconds
        )
        return datetime.now(timezone.utc) >= deadline

    async def _ensure_wait_task(self, bot: Bot, session: UserSession) -> None:
        async with self._sms_task_lock:
            active_task = self._active_sms_tasks.get(session.requester_id)
            if active_task is not None and not active_task.done():
                return

            self._starting_sms_requests.discard(session.requester_id)
            task = asyncio.create_task(self._wait_for_sms(bot=bot, session=session))
            self._active_sms_tasks[session.requester_id] = task

        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(
            lambda done_task, requester_id=session.requester_id: self._drop_sms_task(
                requester_id,
                done_task,
            )
        )

    def _drop_sms_task(self, requester_id: str, task: asyncio.Task[None]) -> None:
        current_task = self._active_sms_tasks.get(requester_id)
        if current_task is task:
            self._active_sms_tasks.pop(requester_id, None)

    async def _cleanup_session_if_expired(
        self,
        session: UserSession,
        *,
        bot: Bot | None = None,
    ) -> bool:
        if self._is_code_reservation_expired(session):
            await self.storage.release_access_code_reservation(
                session.access_code,
                session.requester_id,
            )
            await self.storage.clear_user_session(session.requester_id)
            return True

        if session.is_waiting_sms() and self._is_request_expired(session):
            await self._cancel_wait_task(session.requester_id)
            if session.activation_id is not None:
                with contextlib.suppress(Exception):
                    await self.hero_sms.cancel_activation(session.activation_id)
            await self._restore_country_selection(session, bot=bot)
            return True

        return False

    async def _cancel_wait_task(self, requester_id: str) -> None:
        task_to_cancel: asyncio.Task[None] | None = None
        current_task = asyncio.current_task()

        async with self._sms_task_lock:
            self._starting_sms_requests.discard(requester_id)
            active_task = self._active_sms_tasks.pop(requester_id, None)
            if (
                active_task is not None
                and not active_task.done()
                and active_task is not current_task
            ):
                active_task.cancel()
                task_to_cancel = active_task

        if task_to_cancel is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task_to_cancel

    async def _restore_country_selection(
        self,
        session: UserSession,
        *,
        bot: Bot | None = None,
    ) -> UserSession:
        updated_session = replace(
            session,
            state="awaiting_country",
            country_key=None,
            country_name=None,
            activation_id=None,
            phone_number=None,
            updated_at=datetime.now(timezone.utc),
            sms_requested_at=None,
            cancel_unlocked_at=None,
        )
        await self.storage.upsert_user_session(updated_session)
        if bot is None:
            return updated_session

        locale = await self.get_locale(updated_session.user_id)
        text = render_country_prompt_text(locale, self, updated_session)
        markup = country_keyboard(
            locale,
            updated_session.user_id,
            self,
            updated_session.service_key,
        )

        if updated_session.status_message_id is not None:
            with contextlib.suppress(Exception):
                await bot.edit_message_text(
                    text=text,
                    chat_id=updated_session.chat_id,
                    message_id=updated_session.status_message_id,
                    reply_markup=markup,
                )
                return updated_session

        with contextlib.suppress(Exception):
            sent_message = await bot.send_message(
                updated_session.chat_id,
                text,
                reply_markup=markup,
            )
            message_id = getattr(sent_message, "message_id", None)
            if message_id is not None:
                return await self.bind_status_message(updated_session, message_id)
        return updated_session

    async def _wait_for_sms(self, *, bot: Bot, session: UserSession) -> None:
        if session.activation_id is None:
            return

        active_session = session
        try:
            while not self._is_request_expired(session):
                current_session = await self.storage.get_user_session(session.requester_id)
                if current_session is None:
                    return
                if not current_session.is_waiting_sms():
                    return
                if current_session.activation_id != session.activation_id:
                    return
                active_session = current_session

                status_text = await self.hero_sms.get_status(session.activation_id)
                if "STATUS_OK:" in status_text:
                    code = status_text.split(":", 1)[1].strip()
                    await self.storage.consume_access_code(
                        active_session.access_code,
                        active_session.requester_id,
                    )
                    with contextlib.suppress(Exception):
                        await self.hero_sms.finish_activation(session.activation_id)
                    await self.storage.clear_user_session(active_session.requester_id)
                    locale = await self.get_locale(active_session.user_id)
                    with contextlib.suppress(Exception):
                        await bot.send_message(
                            active_session.chat_id,
                            translate(
                                locale,
                                "sms_code_found",
                                phone=active_session.phone_number or "-",
                                code=code,
                            ),
                        )
                    return

                if "STATUS_CANCEL" in status_text:
                    await self._restore_country_selection(active_session, bot=bot)
                    return

                await asyncio.sleep(self.settings.hero_sms_poll_interval_seconds)

            with contextlib.suppress(Exception):
                await self.hero_sms.cancel_activation(session.activation_id)
            await self._restore_country_selection(active_session, bot=bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            with contextlib.suppress(Exception):
                await self.hero_sms.cancel_activation(session.activation_id)
            latest_session = await self.storage.get_user_session(session.requester_id)
            active_session = latest_session or active_session
            updated_session = await self._restore_country_selection(active_session, bot=bot)
            locale = await self.get_locale(active_session.user_id)
            with contextlib.suppress(Exception):
                await bot.send_message(
                    updated_session.chat_id,
                    translate(
                        locale,
                        "sms_failed",
                        phone=active_session.phone_number or "-",
                    ),
                )
