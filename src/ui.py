from typing import Protocol

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import CountryConfig
from src.messages import translate
from src.storage import UserSession


class ServiceUiProtocol(Protocol):
    def get_countries_for_service(self, service_key: str) -> list[CountryConfig]:
        ...

    def get_service_name(self, service_key: str) -> str:
        ...

    def get_cancel_remaining_seconds(self, session: UserSession) -> int:
        ...

    def format_duration(self, total_seconds: int) -> str:
        ...

    def format_request_window(self, locale: str) -> str:
        ...


def country_keyboard(
    locale: str,
    user_id: int,
    service: ServiceUiProtocol,
    service_key: str,
) -> InlineKeyboardMarkup:
    countries = service.get_countries_for_service(service_key)
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []

    for country in countries:
        current_row.append(
            InlineKeyboardButton(
                text=country.label(locale),
                callback_data=f"country:{user_id}:{country.key}",
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=translate(locale, "change_code_button"),
                callback_data=f"change:{user_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard(locale: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=translate(locale, "cancel_button"),
                    callback_data=f"cancel:{user_id}",
                )
            ]
        ]
    )


def render_country_prompt_text(
    locale: str,
    service: ServiceUiProtocol,
    session: UserSession,
) -> str:
    return translate(
        locale,
        "country_prompt",
        code=session.access_code,
        service=service.get_service_name(session.service_key),
        request_window=service.format_request_window(locale),
    )


def render_waiting_text(
    locale: str,
    service: ServiceUiProtocol,
    session: UserSession,
) -> str:
    return render_number_ready_text(locale, service, session)


def render_number_ready_text(
    locale: str,
    service: ServiceUiProtocol,
    session: UserSession,
) -> str:
    return translate(
        locale,
        "number_ready",
        service=service.get_service_name(session.service_key),
        code=session.access_code,
        phone=session.phone_number or "-",
        activation_id=session.activation_id or "-",
        cancel_after=service.format_duration(
            service.get_cancel_remaining_seconds(session)
        ),
    )
