import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp


class HeroSmsError(RuntimeError):
    pass


class HeroSmsNoNumbersError(HeroSmsError):
    pass


@dataclass(slots=True, frozen=True)
class HeroSmsPurchase:
    activation_id: str
    phone_number: str
    country_id: int
    country_name: str


class HeroSmsClientProtocol(Protocol):
    async def buy_number(self, service_code: str, country_name: str) -> HeroSmsPurchase: ...

    async def get_status(self, activation_id: str) -> str: ...

    async def finish_activation(self, activation_id: str) -> None: ...

    async def cancel_activation(self, activation_id: str) -> None: ...

    async def close(self) -> None: ...


class HeroSmsClient:
    def __init__(self, *, api_key: str | None, base_url: str) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.strip()
        self._session: aiohttp.ClientSession | None = None
        self._country_cache: dict[str, int] = {}

    async def buy_number(self, service_code: str, country_name: str) -> HeroSmsPurchase:
        country_id = await self._get_country_id(country_name)
        result = await self._call_api_json(
            "getNumberV2",
            service=service_code.strip(),
            country=country_id,
        )

        if isinstance(result, dict) and "activationId" in result and "phoneNumber" in result:
            return HeroSmsPurchase(
                activation_id=str(result["activationId"]).strip(),
                phone_number=str(result["phoneNumber"]).strip(),
                country_id=country_id,
                country_name=country_name.strip(),
            )

        if isinstance(result, str) and "NO_NUMBERS" in result.upper():
            raise HeroSmsNoNumbersError(result)

        raise HeroSmsError(f"unexpected HeroSMS buy_number response: {result}")

    async def get_status(self, activation_id: str) -> str:
        return await self._call_api("getStatus", id=str(activation_id).strip())

    async def finish_activation(self, activation_id: str) -> None:
        await self._call_api("setStatus", id=str(activation_id).strip(), status=6)

    async def cancel_activation(self, activation_id: str) -> None:
        await self._call_api("setStatus", id=str(activation_id).strip(), status=8)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _call_api(self, action: str, **params: Any) -> str:
        if not self.api_key:
            raise HeroSmsError("hero_sms_api_key is not configured")
        if not self.base_url:
            raise HeroSmsError("hero_sms_base_url is not configured")

        payload = {"action": action, "api_key": self.api_key, **params}
        session = await self._get_session()
        try:
            async with session.get(
                self.base_url,
                params=payload,
                timeout=aiohttp.ClientTimeout(30),
            ) as response:
                response.raise_for_status()
                return (await response.text()).strip()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise HeroSmsError(f"HeroSMS request failed for action '{action}'") from exc

    async def _call_api_json(self, action: str, **params: Any) -> Any:
        text = await self._call_api(action, **params)
        if text.startswith(("{", "[")):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return text

    async def _get_country_id(self, country_name: str) -> int:
        cache_key = country_name.strip().lower()
        cached = self._country_cache.get(cache_key)
        if cached is not None:
            return cached

        countries = await self._call_api_json("getCountries")
        if not isinstance(countries, dict):
            raise HeroSmsError(f"unexpected HeroSMS countries response: {countries}")

        for raw_country in countries.values():
            if not isinstance(raw_country, dict):
                continue
            if str(raw_country.get("eng", "")).strip().lower() != cache_key:
                continue
            country_id = int(raw_country["id"])
            self._country_cache[cache_key] = country_id
            return country_id

        raise HeroSmsError(f"country '{country_name}' was not found in HeroSMS")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
