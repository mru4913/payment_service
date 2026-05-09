#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（环境变量与 .env，见 SettingsConfigDict）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TG Payment Bot Backend"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"

    database_url: str = (
        "postgresql+asyncpg://user:password@localhost:5432/tg_payment_bot"
    )

    telegram_bot_token: Optional[str] = None

    alipay_app_id: Optional[str] = None
    alipay_private_key: Optional[str] = None
    alipay_public_key: Optional[str] = None

    wechat_app_id: Optional[str] = None
    wechat_mch_id: Optional[str] = None
    wechat_private_key: Optional[str] = None
    wechat_serial_no: Optional[str] = None
    wechat_api_v3_key: Optional[str] = None
    wechat_platform_cert_pem: Optional[str] = None

    trc20_wallet_address: Optional[str] = None
    trc20_check_interval: int = 15
    trc20_order_timeout_minutes: int = 15
    trc20_pending_scan_batch_size: int = 200
    trc20_pending_scan_max_batches: int = 100

    secret_key: str = "your-secret-key-here"
    api_key: Optional[str] = None

    payment_callback_url: str = "https://your-domain.com/api/payments/callback"

    exchange_rate_api_key: Optional[str] = None

    host: str = "0.0.0.0"
    port: int = 8000

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8080"]
    )

    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])

    payment_callback_rate_limit_per_minute: int = 120
