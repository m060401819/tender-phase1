from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEVELOPMENT_DATABASE_URL: ClassVar[str] = "postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1"
    PRODUCTION_REQUIRED_FIELDS: ClassVar[dict[str, str]] = {
        "app_env": "APP_ENV",
        "database_url": "DATABASE_URL",
        "admin_auth_secret": "ADMIN_AUTH_SECRET",
        "log_level": "LOG_LEVEL",
    }
    LOG_LEVEL_ALIASES: ClassVar[dict[str, str]] = {
        "WARN": "WARNING",
        "FATAL": "CRITICAL",
    }
    LOG_LEVEL_VALUES: ClassVar[dict[str, int]] = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    app_name: str = "招标信息聚合平台一期"
    app_env: str = "dev"
    database_url: str = DEVELOPMENT_DATABASE_URL
    admin_auth_secret: str = ""
    log_level: str = "INFO"
    auth_basic_users_json: str = ""
    auth_basic_realm: str = "Tender Phase1 Admin"
    source_scheduler_embedded_enabled: bool = False
    source_scheduler_refresh_interval_seconds: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "dev"
        if text == "production":
            return "prod"
        if text == "development":
            return "dev"
        return text

    @field_validator(
        "database_url",
        "admin_auth_secret",
        "auth_basic_users_json",
        "auth_basic_realm",
        mode="before",
    )
    @classmethod
    def _normalize_string_value(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> str:
        normalized = cls.LOG_LEVEL_ALIASES.get(str(value or "").strip().upper(), str(value or "").strip().upper())
        if not normalized:
            normalized = "INFO"
        if normalized not in cls.LOG_LEVEL_VALUES:
            allowed = ", ".join(cls.LOG_LEVEL_VALUES)
            raise ValueError(f"LOG_LEVEL must be one of: {allowed}")
        return normalized

    @model_validator(mode="after")
    def _validate_production_runtime_requirements(self) -> Settings:
        if not self.is_production:
            return self

        missing_vars = [
            env_name
            for field_name, env_name in self.PRODUCTION_REQUIRED_FIELDS.items()
            if field_name not in self.model_fields_set or not str(getattr(self, field_name)).strip()
        ]
        if missing_vars:
            required = ", ".join(missing_vars)
            raise ValueError(f"生产环境必须显式配置以下变量: {required}")

        if self.database_url == self.DEVELOPMENT_DATABASE_URL:
            raise ValueError("生产环境禁止使用默认开发 DATABASE_URL，请显式配置生产数据库连接")

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"

    @property
    def log_level_value(self) -> int:
        return self.LOG_LEVEL_VALUES[self.log_level]


settings = Settings()
