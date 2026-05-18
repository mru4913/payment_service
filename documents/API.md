# HTTP API 说明（Eshow / 易修）

基路径与挂载方式以运行中的 FastAPI 应用为准（常见为根路径下 `/users`、`/payments`、`/tasks` 等）。受保护路由需请求头携带 API Key（若配置了 `API_KEY`）：`X-API-Key: <your-key>`；未配置时开发环境可能不校验。

## 破坏性变更提示：用户余额字段

- **`GET /users/{telegram_id}`** 与 **`GET /users/{telegram_id}/balance`** 现返回：
  - **`balance`**：总余额（美元计价）。
  - **`balance_held`**：预授权冻结合计（与 `balance` 同币种，列名无 `_usd` 后缀）。
  - **`balance_available`**：可用余额，等于 `balance - balance_held`（不单独持久化）。
- 原先仅返回单一字段 **`balance_usd`** 的 **`GET .../balance`** 响应已替换为上述结构；客户端需按新字段解析。

## `PUT /users/{telegram_id}/balance`

管理员或内部调账用途。

**查询参数（与实现一致）**：`amount`（`Decimal`）、`transaction_type`（字符串，建议与 `balance_transactions.transaction_type` 一致，如 `deposit` / `withdraw` / `payment` / `refund` 等）、可选 **`payment_id`**（字符串形式的 **UUID**；若传入非空且非法则 **422**）、可选 `description`。

若扣减后 **`balance < balance_held`**，返回 **409**，body 形如：

```json
{"detail": {"message": "扣减后总余额不能低于已冻结金额", "code": "balance_below_held"}}
```

用户不存在时仍为 **404**（`"用户不存在"`）。

## `GET /users/{telegram_id}/transactions`

分页查询该用户余额流水。每条记录除金额与 `transaction_type` 外，包含：

- **`payment_id`**：关联支付时存在（UUID 字符串）。
- **`task_id`**：算力任务相关流水（`hold` / `hold_release` / `consumption` 等）时存在（UUID 字符串）。

响应 **`total`**：该用户流水**总条数**（与 `skip`/`limit` 分页无关）。本页条数即 `transactions` 数组长度。

## 列表响应：`total` 与 `returned`（支付与全局余额列表）

以下接口在分页语义上对齐：**`total`** = 满足当前筛选条件的记录**总条数**；**`returned`** = 本响应中列表数组长度（≤ `limit`）。仅含用户维度的流水接口仍只返回 **`total`**（见上一节 `GET /users/.../transactions`）。

| 接口 | 列表字段 |
|------|----------|
| `GET /payments/pending` | `payments` |
| `GET /payments/status/{status}` | `payments` |
| `GET /payments/user/{telegram_id}` | `payments` |
| `GET /balance/transactions/recent` | `transactions`（时间窗由 `days` 决定） |
| `GET /balance/transactions/type/{transaction_type}` | `transactions` |

## `GET /balance/user/{telegram_id}/summary`

按用户 + 时间窗口（`period_days`，默认 30）汇总流水，响应在 **`telegram_id`**、**`period_days`** 之外，还包含：

| 字段 | 含义 |
|------|------|
| `total_transactions` | 窗口内笔数 |
| `deposit_count` / `total_deposit_amount` | 充值 |
| `withdrawal_count` / `total_withdrawal_amount` | 提现/消费类 `withdraw` |
| `refund_count` / `total_refund_amount` | 退款 |
| `payment_count` / `total_payment_amount` | `payment` |
| `hold_count` / `total_hold_amount` | 预授权冻结流水 |
| `hold_release_count` / `total_hold_release_amount` | 解冻流水 |
| `consumption_count` / `total_consumption_amount` | 算力实际扣费 |

金额均为该窗口内对应类型金额累加（支出类按绝对值计入 `total_*_amount`）。

其它余额相关路由（如 **`GET /balance/transaction/{transaction_id}`**）在可关联时同样返回 **`task_id`**。`transaction_type` 合法值与领域枚举一致，含 **`hold`**、**`hold_release`**、**`consumption`**。带列表的分页字段见上文「列表响应：`total` 与 `returned`」。

## Tasks（算力任务）

前缀 **`/tasks`**（需 API Key，与 `users` 等一致）。

### `POST /tasks`

创建任务并做预授权冻结（增加 `balance_held`，不减少总余额 `balance`）。

**请求体（JSON）** 主要字段：

| 字段 | 说明 |
|------|------|
| `telegram_id` | 用户 Telegram ID |
| `task_type` | **字符串**（最长 64），与 [`backend/config/workflow_recipes.yaml`](../backend/config/workflow_recipes.yaml) 中配方键对齐；当前 YAML 已登记 **`face_swap`**。新增能力时在 YAML 增加键即可，无需改表结构。 |
| `third_party_platform` | 如 `runninghub` |
| `priority_type` | 如 `lite`、`default`、`plus` |
| `input_payload` | 与 `task_type` 绑定的 JSON 对象 |
| `task_description` | 可选 |
| `idempotency_key` | 可选；同一用户下非空时唯一 |
| `hold_amount` | 预授权冻结上限（正数） |

**响应**：`task_id`、`status`、`queued_at`、**`created`**（是否本次新建；幂等重放时为 `false`，且不会再次触发入队占位）。

