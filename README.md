`sms-tg-bot` is a Telegram bot that mirrors a HeroSMS-style flow:

- user picks a language
- sends a one-time seller code
- chooses a country from config
- receives a phone number
- waits for the SMS code
- can cancel only after the configured lock period

Run:

```bash
python main.py
```

Required settings in `.env`:

```env
TG_TOKEN=your_telegram_bot_token
HERO_SMS_API_KEY=your_hero_sms_api_key
TG_ADMINS=123456789
```

`TG_ADMINS` should be configured explicitly. If it is empty, admin commands stay unavailable for everyone.

Optional JSON config for services and countries:

```env
SERVICES=[{"key":"claude","name":"Claude","hero_sms_code":"acz","country_keys":["france","poland"]},{"key":"codex","name":"Codex","hero_sms_code":"dr","country_keys":["netherlands"]}]
COUNTRIES=[{"key":"france","name":"France","label_ru":"Франция"},{"key":"poland","name":"Poland","label_ru":"Польша"},{"key":"netherlands","name":"Netherlands","label_ru":"Нидерланды"}]
ACCESS_CODE_RESERVATION_TIMEOUT_SECONDS=900
```

There is no global country fallback. Each service must explicitly list its own `country_keys`, otherwise the bot will show no countries for that service.

Admin commands:

- `/addcode <service_key|hero_sms_code> [code]`
- `/gencodes <service_key|hero_sms_code> <count>`
- `/delcode <code>`
- `/codelist [service_key|hero_sms_code]`

Tests:

```bash
python -m unittest tests.test_service_flow -v
```
