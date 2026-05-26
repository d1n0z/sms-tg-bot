DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")

MESSAGES = {
    "ru": {
        "choose_language": "Выбери язык / Choose your language",
        "language_set": "Язык сохранен: русский.",
        "help_text": (
            "Что умеет бот:\n"
            "- `/start` - начать заново или продолжить текущую заявку\n"
            "- отправить код от продавца - активировать одноразовый доступ\n"
            "- выбрать страну - получить номер и дождаться SMS\n"
            "- `/start en` - переключить язык на английский"
        ),
        "admin_help_text": (
            "Админские команды:\n"
            "- `/addcode <service_key|hero_sms_code> [код]`\n"
            "- `/gencodes <service_key|hero_sms_code> <count>`\n"
            "- `/delcode <код>`\n"
            "- `/codelist [service_key|hero_sms_code]`"
        ),
        "admin_only": "Эта команда доступна только администраторам.",
        "code_prompt": "Отправьте код от продавца.",
        "code_invalid": "Код `{code}` не найден.",
        "code_consumed": "Код `{code}` уже был использован.",
        "code_reserved": "Код `{code}` уже активирован другим пользователем.",
        "service_missing": "Для кода `{code}` не найден сервис в конфиге.",
        "country_prompt": (
            "✅ Код: {code} принят для сервиса \"{service}\".\n\n"
            "➡️ Выбирайте нужную страну кнопками ниже.\n"
            "ℹ️ Номер телефона будет действовать в течение {request_window}."
        ),
        "country_unknown": "Страна `{country}` недоступна.",
        "country_no_numbers": "Для страны `{country}` сейчас нет свободных номеров. Выберите другую.",
        "country_request_failed": "Не удалось запросить номер для страны `{country}`.",
        "number_ready": (
            "➡️ Сервис: {service} / {code}\n"
            "1️⃣ Номер телефона: {phone}\n"
            "2️⃣ ID активации: {activation_id}\n"
            "3️⃣ SMS-код с номера: Ждем.\n\n"
            "❗️ Если номер не подходит, после {cancel_after} можете отменить и выбрать новый номер.."
        ),
        "waiting_hint": "Кнопка отмены станет доступна через {seconds}.",
        "waiting_resume": (
            "➡️ Сервис: {service} / {code}\n"
            "1️⃣ Номер телефона: {phone}\n"
            "2️⃣ ID активации: {activation_id}\n"
            "3️⃣ SMS-код с номера: Ждем."
        ),
        "waiting_already": "Вы уже ждете SMS по текущей заявке.",
        "sms_code_found": "Код для `{phone}`: `{code}`",
        "sms_timeout": "Время ожидания истекло. Выберите страну еще раз.",
        "sms_failed": "Не удалось получить SMS для `{phone}`.",
        "sms_cancelled": "Активация для `{phone}` отменена.",
        "sms_cancelled_remote": "Активация была отменена на стороне HeroSMS.",
        "cancel_button": "Отменить",
        "cancel_locked": "Отмена будет доступна через {remaining}.",
        "cancel_missing": "Сейчас нет активного ожидания SMS.",
        "change_code_button": "Сменить код",
        "change_code_success": "Текущий код сброшен. Отправьте новый код.",
        "button_denied": "Эта кнопка не для вас.",
        "addcode_usage": "Использование: `/addcode <service_key|hero_sms_code> [код]`",
        "addcode_service_missing": "Сервис `{service}` не найден в конфиге.",
        "addcode_duplicate": "Код `{code}` уже существует.",
        "addcode_success": "Создан код `{code}` для сервиса `{service}`.",
        "gencodes_usage": "Использование: `/gencodes <service_key|hero_sms_code> <count>`",
        "gencodes_invalid": "Количество должно быть положительным числом.",
        "gencodes_success": "Создано `{count}` код(ов) для сервиса `{service}`:\n{codes}",
        "delcode_usage": "Использование: `/delcode <код>`",
        "delcode_missing": "Код `{code}` не найден.",
        "delcode_success": "Код `{code}` удален.",
        "codelist_empty": "Список кодов пуст.",
        "codelist_header": "Коды:\n{rows}",
        "state_available": "свободен",
        "state_reserved": "зарезервирован",
        "state_consumed": "использован",
    },
    "en": {
        "choose_language": "Choose your language / Выбери язык",
        "language_set": "Language saved: English.",
        "help_text": (
            "What the bot can do:\n"
            "- `/start` - start over or continue the current request\n"
            "- send a seller code - activate one-time access\n"
            "- choose a country - get a phone number and wait for the SMS\n"
            "- `/start ru` - switch language to Russian"
        ),
        "admin_help_text": (
            "Admin commands:\n"
            "- `/addcode <service_key|hero_sms_code> [code]`\n"
            "- `/gencodes <service_key|hero_sms_code> <count>`\n"
            "- `/delcode <code>`\n"
            "- `/codelist [service_key|hero_sms_code]`"
        ),
        "admin_only": "This command is available to administrators only.",
        "code_prompt": "Send the seller code.",
        "code_invalid": "Code `{code}` was not found.",
        "code_consumed": "Code `{code}` has already been used.",
        "code_reserved": "Code `{code}` is already activated by another user.",
        "service_missing": "No configured service was found for code `{code}`.",
        "country_prompt": (
            "✅ Code: {code} accepted for service \"{service}\".\n\n"
            "➡️ Choose the country you need with the buttons below.\n"
            "ℹ️ The phone number will stay active for {request_window}."
        ),
        "country_unknown": "Country `{country}` is not available.",
        "country_no_numbers": "There are no free numbers for `{country}` right now. Choose another country.",
        "country_request_failed": "Could not request a number for `{country}`.",
        "number_ready": (
            "➡️ Service: {service} / {code}\n"
            "1️⃣ Phone number: {phone}\n"
            "2️⃣ Activation ID: {activation_id}\n"
            "3️⃣ SMS code from the number: Waiting.\n\n"
            "❗️ If the number does not fit, after {cancel_after} you can cancel and choose a new number.."
        ),
        "waiting_hint": "The cancel button will become available in {seconds}.",
        "waiting_resume": (
            "➡️ Service: {service} / {code}\n"
            "1️⃣ Phone number: {phone}\n"
            "2️⃣ Activation ID: {activation_id}\n"
            "3️⃣ SMS code from the number: Waiting."
        ),
        "waiting_already": "You are already waiting for an SMS for the current request.",
        "sms_code_found": "Code for `{phone}`: `{code}`",
        "sms_timeout": "The waiting time has expired. Choose the country again.",
        "sms_failed": "Could not get the SMS for `{phone}`.",
        "sms_cancelled": "Activation for `{phone}` was cancelled.",
        "sms_cancelled_remote": "The activation was cancelled on the HeroSMS side.",
        "cancel_button": "Cancel",
        "cancel_locked": "Cancellation will be available in {remaining}.",
        "cancel_missing": "There is no active SMS wait right now.",
        "change_code_button": "Change code",
        "change_code_success": "The current code has been cleared. Send a new one.",
        "button_denied": "This button is not for you.",
        "addcode_usage": "Usage: `/addcode <service_key|hero_sms_code> [code]`",
        "addcode_service_missing": "Service `{service}` was not found in the config.",
        "addcode_duplicate": "Code `{code}` already exists.",
        "addcode_success": "Created code `{code}` for service `{service}`.",
        "gencodes_usage": "Usage: `/gencodes <service_key|hero_sms_code> <count>`",
        "gencodes_invalid": "Count must be a positive integer.",
        "gencodes_success": "Created `{count}` code(s) for service `{service}`:\n{codes}",
        "delcode_usage": "Usage: `/delcode <code>`",
        "delcode_missing": "Code `{code}` was not found.",
        "delcode_success": "Code `{code}` has been deleted.",
        "codelist_empty": "The code list is empty.",
        "codelist_header": "Codes:\n{rows}",
        "state_available": "available",
        "state_reserved": "reserved",
        "state_consumed": "used",
    },
}


def translate(locale: str, key: str, **kwargs: str) -> str:
    bundle = MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE])
    template = bundle.get(key) or MESSAGES[DEFAULT_LOCALE][key]
    return template.format(**kwargs)
