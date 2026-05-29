#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（环境变量与 .env，见 SettingsConfigDict）。"""

    # ---- 通用应用设置 ----
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Eshow Backend"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"
    secret_key: str = "your-secret-key-here"
    api_key: Optional[str] = None
    log_level: Optional[str] = None
    log_dir: str = "logs"
    log_to_console: bool = True

    # ---- 服务及网络设置 ----
    host: str = "0.0.0.0"
    port: int = 8000

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8080"]
    )
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])
    payment_callback_url: str = "https://your-domain.com/api/payments/callback"
    payment_callback_rate_limit_per_minute: int = 120

    # ---- 数据库设置 ----
    database_url: str = "postgresql+asyncpg://eshow:password@localhost:5432/eshow"

    # ---- 第三方/支付相关设置 ----
    ## Telegram Bot
    telegram_bot_token: Optional[str] = None

    ## 支付宝
    alipay_app_id: Optional[str] = None
    alipay_private_key: Optional[str] = None
    alipay_public_key: Optional[str] = None

    ## 微信
    wechat_app_id: Optional[str] = None
    wechat_mch_id: Optional[str] = None
    wechat_private_key: Optional[str] = None
    wechat_serial_no: Optional[str] = None
    wechat_api_v3_key: Optional[str] = None
    wechat_platform_cert_pem: Optional[str] = None

    # ---- USDT (TRC20) 支付设置 ----
    trc20_wallet_address: Optional[str] = None
    trc20_check_interval: int = 15
    trc20_order_timeout_minutes: int = 15
    trc20_pending_scan_batch_size: int = 200
    trc20_pending_scan_max_batches: int = 100

    # ---- Plisio invoice 支付设置（默认充值路径；无公网时靠 worker_poll 轮询）----
    plisio_enabled: bool = False
    plisio_api_key: Optional[str] = None
    plisio_base_url: str = "https://api.plisio.net/api/v1"
    plisio_recharge_currency: str = "USDT_TRX"
    plisio_invoice_expire_minutes: int = 15

    # ---- 支付轮询（Plisio invoice，无公网 callback 时主路径）----
    payment_poll_enabled: bool = False
    payment_poll_interval_sec: int = 30
    payment_poll_batch_size: int = 50

    # ---- 汇率及其他 ----
    exchange_rate_api_key: Optional[str] = None

    # ---- Celery Worker 设置 ----
    celery_broker_url: Optional[str] = None
    celery_result_backend: Optional[str] = None

    # ---- Compute queued task recovery ----
    compute_requeue_enabled: bool = True
    compute_requeue_interval_sec: int = 30
    compute_requeue_batch_size: int = 100
    compute_requeue_min_age_sec: int = 60
    compute_worker_claim_stale_sec: int = 300

    # ---- RunningHub 无 Webhook：轮询终态（Celery Beat + maintenance 队列）----
    poll_enabled: bool = False
    poll_interval_sec: int = 60
    poll_batch_size: int = 30
    poll_max_running_sec: int = 7200
    # 单 tick 内并发 query_task 上限；1=串行。增大缩短尾延迟，易触发 RH 限流/429。
    poll_max_concurrent: int = 1

    # ---- 本地文件存储（临时中转，定期清理）----
    upload_dir: str = "data/uploads"
    upload_retain_days: int = 3
    upload_max_bytes: int = 10 * 1024 * 1024

    # ---- Batch archive processing ----
    batch_result_dir: str = "data/batches"
    batch_archive_max_bytes: int = 100 * 1024 * 1024
    batch_archive_max_items: int = 20
    batch_archive_max_unpacked_bytes: int = 300 * 1024 * 1024
    batch_telegram_document_max_bytes: int = 50 * 1024 * 1024
    batch_packaging_claim_timeout_sec: int = 3600

    # ---- RunningHub ----
    runninghub_api_key: Optional[str] = None
    runninghub_base_url: str = "https://www.runninghub.cn"
    runninghub_webhook_public_base_url: Optional[str] = None

    # 算力「创建运行」提交前并发槽
    slot_redis_url: Optional[str] = None
    slot_max_concurrent_global: int = 32
    slot_max_concurrent_per_user: int = 6
