import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceConfig(BaseModel):
    key: str
    name: str
    hero_sms_code: str
    country_keys: list[str] | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("service key cannot be empty")
        return normalized

    @field_validator("name", "hero_sms_code")
    @classmethod
    def ensure_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("service fields cannot be empty")
        return normalized

    @field_validator("country_keys", mode="before")
    @classmethod
    def normalize_country_keys(cls, value: Any) -> list[str] | None:
        if value in (None, "", []):
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.startswith("["):
                value = json.loads(stripped)
            else:
                value = [item.strip() for item in stripped.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        raise TypeError("country_keys must be a list of strings")


class CountryConfig(BaseModel):
    key: str
    name: str
    label_ru: str | None = None
    label_en: str | None = None
    hero_sms_name: str | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("country key cannot be empty")
        return normalized

    @field_validator("name")
    @classmethod
    def ensure_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("country name cannot be empty")
        return normalized

    def label(self, locale: str) -> str:
        if locale == "ru" and self.label_ru:
            return self.label_ru
        if locale == "en" and self.label_en:
            return self.label_en
        return self.name

    @property
    def provider_name(self) -> str:
        return (self.hero_sms_name or self.name).strip()


def _default_services() -> list[ServiceConfig]:
    return [
        ServiceConfig(
            key="claude",
            name="Claude",
            hero_sms_code="acz",
            country_keys=[
                "israel",
                "netherlands",
                "brazil",
                "cameroon",
                "united-kingdom",
                "france",
                "sweden",
                "poland",
            ],
        ),
        ServiceConfig(
            key="codex",
            name="Codex",
            hero_sms_code="dr",
            country_keys=[
                "portugal",
                "cameroon",
                "malaysia",
            ],
        ),
        ServiceConfig(
            key="perplexity",
            name="Perplexity",
            hero_sms_code="dr",
            country_keys=[
                "united-kingdom",
                "romania",
                "sweden",
            ],
        ),
    ]


def _default_countries() -> list[CountryConfig]:
    return [
        CountryConfig(key="israel", name="Israel", label_ru="Израиль"),
        CountryConfig(key="netherlands", name="Netherlands", label_ru="Нидерланды"),
        CountryConfig(key="brazil", name="Brazil", label_ru="Бразилия"),
        CountryConfig(key="cameroon", name="Cameroon", label_ru="Камерун"),
        CountryConfig(
            key="united-kingdom",
            name="United Kingdom",
            label_ru="Великобритания",
        ),
        CountryConfig(key="france", name="France", label_ru="Франция"),
        CountryConfig(key="sweden", name="Sweden", label_ru="Швеция"),
        CountryConfig(key="poland", name="Poland", label_ru="Польша"),
        CountryConfig(key="portugal", name="Portugal", label_ru="Португалия"),
        CountryConfig(key="malaysia", name="Malaysia", label_ru="Малайзия"),
        CountryConfig(key="romania", name="Romania", label_ru="Румыния"),
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="allow",
    )

    tg_token: str | None = None
    tg_admins: list[int] = []
    hero_sms_api_key: str | None = None
    hero_sms_base_url: str = "https://hero-sms.com/stubs/handler_api.php"
    access_code_store_path: Path = Path("codes.json")
    user_session_store_path: Path = Path("user_sessions.json")
    user_locale_store_path: Path = Path("user_locales.json")
    hero_sms_poll_interval_seconds: float = 5.0
    hero_sms_cancel_unlock_seconds: int = 120
    hero_sms_request_timeout_seconds: int = 1200
    access_code_reservation_timeout_seconds: int = 900
    services: list[ServiceConfig] = Field(default_factory=_default_services)
    countries: list[CountryConfig] = Field(default_factory=_default_countries)

    @field_validator("tg_admins", mode="before")
    @classmethod
    def parse_admins(cls, value: Any) -> list[int]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return [int(item) for item in json.loads(stripped)]
            return [int(item.strip()) for item in stripped.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [int(item) for item in value]
        raise TypeError(
            "tg_admins must be a list of integers or a comma-separated string"
        )

    @field_validator("services", mode="before")
    @classmethod
    def parse_services(cls, value: Any) -> list[ServiceConfig] | Any:
        if value in (None, "", []):
            return _default_services()
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return _default_services()
            value = json.loads(stripped)
        return value

    @field_validator("countries", mode="before")
    @classmethod
    def parse_countries(cls, value: Any) -> list[CountryConfig] | Any:
        if value in (None, "", []):
            return _default_countries()
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return _default_countries()
            value = json.loads(stripped)
        return value

    @model_validator(mode="after")
    def validate_catalogs(self) -> "Settings":
        if not self.services:
            raise ValueError("at least one service must be configured")
        seen_service_keys: set[str] = set()
        for service in self.services:
            if service.key in seen_service_keys:
                raise ValueError(f"duplicate service key: {service.key}")
            seen_service_keys.add(service.key)

        seen_country_keys: set[str] = set()
        for country in self.countries:
            if country.key in seen_country_keys:
                raise ValueError(f"duplicate country key: {country.key}")
            seen_country_keys.add(country.key)

        for service in self.services:
            if not service.country_keys:
                continue
            unknown = [
                key for key in service.country_keys if key not in seen_country_keys
            ]
            if unknown:
                raise ValueError(
                    f"service '{service.key}' references unknown countries: {', '.join(unknown)}"
                )
        return self

    def get_service(self, service_key: str) -> ServiceConfig | None:
        normalized = service_key.strip().lower()
        for service in self.services:
            if service.key == normalized:
                return service
        return None

    def resolve_service_ref(self, service_ref: str) -> ServiceConfig | None:
        normalized = service_ref.strip().lower()
        if not normalized:
            return None

        service = self.get_service(normalized)
        if service is not None:
            return service

        provider_matches = [
            service
            for service in self.services
            if service.hero_sms_code.strip().lower() == normalized
        ]
        if len(provider_matches) == 1:
            return provider_matches[0]
        return None

    def get_country(self, country_key: str) -> CountryConfig | None:
        normalized = country_key.strip().lower()
        for country in self.countries:
            if country.key == normalized:
                return country
        return None

    def get_countries_for_service(self, service_key: str) -> list[CountryConfig]:
        service = self.get_service(service_key)
        if service is None or not service.country_keys:
            return list(self.countries)

        allowed_keys = set(service.country_keys)
        return [country for country in self.countries if country.key in allowed_keys]


settings = Settings()  # type: ignore[call-arg]


__all__ = [
    "CountryConfig",
    "ServiceConfig",
    "Settings",
    "settings",
]