**错误**：`detail` 多为 `{"message": "...", "code": "..."}`，常见 `code`：

| code | HTTP |
|------|------|
| `user_not_found` | 404 |
| `user_inactive` | 403 |
| `insufficient_funds` | 402 |
| `invalid_hold_amount` | 422 |
| 其它业务冲突 | 400 / 409 |

### `GET /tasks/{task_id}?telegram_id=<id>`

查询任务状态；`telegram_id` 必须与任务归属一致，否则 **404**。除基础状态字段外，终态任务可能返回：

| 字段 | 说明 |
|------|------|
| `billable_seconds` | 可计费秒数；成功任务上游耗时优先，本地运行时长兜底 |
| `charged_amount` | 实际扣费（美元）；失败 / 取消为 0 |
| `pricing_version` | 本次结算使用的价目版本 |

## 算力计费

MVP 使用 **按运行秒数计费**，价格来自
[`backend/config/pricing_table.yaml`](../backend/config/pricing_table.yaml)：

- 价格维度为 **`task_type + priority_type`**。
- 仅 **`succeeded`** 任务扣费；**`failed` / `cancelled`** 不计费并释放冻结。
- 可计费秒优先读取 RunningHub 结果中的 `taskCostTime` 等上游耗时字段；缺失时回退 `started_at → completed_at`。
- 费用按秒向上取整后计算，并保留 6 位 USD 精度。
- 若计算费用超过本任务 hold，则按 hold 上限扣费，并在 `result_payload.billing.charge_capped` 记录。
- 缺少启用的价格配置时视为配置错误，不静默扣 0。

## 异步执行（Celery）

`POST /tasks` 在 **`created: true`** 时，在 **HTTP 响应返回且写库事务已提交之后**（FastAPI `BackgroundTasks`）再调用入队逻辑，向 Celery 投递 **`tasks.execute_compute`**（队列 **`compute`**），前提是环境变量 **`CELERY_BROKER_URL`** 已配置（通常为 Redis）。

- **未配置 broker**：打 **`compute_task_enqueue_skipped`** 类告警日志（`reason=no_broker`），不入队。
- **`send_task` 抛错**：打 **`compute_task_enqueue_failed`**（含异常栈），不向外层抛出，避免影响已返回的 HTTP 结果；应通过日志与监控兜底。

幂等重放（`created: false`）不会再次入队。

### RunningHub 终态（Webhook，公开路由）

当 **`third_party_platform=runninghub`** 且 Worker 成功 **`create`** 后，任务在 DB 中多为 **`running`** 并带有 **`upstream_task_id`**。平台任务结束时向配置的 **`webhookUrl`** 发起 **`POST /api/webhooks/runninghub/{task_id}`**（实现见 [`backend/api/routers/webhooks.py`](../backend/api/routers/webhooks.py)，**不要求** `X-API-Key`）。Handler 先 **200**，在 **`BackgroundTasks`** 内完成幂等检查、可选 **`query_task`**、写 **`result_payload` / 终态**，再 **`settle_task_balance_hold_async`**。默认也可通过 `tasks.poll_terminal` 轮询 RunningHub `query_task` 收敛终态；Webhook 与轮询共用终态结算幂等。

### 入队可靠性（进阶）

`BackgroundTasks` 在 **API 进程崩溃** 等情况下不持久化；若需「提交后绝不丢消息」，可演进为：

- **事务外箱（outbox）**：与任务行同事务写入 outbox 表，独立进程读表再 `send_task`，成功则标记已投递；或
- **以 DB 为准的补偿**：任务行已存在、队列为空时由定时任务扫描 **`queued`** 状态补投递；并与 Celery **`task_id`** / 业务 **`task_id`** 绑定以便对账。

详见同目录 [`DEPLOYMENT.md`](DEPLOYMENT.md) 与 [`04-BUSINESS-DESIGN.md`](04-BUSINESS-DESIGN.md) §7。

## Docker Compose 联调验收（app + worker + redis + db）

1. 配置 `.env`（至少 **`POSTGRES_PASSWORD`**；若需鉴权则设 **`API_KEY`**）。Compose 会为 **`app` / `worker`** 注入 **`DATABASE_URL`**、**`CELERY_BROKER_URL`**。
2. 启动：`docker compose up -d --build`，等待 **`db`**、**`redis`** healthy，**`worker`** 完成 `alembic upgrade head` 并监听队列 **`compute`**。
3. 确保测试用户有足够余额（可用 **`PUT /users/{telegram_id}/balance`** 调账或先走充值流程）。
4. **`POST /tasks`**（Header：`X-API-Key` 与配置一致），body 至少含 `telegram_id`、`task_type`、`third_party_platform`、`priority_type`、`input_payload`、`hold_amount`。
5. 预期：**`worker` 日志**出现处理该 **`task_id`** 的记录；**`GET /users/{id}/balance`** 中 **`balance_held`** 在结算后回落；**`GET /users/{id}/transactions`** 或 **`/balance/user/{id}/summary`** 中出现 **`hold`**、**`consumption`**、**`hold_release`** 等类型与文档一致。

具体 curl 示例以保持与本机 **`PORT`**（默认 8000）一致为准。
