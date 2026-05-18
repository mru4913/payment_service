# 部署说明（摘录）

## 数据库与迁移

1. 启动 Postgres（与 `docker-compose.yml` 一致）：

   ```bash
   docker compose up -d db
   ```

2. 在 `.env` 中设置 `DATABASE_URL`（本地开发示例见 `.env.example`：`postgresql+asyncpg://…@localhost:<POSTGRES_PORT>/…`）。

3. 执行迁移：

   ```bash
   uv run alembic upgrade head
   ```

`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`、`POSTGRES_PORT` 需与 Compose 及 `DATABASE_URL` 中的账号、库名、端口一致。

## 算力 Worker 与预授权结算

任务创建后会写入 `task_balance_holds`（`active`）并增加 `users.balance_held`。**Worker 在将 `tasks` 更新为终态**（`succeeded` / `failed` / `cancelled`）并写好 `charged_amount`（成功路径）之后，必须调用：

- `backend.workers.settle_task_balance_hold_async(task_id)`（异步会话内），或
- `backend.workers.settle_task_balance_hold(task_id)`（同步封装，便于 Celery）

内部使用 `TaskService.settle_balance_hold_for_terminal_task`：成功则 `capture`，失败/取消则 `release`。已结算或无 active 冻结时幂等空操作。

## Celery Worker（算力队列）

与 `documents/04-BUSINESS-DESIGN.md` **§7** 一致：Broker 使用 **Redis**；任务名为 **`tasks.execute_compute`**，队列 **`compute`**，消息参数为 **`task_id`（字符串）**。

1. 在 `.env` 中设置 `CELERY_BROKER_URL`（示例见 `.env.example`）。未设置时，API 创建任务后**不会**向队列投递，仅打告警日志。
2. 启动 Redis 与 Worker。使用 Compose 时：

   ```bash
   docker compose up -d db redis app worker
   ```

   `app` / `worker` 服务已注入 `CELERY_BROKER_URL=redis://redis:6379/0`。

3. 本地单独启动 Worker（需已迁移 DB、Redis 可连）：

   ```bash
   uv run celery -A backend.workers.celery_app:celery_app worker -l info -Q compute
   ```

**`compute_runner` 分流（与代码一致）**：

- **`third_party_platform == runninghub`**：走 **`run_runninghub_pipeline`**（`backend/workers/rh_pipeline.py`）：上传媒体、`create_comfy_task`、写 **`upstream_task_id`** 与 **`running`**。**终态与结算（当前默认）**：
  - **轮询主路径（默认）**：`.env` 中 **`POLL_ENABLED=true`**，并起 **`celery_beat`** + 消费 **`maintenance`** 队列的 **`worker_poll`**（见 `docker-compose.yml`）。Beat 调度 **`poll_schedule`** → **`tasks.poll_terminal`**，扫 **`running`** 且已有 **`upstream_task_id`** 的任务，调 RH **`query_task`**；超过 **`POLL_MAX_RUNNING_SEC`**（默认 7200 秒）仍无终态则标 **`failed`**（`poll_running_timeout`）并释槽/解冻。仍需 **`RUNNINGHUB_API_KEY`**；**`CELERY_BROKER_URL` 须显式设置** 才会注册 `poll_schedule`（详见下「轮询与 Celery Beat」）。
  - **Webhook（可选）**：配置 **`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`** 后，`create` 请求会带 **`webhookUrl`**，RH 回调 **`POST /api/webhooks/runninghub/{task_id}`**，回调内可选 **`query_task`**，再 **`settle_task_balance_hold_async`** / **`settle_task_balance_hold`**。与轮询共用 **CAS 幂等**，可同时启用以降低对 **`query_task`** 的依赖。
- **其它平台**：仍为 **stub** 路径（`promote_task_to_terminal_and_settle`），便于无上游密钥时联调终态与预授权结算。

### 轮询与 Celery Beat（必读）

1. **`CELERY_BROKER_URL` 须显式配置**：`backend/workers/celery_app.py` 仅在 **`poll_enabled` 且 `celery_broker_url` 非空** 时注册 **`poll_schedule`**。仅设 `POLL_ENABLED=true` 而 broker 留空时，Worker 进程仍可能用内置默认 Redis URL 连 broker，但 **Beat 不会排 `tasks.poll_terminal`**，表现为轮询不跑。启动时会对 **`POLL_ENABLED=true` 且 broker 未设置** 打 **warning**（`celery_app` 与每次 `run_poll_terminal_batch` tick）。
2. **只跑一个 `celery_beat` 实例**：多 Beat 会重复投递同一 `poll_schedule`，导致对 RunningHub 的 **`query_task` 重复调用**（终态仍由 DB CAS 幂等，但浪费配额、易触发限流）。需要高可用时再考虑分布式锁或 `SKIP LOCKED` 等增强。
3. **`POLL_INTERVAL_SEC` / `POLL_BATCH_SIZE` / `POLL_MAX_CONCURRENT`**：单次 tick 内对每条任务至少一次 RH 请求（超时 discard 前可能多一次 `query` 摘要）。建议使 **`POLL_INTERVAL_SEC` ≥ 单次最坏耗时** 的量级，其中最坏耗时大致随 `ceil(batch_size / max_concurrent) × 单次 query 延迟` 增长。`POLL_MAX_CONCURRENT` 默认 **1**（串行）；增大可缩短尾延迟，但更容易触发 RH **429 / 限流**，需与间隔、批量一起调参。
4. **每次 tick 的结构化日志**：`poll_terminal: tick` 一行包含 `batch`、`elapsed_ms`、`concurrent`、`terminal_cas_hit` / `terminal_cas_miss`、`query_failures`、`still_in_progress`，便于对齐限流与 interval。
5. **`query_task` 连续失败**：当前实现为打 **`poll_terminal: query_task`** / **`query_snapshot`** 的 **warning** 日志，本 tick 不推进该任务；可对日志做采集告警。长期若在 DB 记连续失败次数再自动 failed，属后续增强。
6. **结算与释槽**：终态 **CAS 成功** 后调用 **`settle_task_balance_hold_async`** 与 **`release_slot`**（轮询与 Webhook 路径一致）。若 **settle 抛错**，仍会 **释槽**（避免用户永久占坑），并打 **`poll_terminal: settle failed`** 与 **`settle failed but releasing slot anyway`**；对账依赖 settle 幂等与运维跟进。若需改为「settle 成功才释槽」，须单独评估槽位饿死风险后再改代码。

Compose 全栈若启用轮询：`docker compose up -d db redis app worker worker_poll celery_beat`，并确保 **`.env` 中 `CELERY_BROKER_URL` 非空**（与 Compose 注入一致），按需配置 **`POLL_*`**。

联调占位：也可直接调用 `promote_task_to_terminal_and_settle`（`backend.workers.compute_runner`），仅用于开发/测试。

## Compose 全栈联调提示

- 若宿主机 **6379** 已被占用，在 `.env` 中设置 **`REDIS_PORT=6380`**（或任意空闲端口）；容器内仍通过服务名 **`redis:6379`** 互连，不受影响。
- **`app` / `worker`** 会通过 Compose 的 `environment` 注入 **`CELERY_BROKER_URL`** 与 **`DATABASE_URL`**，与 `.env` 里面向宿主机的 `DATABASE_URL` 可以不一致。
- 镜像内需包含项目根目录的 **`common/`**（日志等）；`Dockerfile` 已 `COPY common/`。运行用户需对项目目录可写以便 `uv` 缓存（镜像内已为 `appuser` 配置家目录与 `/app` 属主）。
