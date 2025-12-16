#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本信息
    app_name: str = "TG Payment Bot Backend"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, env="DEBUG")
    environment: str = Field(default="development", env="ENVIRONMENT")

    # 数据库配置
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/tg_payment_bot",
        env="DATABASE_URL"
    )

    # Telegram Bot配置
    telegram_bot_token: Optional[str] = Field(None, env="TELEGRAM_BOT_TOKEN")

    # 支付宝配置
    alipay_app_id: Optional[str] = Field(None, env="ALIPAY_APP_ID")
    alipay_private_key: Optional[str] = Field(None, env="ALIPAY_PRIVATE_KEY")
    alipay_public_key: Optional[str] = Field(None, env="ALIPAY_PUBLIC_KEY")

    # 微信支付配置
    wechat_app_id: Optional[str] = Field(None, env="WECHAT_APP_ID")
    wechat_mch_id: Optional[str] = Field(None, env="WECHAT_MCH_ID")
    wechat_private_key: Optional[str] = Field(None, env="WECHAT_PRIVATE_KEY")
    wechat_serial_no: Optional[str] = Field(None, env="WECHAT_SERIAL_NO")

    # 安全配置
    secret_key: str = Field(default="your-secret-key-here", env="SECRET_KEY")
    jwt_secret_key: str = Field(default="your-jwt-secret-key", env="JWT_SECRET_KEY")
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # 支付回调配置
    payment_callback_url: str = Field(
        default="https://your-domain.com/api/payments/callback",
        env="PAYMENT_CALLBACK_URL"
    )

    # 汇率API配置 (如果需要的话)
    exchange_rate_api_key: Optional[str] = Field(None, env="EXCHANGE_RATE_API_KEY")

    # 服务器配置
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")

    # CORS配置
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="CORS_ORIGINS"
    )

    # 信任主机配置
    allowed_hosts: list[str] = Field(
        default=["*"],
        env="ALLOWED_HOSTS"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


