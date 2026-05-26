import asyncio
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import Settings
from src.hero_sms import HeroSmsNoNumbersError, HeroSmsPurchase
from src.service import BotService
from src.storage import JsonStorage


class ServiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.storage = JsonStorage(
            access_code_store_path=self.base_path / "codes.json",
            user_session_store_path=self.base_path / "sessions.json",
            user_locale_store_path=self.base_path / "locales.json",
        )
        self.hero_sms = FakeHeroSmsClient()
        self.service = BotService(
            settings=Settings(
                access_code_store_path=self.base_path / "codes.json",
                user_session_store_path=self.base_path / "sessions.json",
                user_locale_store_path=self.base_path / "locales.json",
                hero_sms_poll_interval_seconds=0.01,
                hero_sms_request_timeout_seconds=30,
                access_code_reservation_timeout_seconds=30,
                services=[
                    {
                        "key": "claude",
                        "name": "Claude",
                        "hero_sms_code": "acz",
                    }
                ],
                countries=[
                    {
                        "key": "france",
                        "name": "France",
                        "label_ru": "Франция",
                    }
                ],
            ),
            storage=self.storage,
            hero_sms=self.hero_sms,
        )

    async def asyncTearDown(self) -> None:
        await self.service.shutdown()
        self.temp_dir.cleanup()

    async def test_admin_access_is_closed_without_configured_admins(self) -> None:
        self.assertFalse(self.service.is_admin(999))

    async def test_no_numbers_keeps_code_reserved_but_not_consumed(self) -> None:
        status, access_code = await self.service.create_access_code(service_key="claude")
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        self.hero_sms.buy_error = HeroSmsNoNumbersError("NO_NUMBERS")
        start_result = await self.service.start_sms_request(
            bot=FakeBot(),  # type: ignore[arg-type]
            user_id=1,
            chat_id=10,
            country_key="france",
        )
        self.assertEqual(start_result.status, "no_numbers")

        stored_code = await self.storage.get_access_code(access_code.code)
        assert stored_code is not None
        self.assertTrue(stored_code.is_reserved())
        self.assertFalse(stored_code.is_consumed())

        session = await self.service.get_user_session(1)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertTrue(session.is_awaiting_country())

    async def test_provider_timeout_returns_provider_error_and_keeps_session(self) -> None:
        status, access_code = await self.service.create_access_code(
            service_key="claude",
            custom_code="TIMEOUTCODE",
        )
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        self.hero_sms.buy_error = TimeoutError("network timeout")
        start_result = await self.service.start_sms_request(
            bot=FakeBot(),  # type: ignore[arg-type]
            user_id=1,
            chat_id=10,
            country_key="france",
        )
        self.assertEqual(start_result.status, "provider_error")

        session = await self.service.get_user_session(1)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertTrue(session.is_awaiting_country())

    async def test_successful_request_consumes_code_and_delivers_sms(self) -> None:
        status, access_code = await self.service.create_access_code(service_key="claude")
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        self.hero_sms.statuses = ["STATUS_WAIT_CODE", "STATUS_OK:654321"]
        bot = FakeBot()
        start_result = await self.service.start_sms_request(
            bot=bot,  # type: ignore[arg-type]
            user_id=1,
            chat_id=10,
            country_key="france",
        )
        self.assertEqual(start_result.status, "started")

        for _ in range(100):
            if bot.messages:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(bot.messages, [(10, "Код для `+33123456789`: `654321`")])

        stored_code = await self.storage.get_access_code(access_code.code)
        assert stored_code is not None
        self.assertTrue(stored_code.is_consumed())

        session = await self.service.get_user_session(1)
        self.assertIsNone(session)
        self.assertEqual(self.hero_sms.finished, ["activation-1"])

    async def test_cancel_is_blocked_until_unlock_time(self) -> None:
        status, access_code = await self.service.create_access_code(service_key="claude")
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        self.hero_sms.wait_forever = True
        bot = FakeBot()
        start_result = await self.service.start_sms_request(
            bot=bot,  # type: ignore[arg-type]
            user_id=1,
            chat_id=10,
            country_key="france",
        )
        self.assertEqual(start_result.status, "started")

        locked_result = await self.service.cancel_sms_request(1)
        self.assertEqual(locked_result.status, "locked")
        self.assertIsNotNone(locked_result.remaining_seconds)

        session = await self.service.get_user_session(1)
        assert session is not None
        await self.storage.upsert_user_session(
            replace(
                session,
                cancel_unlocked_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

        cancelled_result = await self.service.cancel_sms_request(1)
        self.assertEqual(cancelled_result.status, "cancelled")
        self.assertEqual(self.hero_sms.cancelled, ["activation-1"])
        self.assertIsNone(await self.service.get_user_session(1))

    async def test_resume_expired_waiting_session_notifies_user(self) -> None:
        now = datetime.now(timezone.utc)
        await self.storage.upsert_user_session(
            service_session(
                requester_id=self.service.build_requester_id(1),
                user_id=1,
                chat_id=10,
                username=None,
                full_name=None,
                service_key="claude",
                access_code="EXPIREWAIT",
                state="waiting_sms",
                country_key="france",
                country_name="France",
                activation_id="activation-9",
                phone_number="+33123456789",
                created_at=now - timedelta(minutes=5),
                updated_at=now - timedelta(minutes=5),
                sms_requested_at=now - timedelta(seconds=31),
                cancel_unlocked_at=now - timedelta(seconds=1),
            )
        )

        bot = FakeBot()
        await self.service.resume_pending_requests(bot)  # type: ignore[arg-type]

        self.assertIsNone(await self.service.get_user_session(1))
        self.assertEqual(self.hero_sms.cancelled, ["activation-9"])
        self.assertEqual(
            bot.messages,
            [(10, "Время ожидания для `+33123456789` истекло. Активация отменена.")],
        )

    async def test_new_text_does_not_replace_pending_code_until_reset(self) -> None:
        first_status, first_code = await self.service.create_access_code(
            service_key="claude",
            custom_code="FIRSTCODE",
        )
        second_status, second_code = await self.service.create_access_code(
            service_key="claude",
            custom_code="SECONDCODE",
        )
        self.assertEqual(first_status, "created")
        self.assertEqual(second_status, "created")
        assert first_code is not None
        assert second_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=first_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        repeated_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=second_code.code,
        )
        self.assertEqual(repeated_result.status, "awaiting_country")
        assert repeated_result.session is not None
        self.assertEqual(repeated_result.session.access_code, first_code.code)

        stored_first_code = await self.storage.get_access_code(first_code.code)
        stored_second_code = await self.storage.get_access_code(second_code.code)
        assert stored_first_code is not None
        assert stored_second_code is not None
        self.assertTrue(stored_first_code.is_reserved())
        self.assertFalse(stored_second_code.is_reserved())

    async def test_expired_pending_code_is_released_for_another_user(self) -> None:
        status, access_code = await self.service.create_access_code(
            service_key="claude",
            custom_code="EXPIRECODE",
        )
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        session = await self.service.get_user_session(1)
        assert session is not None
        await self.storage.upsert_user_session(
            replace(
                session,
                updated_at=datetime.now(timezone.utc) - timedelta(seconds=31),
            )
        )

        replacement_result = await self.service.activate_access_code(
            user_id=2,
            chat_id=20,
            username="user2",
            full_name="User 2",
            code=access_code.code,
        )
        self.assertEqual(replacement_result.status, "awaiting_country")
        assert replacement_result.session is not None
        self.assertEqual(replacement_result.session.user_id, 2)

        self.assertIsNone(await self.service.get_user_session(1))
        stored_code = await self.storage.get_access_code(access_code.code)
        assert stored_code is not None
        self.assertEqual(stored_code.reserved_by, self.service.build_requester_id(2))

    async def test_poll_error_cancels_remote_activation(self) -> None:
        status, access_code = await self.service.create_access_code(
            service_key="claude",
            custom_code="BROKENCODE",
        )
        self.assertEqual(status, "created")
        assert access_code is not None

        activation_result = await self.service.activate_access_code(
            user_id=1,
            chat_id=10,
            username="user1",
            full_name="User 1",
            code=access_code.code,
        )
        self.assertEqual(activation_result.status, "awaiting_country")

        self.hero_sms.status_error = RuntimeError("temporary api error")
        bot = FakeBot()
        start_result = await self.service.start_sms_request(
            bot=bot,  # type: ignore[arg-type]
            user_id=1,
            chat_id=10,
            country_key="france",
        )
        self.assertEqual(start_result.status, "started")

        for _ in range(100):
            if bot.messages:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(self.hero_sms.cancelled, ["activation-1"])
        self.assertIsNone(await self.service.get_user_session(1))
        self.assertEqual(bot.messages, [(10, "Не удалось получить SMS для `+33123456789`.")])


class FakeHeroSmsClient:
    def __init__(self) -> None:
        self.buy_error: Exception | None = None
        self.status_error: Exception | None = None
        self.statuses: list[str] = []
        self.wait_forever = False
        self.cancelled: list[str] = []
        self.finished: list[str] = []
        self.buy_calls = 0

    async def buy_number(self, service_code: str, country_name: str) -> HeroSmsPurchase:
        self.buy_calls += 1
        if self.buy_error is not None:
            raise self.buy_error
        return HeroSmsPurchase(
            activation_id=f"activation-{self.buy_calls}",
            phone_number="+33123456789",
            country_id=1,
            country_name=country_name,
        )

    async def get_status(self, activation_id: str) -> str:
        if self.wait_forever:
            await asyncio.Future()
        if self.status_error is not None:
            raise self.status_error
        if self.statuses:
            return self.statuses.pop(0)
        return "STATUS_WAIT_CODE"

    async def finish_activation(self, activation_id: str) -> None:
        self.finished.append(activation_id)

    async def cancel_activation(self, activation_id: str) -> None:
        self.cancelled.append(activation_id)

    async def close(self) -> None:
        return None


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        self.messages.append((chat_id, text))


def service_session(**kwargs):
    from src.storage import UserSession

    return UserSession(**kwargs)


if __name__ == "__main__":
    unittest.main()
