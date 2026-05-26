from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.messages import SUPPORTED_LOCALES, translate
from src.service import BotService
from src.storage import AccessCode, normalize_access_code
from src.ui import (
    cancel_keyboard,
    country_keyboard,
    render_country_prompt_text,
    render_number_ready_text,
    render_waiting_text,
)


def build_router(service: BotService) -> Router:
    router = Router()

    async def send_start_flow(message: Message, *, user_id: int, locale: str) -> None:
        session = await service.get_user_session(user_id, bot=message.bot)
        if session is None:
            await message.answer(translate(locale, "code_prompt"))
            return

        if session.is_waiting_sms():
            if message.bot is not None:
                await service.ensure_sms_request_task(message.bot, user_id)
            sent_message = await message.answer(
                render_waiting_text(locale, service, session),
                reply_markup=cancel_keyboard(locale, user_id),
            )
            await service.bind_status_message(session, sent_message.message_id)
            return

        await message.answer(
            render_country_prompt_text(locale, service, session),
            reply_markup=country_keyboard(
                locale,
                user_id,
                service,
                session.service_key,
            ),
        )

    @router.message(CommandStart())
    async def start_handler(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        requested_locale = (command.args or "").strip().lower()
        has_saved_locale = await service.has_locale(message.from_user.id)
        if requested_locale in SUPPORTED_LOCALES:
            await service.set_locale(message.from_user.id, requested_locale)
            has_saved_locale = True

        locale = await service.get_locale(message.from_user.id)
        if requested_locale in SUPPORTED_LOCALES:
            await message.answer(translate(locale, "language_set"))
        elif not has_saved_locale:
            await message.answer(
                translate(locale, "choose_language"),
                reply_markup=language_keyboard(),
            )
            return

        await send_start_flow(message, user_id=message.from_user.id, locale=locale)

    @router.callback_query(F.data.startswith("lang:"))
    async def language_callback_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            await callback.answer()
            return

        locale = callback.data.split(":", 1)[1]
        if locale not in SUPPORTED_LOCALES:
            await callback.answer()
            return

        await service.set_locale(callback.from_user.id, locale)
        if callback.message is not None:
            with suppress(Exception):
                await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[arg-type]
            await callback.message.answer(translate(locale, "language_set"))
            await send_start_flow(
                callback.message,  # type: ignore[arg-type]
                user_id=callback.from_user.id,
                locale=locale,
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("country:"))
    async def country_callback_handler(callback: CallbackQuery) -> None:
        if (
            callback.from_user is None
            or callback.data is None
            or callback.message is None
            or callback.bot is None
        ):
            await callback.answer()
            return

        locale = await service.get_locale(callback.from_user.id)
        _, owner_id_raw, country_key = callback.data.split(":", 2)
        if not owner_id_raw.isdigit() or int(owner_id_raw) != callback.from_user.id:
            await callback.answer(translate(locale, "button_denied"), show_alert=True)
            return

        result = await service.start_sms_request(
            bot=callback.bot,
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            country_key=country_key,
        )

        country = service.settings.get_country(country_key)
        country_name = country.label(locale) if country is not None else country_key

        if result.status == "missing":
            await callback.message.answer(translate(locale, "code_prompt"))
            await callback.answer()
            return
        if result.status == "running":
            await callback.answer(translate(locale, "waiting_already"), show_alert=True)
            return
        if result.status == "service_missing":
            code = result.session.access_code if result.session is not None else "-"
            await callback.message.answer(
                translate(locale, "service_missing", code=code)
            )
            await callback.answer()
            return
        if result.status == "unknown_country":
            await callback.answer(
                translate(locale, "country_unknown", country=country_name),
                show_alert=True,
            )
            return
        if result.status == "no_numbers":
            await callback.message.answer(
                translate(locale, "country_no_numbers", country=country_name),
                reply_markup=country_keyboard(
                    locale,
                    callback.from_user.id,
                    service,
                    result.session.service_key if result.session is not None else "default",
                ),
            )
            await callback.answer()
            return
        if result.status == "provider_error" or result.session is None:
            await callback.message.answer(
                translate(locale, "country_request_failed", country=country_name)
            )
            await callback.answer()
            return

        updated_session = await service.bind_status_message(
            result.session,
            callback.message.message_id,
        )
        waiting_text = render_number_ready_text(locale, service, updated_session)
        edited = False
        with suppress(Exception):
            await callback.message.edit_text(  # type: ignore
                waiting_text,
                reply_markup=cancel_keyboard(locale, callback.from_user.id),
            )
            edited = True
        if not edited:
            sent_message = await callback.message.answer(
                waiting_text,
                reply_markup=cancel_keyboard(locale, callback.from_user.id),
            )
            await service.bind_status_message(updated_session, sent_message.message_id)
        await callback.answer()

    @router.callback_query(F.data.startswith("cancel:"))
    async def cancel_callback_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            await callback.answer()
            return

        locale = await service.get_locale(callback.from_user.id)
        _, owner_id_raw = callback.data.split(":", 1)
        if not owner_id_raw.isdigit() or int(owner_id_raw) != callback.from_user.id:
            await callback.answer(translate(locale, "button_denied"), show_alert=True)
            return

        result = await service.cancel_sms_request(callback.from_user.id, bot=callback.bot)
        if result.status == "missing":
            await callback.answer(translate(locale, "cancel_missing"), show_alert=True)
            return
        if result.status == "locked":
            await callback.answer(
                translate(
                    locale,
                    "cancel_locked",
                    remaining=service.format_duration(result.remaining_seconds or 0),
                ),
                show_alert=True,
            )
            return

        await callback.answer()

    @router.callback_query(F.data.startswith("change:"))
    async def change_code_callback_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.data is None:
            await callback.answer()
            return

        locale = await service.get_locale(callback.from_user.id)
        _, owner_id_raw = callback.data.split(":", 1)
        if not owner_id_raw.isdigit() or int(owner_id_raw) != callback.from_user.id:
            await callback.answer(translate(locale, "button_denied"), show_alert=True)
            return

        result = await service.reset_pending_code(callback.from_user.id, bot=callback.bot)
        if result.status == "missing":
            await callback.answer(translate(locale, "code_prompt"), show_alert=True)
            return
        if result.status == "waiting_sms":
            await callback.answer(translate(locale, "waiting_already"), show_alert=True)
            return

        if callback.message is not None:
            with suppress(Exception):
                await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[arg-type]
            await callback.message.answer(translate(locale, "change_code_success"))
            await callback.message.answer(translate(locale, "code_prompt"))
        await callback.answer()

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        if message.from_user is None:
            return

        locale = await service.get_locale(message.from_user.id)
        text = translate(locale, "help_text")
        if service.is_admin(message.from_user.id):
            text = f"{text}\n\n{translate(locale, 'admin_help_text')}"
        await message.answer(text)

    @router.message(Command("addcode"))
    async def addcode_handler(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        locale = await service.get_locale(message.from_user.id)
        if not service.is_admin(message.from_user.id):
            await message.answer(translate(locale, "admin_only"))
            return

        args = (command.args or "").split(maxsplit=1)
        if len(args) not in {1, 2}:
            await message.answer(translate(locale, "addcode_usage"))
            return

        service_key = args[0]
        custom_code = args[1] if len(args) == 2 else None
        status, access_code = await service.create_access_code(
            service_key=service_key,
            custom_code=custom_code,
        )
        if status == "service_missing":
            await message.answer(
                translate(locale, "addcode_service_missing", service=service_key)
            )
            return
        if status == "duplicate":
            duplicate_code = normalize_access_code(custom_code or "")
            await message.answer(
                translate(locale, "addcode_duplicate", code=duplicate_code)
            )
            return
        if access_code is None:
            await message.answer(translate(locale, "addcode_usage"))
            return

        await message.answer(
            translate(
                locale,
                "addcode_success",
                code=access_code.code,
                service=service.get_service_name(access_code.service_key),
            )
        )

    @router.message(Command("gencodes"))
    async def gencodes_handler(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        locale = await service.get_locale(message.from_user.id)
        if not service.is_admin(message.from_user.id):
            await message.answer(translate(locale, "admin_only"))
            return

        args = (command.args or "").split()
        if len(args) != 2:
            await message.answer(translate(locale, "gencodes_usage"))
            return

        service_key, count_raw = args
        try:
            count = int(count_raw)
        except ValueError:
            await message.answer(translate(locale, "gencodes_invalid"))
            return

        status, access_codes = await service.create_access_codes(
            service_key=service_key,
            count=count,
        )
        if status == "service_missing":
            await message.answer(
                translate(locale, "addcode_service_missing", service=service_key)
            )
            return
        if status == "invalid_count" or not access_codes:
            await message.answer(translate(locale, "gencodes_invalid"))
            return

        text = translate(
            locale,
            "gencodes_success",
            count=str(len(access_codes)),
            service=service.get_service_name(access_codes[0].service_key),
            codes="\n".join(f"`{item.code}`" for item in access_codes),
        )
        await send_chunks(message, service, text)

    @router.message(Command("delcode"))
    async def delcode_handler(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        locale = await service.get_locale(message.from_user.id)
        if not service.is_admin(message.from_user.id):
            await message.answer(translate(locale, "admin_only"))
            return

        raw_code = (command.args or "").strip()
        if not raw_code:
            await message.answer(translate(locale, "delcode_usage"))
            return

        code = normalize_access_code(raw_code)
        deleted = await service.delete_access_code(code)
        if not deleted:
            await message.answer(translate(locale, "delcode_missing", code=code))
            return

        await message.answer(translate(locale, "delcode_success", code=code))

    @router.message(Command("codelist"))
    async def codelist_handler(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        locale = await service.get_locale(message.from_user.id)
        if not service.is_admin(message.from_user.id):
            await message.answer(translate(locale, "admin_only"))
            return

        service_key = (command.args or "").strip() or None
        if service_key and service.settings.resolve_service_ref(service_key) is None:
            await message.answer(
                translate(locale, "addcode_service_missing", service=service_key)
            )
            return

        access_codes = await service.list_access_codes(service_key)
        if not access_codes:
            await message.answer(translate(locale, "codelist_empty"))
            return

        rows = [render_access_code_row(locale, service, item) for item in access_codes]
        await send_chunks(
            message,
            service,
            translate(locale, "codelist_header", rows="\n".join(rows)),
        )

    @router.message(F.text)
    async def text_handler(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        if message.text.startswith("/"):
            return

        if not await service.has_locale(message.from_user.id):
            locale = await service.get_locale(message.from_user.id)
            await message.answer(
                translate(locale, "choose_language"),
                reply_markup=language_keyboard(),
            )
            return

        locale = await service.get_locale(message.from_user.id)
        result = await service.activate_access_code(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            code=message.text,
        )

        if result.status == "missing":
            await message.answer(
                translate(
                    locale,
                    "code_invalid",
                    code=normalize_access_code(message.text),
                )
            )
            return
        if result.status == "consumed":
            code = result.access_code.code if result.access_code is not None else normalize_access_code(message.text)
            await message.answer(translate(locale, "code_consumed", code=code))
            return
        if result.status == "reserved":
            code = result.access_code.code if result.access_code is not None else normalize_access_code(message.text)
            await message.answer(translate(locale, "code_reserved", code=code))
            return
        if result.status == "service_missing":
            code = result.access_code.code if result.access_code is not None else normalize_access_code(message.text)
            await message.answer(translate(locale, "service_missing", code=code))
            return
        if result.status == "waiting_sms" and result.session is not None:
            if message.bot is not None:
                await service.ensure_sms_request_task(message.bot, message.from_user.id)
            sent_message = await message.answer(
                render_waiting_text(locale, service, result.session),
                reply_markup=cancel_keyboard(locale, message.from_user.id),
            )
            await service.bind_status_message(result.session, sent_message.message_id)
            return
        if result.session is None:
            await message.answer(translate(locale, "code_prompt"))
            return

        await message.answer(
            render_country_prompt_text(locale, service, result.session),
            reply_markup=country_keyboard(
                locale,
                message.from_user.id,
                service,
                result.session.service_key,
            ),
        )

    return router


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="English", callback_data="lang:en"),
            ]
        ]
    )
def render_access_code_row(locale: str, service: BotService, access_code: AccessCode) -> str:
    state_label = service.describe_access_code_state(locale, access_code)
    prefix = {
        "available": "+",
        "reserved": "~",
        "consumed": "-",
    }[access_code.state()]
    return f"{prefix} {access_code.code} {access_code.service_key} {state_label}"


async def send_chunks(message: Message, service: BotService, text: str) -> None:
    for chunk in service.split_message(text):
        await message.answer(chunk)
