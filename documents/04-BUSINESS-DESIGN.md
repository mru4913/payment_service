# 整体业务处理设计

本文档描述在「支付与余额」能力之上，扩展 **第三方算力 API（如 RunningHub）**、**队列调度** 与 **双 Telegram Bot** 后的 **端到端业务处理设计**。与 [01-PRD.md](01-PRD.md)（需求）、[02-ARCHITECTURE.md](02-ARCHITECTURE.md)（技术架构）配合阅读。

**外部参考**（上游 API 行为与限制以官方为准）：[RunningHub API 文档](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287334)

**文档结构（速览）**：§1–2 范围与术语 · §3 双 Bot · §4 架构 · §5 业务流程 · §6 计费 · §7 Celery/Worker · §8 数据模型 · §9 状态机 · §10–13 错误、安全、演进与维护。

---

## 1. 目的与范围

| 项 | 说明 |
|----|------|
| **目的** | 统一描述用户从「充值」到「消费算力」的闭环，以及内部队列、计费、对账的职责划分。 |
| **范围** | 双 Bot 交互、HTTP API、**Celery Worker**、Redis、PostgreSQL、第三方 ComfyUI 云端 API（Celery 设计见 **§7**）。 |
| **非目标** | 不替代官方 RunningHub 文档；不规定具体 HTTP 路径命名（实现阶段在 OpenAPI 中固化）。 |

---

## 2. 术语

| 术语 | 含义 |
|------|------|
| **支付 Bot** | 负责充值、余额、订单与账户类交互的 Telegram 机器人。 |
| **业务 Bot** | 负责提交/查询算力任务、展示结果入口的 Telegram 机器人。 |
| **业务任务（Task）** | 用户发起的一次可计费请求；持久化对应表 **`tasks`** 中的一行，主键 **`task_id`**，并入队 Celery。 |
| **任务类型（task_type）** | 业务分类（产品线、能力枚举等），**决定走哪套入参校验、上传步骤与上游组参逻辑**；与 **`third_party_platform`**、**`input_payload`**（内含资源标识等）配合使用。图片类示例见 **§5.2.1**。 |
| **任务说明（task_description）** | 可选的人类可读摘要，供列表/客服展示；结构化执行参数放在 **`input_payload`**。 |
| **第三方平台（third_party_platform）** | 算力/工作流由哪家提供，**稳定枚举**（如 `runninghub`）。与 **`input_payload`**（资源侧参数）、**`upstream_task_id`**（本次运行实例）联用。 |
| **第三方执行实例 ID（upstream_task_id）** | 调用平台「创建任务/运行」接口后，**由第三方返回的、标识这一次运行的 ID**（用于轮询状态、对账）。**Workflow 等资源标识** 不单独建列，放在 **`input_payload`** 的约定字段中（如 `workflow_id`）。 |
| **上游任务** | 第三方平台上的一次实际运行实例，对应 **`upstream_task_id`**，有独立状态与运行时长。 |
| **可计费秒（billable seconds）** | 用于对用户扣费的时长计量，遵循「多任务并发时按各任务时长之和累计」的规则。 |
| **槽位（slot）** | 在调用 RunningHub **创建运行** API 之前占用的并发许可；实现为 **Redis 计数器**，拆为 **全局** 与 **按 `telegram_id` 每用户** 两层，**两层同时未满**才允许 `create`。**本阶段不**实现按 `priority_type` / `instanceType` 的独立总池（与代码、运维配置保持一致）。 |

---

## 3. 双 Bot 职责划分

```
┌─────────────────────┐          ┌─────────────────────┐
│     支付 Bot         │          │     业务 Bot         │
│  充值 / 余额 / 历史   │          │  提交任务 / 查状态   │
│  语言 / 帮助         │          │  结果链接 / 失败说明  │
└──────────┬──────────┘          └──────────┬──────────┘
           │                                │
           └────────────────┬───────────────┘
                            ▼
                 ┌─────────────────────┐
                 │  FastAPI 后端        │
                 │  同一用户体系        │
                 │  telegram_id 关联    │
                 └─────────────────────┘
```

**原则**

- 两个 **Bot Token**、两个 **进程**（或两个容器），避免单进程拖死两类流量。
- **共享** `frontend/core`、`frontend/shared`（i18n、错误处理、`base_bot` 等）。
- 后端 **同一套** 用户、余额、流水；业务 Bot 只调用「任务与计费」相关接口，不在 Bot 内持有上游 API Key。

**用户体验**

- 支付与业务分两个对话窗口时，需在 `/start` 或帮助文案中说明分工，并可提供互相跳转的 `t.me/...` 深链。

---

## 4. 总体业务架构

```
用户 ──► 业务 Bot / 自有 HTTP API
              │
              ▼
        ┌─────────────┐     入队      ┌─────────────┐
        │  Web/API    │ ───────────► │ Redis       │
        │  鉴权/扣费   │              │ (Celery)    │
        │  创建 Task  │              └──────┬──────┘
        └──────┬──────┘                     │
               │                             ▼
               │                    ┌─────────────┐
               │                    │ Celery      │
               │                    │ Worker(s)   │
               │                    └──────┬──────┘
               │                           │
               │                           ▼
               │                    ┌─────────────┐
               │                    │ RunningHub  │
               │                    │ (第三方)    │
               │                    └──────┬──────┘
               │                           │
               ▼                           ▼
        ┌─────────────────────────────────────────┐
        │ PostgreSQL：用户、余额、流水、tasks、task_balance_holds  │
        └─────────────────────────────────────────┘
```

**隔离说明**

- **逻辑隔离**：Web 只负责「接单 + 持久化 + 入队」；Worker 负责「占槽、调上游、**收结果（Webhook 或轮询）**、写终态、计量」。**RunningHub**：**当前阶段不以公网 Webhook 为必选项**（可暂缓搭建 `RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`）；**无公网回调时**以 **`POLL_ENABLED` + Celery Beat + `tasks.poll_terminal`** 周期性 **`query_task`** 收敛终态为主路径（见 `documents/DEPLOYMENT.md`、`documents/third-party/01-runninghub-api.md`）。配置公网 HTTPS 并下发 `webhookUrl` 时，**Webhook + 回调内可选 query** 仍可用，与轮询共用 **CAS 幂等**，二者择一或并存均可。
- **密钥隔离**：RunningHub **API Key 仅注入 Worker 环境**（或 KMS），Web 容器不持有。

---

## 5. 核心业务流程

### 5.1 资金入账（已有能力）

1. 用户在 **支付 Bot** 创建充值订单（如 TRC20 USDT）。
2. 到账确认后 **增加美元余额**（系统内统一 USD 记账，与 PRD/架构一致）。
3. 余额变动写入 **余额流水**（类型：充值），便于审计。

### 5.2 发起算力任务（目标能力）

1. 用户在 **业务 Bot**（或开放 API）提交参数：**`third_party_platform`**（如 `runninghub`）、**`task_type`**、可选 **`task_description`**、**`priority_type`**、以及落入 **`input_payload`** 的结构化数据（其中包含 **资源标识**，如 RunningHub 的 **workflow ID**，字段名在各类 `task_type` 的 schema 中约定，如 `workflow_id`）；Worker 按 `third_party_platform` 与 `task_type` 解析 `input_payload` 并映射到上游 API（参数名以官方 OpenAPI 为准）。
2. **API 层**校验：
   - 用户存在且可用（若现有 **`users.is_active`** 等字段，未激活用户应拒绝创建 Task）；
   - **余额或额度**满足产品规则（预授权 / 最低余额 / 单笔上限等，产品可配置）。
3. 创建 **Task** 记录（表 `tasks`）：`queued` 状态，生成 `task_id`；若采用预授权则写入 **`task_balance_holds`**（见 **§8**）。
4. 投递 **Celery 任务**（消息体仅携带 `task_id` 等轻量字段），立即向客户端返回 `task_id`（异步）。

### 5.2.1 按任务类型处理（图片能力示例：换脸等）

当前 **`tasks`** 模型**已覆盖**「不同图片能力走不同流程」的需求，约定如下：

| 维度 | 作用 |
|------|------|
| **`task_type`** | 业务侧 **能力判别键**；API 为 **字符串**（`VARCHAR(64)`），与 **`workflow_recipes.yaml`** 中配方键对齐。仓库当前 YAML 已登记 **`face_swap`**；新增键时扩展 YAML 与 Bot 菜单即可。 |
| **`third_party_platform`** | 使用哪家第三方（如 `runninghub`）；决定 SDK/URL、鉴权方式与字段语义。 |
| **`input_payload`** | **与 `task_type` 绑定的结构化 JSON**（含 **workflow_id**（若配方未写死）、源图引用等）；配方由 `recipe` 模块翻译为上游 `nodeInfoList`。 |
| **`task_description`** | 可选展示文案（如用户备注）；**不替代** `input_payload` 里的结构化参数。 |

**Worker 侧建议**：按 **`third_party_platform` + `task_type`** 做 **策略/注册表**（如 `handlers[(platform, task_type)]`），从 **`input_payload`** 读取 **workflow_id**（或其它资源字段），再完成：是否需要先调官方 **上传接口**、如何拼 `nodeInfoList`、如何把 `priority_type` 映射为 `instanceType`。创建运行成功后回写 **`upstream_task_id`**。新增一种图片能力时，主要增量是 **平台 + 新的 `task_type` + 对应 payload schema**，**不必改 `tasks` 表结构**。

**设计边界**：若多种能力 **共用同一 workflow**、仅靠参数区分，可在 **`input_payload` 中使用相同 `workflow_id`**（同一 `third_party_platform` 下），用 `task_type` + `input_payload` 其它字段区分行为（以可维护性为准，优先「一种能力一工作流」更清晰）。

### 5.3 队列与 Worker

实现细节见 **§7（Celery 与 Worker 设计）**。

1. Worker 从队列取出任务。
2. **申请槽位**（见 **§7.5**）：在 **`create` 调用前** 对 Redis 执行 **原子脚本**（全局计数 + 每用户计数）；若任一层已满，则 **不调用上游**，由 Celery **有限次退避重试**（不得忙等占满 Worker 线程）。
3. 槽位占用成功后按 `third_party_platform` 调用对应 API **创建运行**；将第三方返回的 **本次执行实例 ID** 写入 **`upstream_task_id`**（**workflow 等资源标识** 已存在于 **`input_payload`** 快照中，无需与运行实例 ID 混为一列）。若 **`create` 失败**，Worker **立即释放**已占槽位（与 §7.5 一致）。
4. **收结果、写终态**：**`runninghub`**：**已实现**（1）**公网 Webhook**（`POST /api/webhooks/runninghub/{task_id}`），回调内可 **再调一次 query** 固结果；（2）**无 Webhook 时**由 **`tasks.poll_terminal`** 轮询 **`query_task`**，并按 **`POLL_MAX_RUNNING_SEC`** 对仍无终态的 **`running`** 做超时 discard。**当前产品节奏**：**公网 Webhook 可先不做**，不配 `RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL` 即不向 RH 下发 `webhookUrl`，仅依赖轮询路径即可闭环。**非 runninghub** 的当前实现仍走 **stub 终态**（`promote_task_to_terminal_and_settle`），仅适合联调。
5. **释放槽位**：在任务进入 **终态**（`succeeded` / `failed` / `cancelled`）且 **已对 RH 成功 `create`** 的路径上释放（**Webhook 写终态、轮询写终态、或超时 discard** 任一先到即可；实现上依赖「终态后 settle / release_slot」与幂等）。`create` 前的失败路径由 Worker 在捕获错误时释放。轮询路径下 **`running` 过长** 由 **`POLL_MAX_RUNNING_SEC`** 收敛，不再单独依赖「仅 Webhook 释槽」的运维假设。

### 5.4 第三方执行（RunningHub）

- 工作流须在控制台 **至少成功运行过一次**，否则 API 可能报错（见官方文档说明）。
- 图生图等需 **先上传** 再在节点中引用路径的场景，由 Worker 按官方顺序调用。
- 多输出节点时，结果可能为 **多条资源**，业务层需支持列表型结果存储与展示。

### 5.5 结果与通知

1. Task 终态写入表 `tasks`：`succeeded` / `failed` / `cancelled`。
2. **可计费秒** 在成功分支上计算并写入；失败 / 取消任务不计费（见 **§6**）。
3. **扣费**：按产品策略执行 **预扣 + 结算** 或 **事后扣款**（见 **§6.4**），并写余额流水（类型：消费）。
4. 业务 Bot 侧：用户通过 **轮询命令** 或 **推送消息**（若实现）获取结果链接或错误原因。

---

## 6. 计费模型

### 6.1 对内成本（上游）

- 上游按 **机型** 与 **运行时长** 计费；并发时 **按各任务运行时长之和** 累计，而不是按「墙钟的一段并发窗口」单算一次。
- 机型示例（与商务合同及控制台一致，以下为设计占位）：

| 机型 | 说明 | 请求侧约定（示例） |
|------|------|-------------------|
| Lite | 系统调度 | 默认或指定 lite |
| Standard（24GB） | `instanceType = default`（示例） | `default` |
| Plus（48GB） | `instanceType = plus`（示例） | `plus` |

> 具体参数名、枚举值以 RunningHub 当前 OpenAPI 与控制台为准。  
> 库表 **`tasks.priority_type`** 存业务档位编码（如上表「请求侧约定」列）；Worker 在调用上游时完成 **`priority_type` → `instanceType`** 的映射。

### 6.2 对外售价（用户）

- 用户侧以 **美元** 展示与扣费，资金来源于 **USDT 充值** 换算后的 USD 余额（与现有支付设计一致）。
- **内部**需维护：CNY 成本 → USD 成本或 **直接 USD 标价**（含毛利），并支持后续调价。

### 6.3 可计费时长（billable seconds）

- 每个上游任务优先使用 RunningHub 返回的耗时字段（如 `taskCostTime`）作为 **计费时长**；缺失时回退 `started_at` → `completed_at` 的本地运行时长。
- `billable_seconds` 按秒向上取整，实际扣费为 `billable_seconds × price_per_second_usd`，金额保留 6 位 USD 精度。
- 客户标价由 `backend/config/tier_platform_catalog.yaml` 顶层 `priority_tiers.price_per_second_usd` 管理；RunningHub 内部成本价由 `platforms.runninghub.priority_tiers.cost_per_second_usd` 管理。
- workflow 预计秒数由 `backend/config/workflow_recipes.yaml` 的 `estimated_runtime_seconds` 管理。
- 预授权冻结金额 = `estimated_runtime_seconds × priority_tiers.price_per_second_usd`；结算写入 `pricing_version` 便于对账。
- 某用户在统计窗口内：

\[
\text{总可计费秒} = \sum_{\text{任务 }i} \max(0, \text{duration}_i)
\]

- **并发示例**：3 个任务同时各跑 60 秒 → 计 **180 秒**，不是 60 秒。

### 6.4 扣费时机（产品二选一或组合）

| 模式 | 做法 | 适用 |
|------|------|------|
| **事后扣费** | 成功任务结束后按可计费秒 × 单价扣余额 | 当前实现 |
| **预授权** | 入队前冻结估算上限，结束后多退少补 | 防止跑完发现余额不足 |
| **混合** | 低余额拒绝入队 + 事后按秒结算 | 中小规模常用 |

当前产品条款：仅 **`succeeded`** 任务计费；**`failed` / `cancelled`** 写 `billable_seconds=0`、`charged_amount=0` 并释放冻结。若计算费用超过本任务 hold，则以 hold 上限扣费，并在 `result_payload.billing.charge_capped` 记录。

### 6.5 总余额、预授权冻结与 `balance_held`

| 字段 / 概念 | 含义 |
|-------------|------|
| **`users.balance`** | 用户 **总余额**（美元计价，与充值/提现一致）。预授权 **不** 减少本字段。 |
| **`users.balance_held`** | **冗余**：当前所有 **`task_balance_holds.status = active`** 的冻结金额之和；与 `balance` **同币种**，列名不含币种后缀。创建/释放/capture 时与 hold 行 **同事务** 更新，避免依赖每次 `SUM(holds)`。 |
| **可用余额**（不存库） | `balance - balance_held`。入队前校验：`可用 >= 本次预授权上限`。 |

**不变量**：`balance_held >= 0`；`balance >= balance_held`。提现或调减 `balance` 时需保证调减后仍 **≥ `balance_held`**。

**余额流水**（`balance_transactions`）：

- **`hold`**：预授权成功；`balance_before_usd` = `balance_after_usd` = 当前总余额；`amount_usd` 为冻结额度（正数，表示事件规模）。
- **`hold_release`**：释放冻结（未扣费或 capture 后释放额度）；若总余额未变，则前后快照仍相等；`amount_usd` 为释放额度。
- **`consumption`**：实际扣费；`amount_usd` 建议与现有提现类一致用 **负数** 表示划出；`balance_after_usd` 反映扣减后的总余额。

**capture 顺序（实现参考）**：先按实际费用扣减 `balance` 并记 `consumption`，再将本任务对应 hold 记为 `captured`、`balance_held` 减去该 hold 全额，并记一条 `hold_release`（总余额已为扣费后快照，与 `hold` 类流水一致可审计）。

---

## 7. Celery 与 Worker 设计

本节约定：**异步执行算力任务** 采用 **Celery**；**Broker**（与可选后端状态）使用 **Redis**。与 §4 架构图一致：FastAPI 只负责创建 `tasks` 行并入队；**Worker 进程** 消费消息、占槽、调第三方、回写 DB。

### 7.1 部署拓扑与进程边界

```
┌─────────────────┐         ┌─────────────────┐
│  uvicorn        │         │  Celery worker  │
│  (FastAPI)      │         │  (1..N 进程)    │
│  创建 Task      │  LPUSH  │  执行第三方调用  │
│  delay(task_id) │ ──────► │  更新 tasks 行   │
└────────┬────────┘  Redis  └────────┬────────┘
         │         broker            │
         └──────────┬─────────────────┘
                    │
              ┌─────▼─────┐
              │ PostgreSQL │
              │ tasks 等   │
              └───────────┘
```

| 进程 | 职责 | 禁止事项 |
|------|------|----------|
| **Web（FastAPI）** | 鉴权、校验、`tasks` 插入、`task_balance_holds`（若需要）、`celery_app.send_task(...)`、立即返回 `task_id` | 同步阻塞等待上游跑完；持有第三方 API Key（可选：若仅 Worker 持有则 Web 绝不调用上游） |
| **Celery Worker** | 按 `task_id` 加载行、占槽、调 `third_party_platform` 对应客户端、轮询/收结果、写 `upstream_task_id` / 终态 / 计费字段、释放槽 | 承担用户 HTTP 会话；在内存中长期缓存大文件 |

**同一代码库**：`backend` 内定义 `celery_app`、共享 `Settings`、SQLAlchemy models；Web 与 Worker **启动命令不同**（`uvicorn` vs `celery -A ... worker`）。

**实现提示**：Worker 内若使用 **§7.3** 的 `SELECT ... FOR UPDATE` 等事务语义，需采用 **同步数据库会话** 或在 Celery 任务中显式处理 async/sync 边界；与当前 FastAPI 异步栈并存时避免混用同一连接池不当导致阻塞。

### 7.2 Redis 用途

| 用途 | 说明 |
|------|------|
| **Broker** | Celery 消息队列（队列名/路由与任务名在实现中固化，如 `tasks.execute_compute`）。 |
| **结果后端（可选）** | 若启用 `result_backend`，可用于短 TTL 的异步结果查询；**推荐以 PostgreSQL `tasks` 为权威状态**，避免双写不一致。小体量可 **关闭 result_backend**，仅 DB。 |
| **全局槽位 + 每用户槽位** | 与 §7.5 一致；与 Broker **可共用同一 Redis**，键前缀 **`eshow:slot:`**（实现以代码为准），避免与 Celery 协议键冲突。 |
| **幂等 / 去重（可选）** | 如对 `celery_task_id` 或 `(task_id, step)` 去重，可用 Redis SET NX + TTL。 |

消息体 **只传轻量参数**（至少 `task_id`）；完整入参、workflow 等一律以 DB 中 **`tasks.input_payload`** 为准，避免 Redis 存放大 JSON。

### 7.3 Celery 任务契约

| 项 | 约定 |
|----|------|
| **任务名** | 例如 `tasks.execute_compute`（实现阶段唯一命名，便于监控过滤）。 |
| **参数** | 主参 **`task_id: UUID`**；可选 **`idempotency_token`**（与表 `idempotency_key` 对齐时由 Web 传入 Worker 侧校验）。 |
| **执行步骤（逻辑顺序）** | ① `SELECT ... FOR UPDATE` 或状态 CAS 将 `queued` → `running`（防并发双跑）；② **申请全局 + 用户槽位**（Redis Lua，见 §7.5）；失败则 **不重试上游**，由 Celery 对 **`slot_busy`** 类错误退避重投；③ 读 `input_payload`、上传资源后调 **`create`** → 写 `upstream_task_id` 与 `running`；若 **`create` 异常**则 **释槽** 再抛错；④ **RunningHub**：由 **Webhook 或 `tasks.poll_terminal` 轮询** 写终态并结算（二者 CAS 幂等，当前可仅启用轮询）；**其它/占位**：Worker 内直接推进终态（**不占提交槽**）；⑤ 计算 `billable_seconds`、扣费/解冻；⑥ 写 `result_payload`、终态、`completed_at`；⑦ **终态路径上释槽**（Webhook / 轮询 / discard 任一，仅当本次从非终态变为终态，幂等）。 |
| **幂等** | 对同一 `task_id`，若已为终态则 **直接 return**（Celery 重投不重跑上游）。 |
| **重试** | **槽位已满**（`slot_busy`）：Celery `retry` + 固定短 `countdown`，`max_retries` 上限内排队等槽释放。其它仅对 **可恢复错误**（网络超时、429、5xx）退避；**参数/鉴权错误** 不重试，任务标记 `failed`。 |
| **与 `tasks.celery_task_id`** | Worker 在首次执行时可将当前 Celery 任务 ID 写回表，便于在 Flower/日志中与 DB 关联。 |

### 7.4 Worker 并发配置

| 概念 | 说明 |
|------|------|
| **`worker_concurrency`** | Celery 进程内 **prefork/gevent 并发数**，表示「能同时消费多少条 Celery 消息」。 |
| **与上游槽位关系** | **不得**仅用 `worker_concurrency` 代替上游限额。即使 Worker 开 200 进程，**全局槽位**（如 100）仍须在 **真正调用创建运行 API 前** 占用，否则仍可能压垮第三方或触发封禁。 |
| **建议** | Worker concurrency 可略大于槽位，使部分协程处于「等槽」阻塞/重试；或 concurrency ≈ 槽位 + 小缓冲。 |
| **多机扩容** | 多 Worker 容器共享 **同一 Redis broker + 同一槽位计数**，保证全局上限。 |

### 7.5 并发与槽位（业务约束）

| 控制点 | 说明 |
|--------|------|
| **全局槽位** | 全项目对 RunningHub **已 `create` 且尚未终态** 的任务数上限（与合同/容量对齐）；跨多 Worker 共享 **同一 Redis 计数器** `eshow:slot:global`。环境变量 **`SLOT_MAX_CONCURRENT_GLOBAL`**，`<=0` 表示 **不限制**（本地/压测）。 |
| **每用户槽位** | 按 **`tasks.telegram_id`** 计数，防止单用户占满全局槽；键形如 `eshow:slot:user:{telegram_id}`。环境变量 **`SLOT_MAX_CONCURRENT_PER_USER`**，`<=0` 表示 **不限制**。 |
| **Redis URL** | **`SLOT_REDIS_URL`**；未设置时 **回退** 使用 **`CELERY_BROKER_URL`**（单 Redis 部署）。未配置 Broker 且未配槽位 URL 时，算力不入队，槽位逻辑不生效。 |
| **占用时机** | 在 **`create_comfy_task` 调用前** `INCR`；**`create` 失败**则同请求内 **`DECR` 回滚**（脚本外由代码保证对称）。**`create` 成功**后保持占用，直至 **Webhook、轮询终态、或超时 discard 将任务写终态** 后在结算路径上 **`DECR`**（仅一次，依赖「已终态则早退」避免双释）。 |
| **硬杀 Worker** | 进程 `SIGKILL` 可能导致计数与真实运行中任务 **短期不一致**；缓解：重启前清空槽位键、或后续用 DB 租约字段做对账（本阶段文档级风险）。 |
| **队列深度** | 允许堆积；**槽位**控制「同时向 RH 提交运行」，**Celery 队列**控制「等待执行」。 |
| **档位池** | **本阶段不**按 `priority_type` 单独设总并发池（见 §2「槽位」说明）；后续若商务按机型拆分再加。 |

### 7.6 观测与故障

- **日志**：贯穿 **`task_id`**（及 `upstream_task_id` 一旦存在）；与 `celery_task_id` 同时打点便于排障。
- **Flower / Prometheus（可选）**：队列长度、Worker 存活、任务失败率；与 DB 中 `status` 分布交叉核对。
- **优雅停机**：Worker 收到 SIGTERM 时尽量 **不中断** 已占槽且已提交上游的长任务；依赖 Celery `worker_soft_shutdown_timeout` 等与上游超时策略对齐（实现阶段配置）。

---

## 8. 数据库设计

本节约定：**领域实体名为 Task**；物理表名为 **`tasks`**（小写复数，避免与 SQL 保留字混淆）。冻结额度使用表 **`task_balance_holds`**。金额字段与现有库一致，**美元**使用 `NUMERIC(15,6)`；时长使用 `NUMERIC(12,3)` 可表示小数秒（若上游提供）。

### 8.1 与现有表的关系

| 已有表 | 说明 |
|--------|------|
| `users` | 主键 `telegram_id`；`balance` 仍为美元余额。 |
| `payments` | 充值订单，与 Task 无直接外键。 |
| `balance_transactions` | 余额流水；**扩展**可选外键 `task_id` → `tasks.task_id`，并增加交易类型（见 8.4）。 |

### 8.2 表 `tasks`（实体 Task）

用户侧一次可计费的算力请求，一行对应一个 `task_id`。

| 列名 | 类型 | 约束 / 说明 |
|------|------|-------------|
| `task_id` | UUID | 主键，默认 `gen_random_uuid()`（或应用层生成） |
| `telegram_id` | BIGINT | FK → `users.telegram_id`，NOT NULL |
| `status` | VARCHAR(20) | NOT NULL，如 `queued` / `running` / `succeeded` / `failed` / `cancelled` |
| `task_type` | VARCHAR(64) | NOT NULL，业务任务类型（**字符串键**，与 `workflow_recipes.yaml` 等配置对齐；当前示例 **`face_swap`**）。**Worker/Bot 按此路由**；与 `third_party_platform`、`input_payload` 可组合使用 |
| `task_description` | TEXT | NULL，展示用短说明（用户填写或系统生成）；不参与上游执行逻辑，避免与 `input_payload` 重复存放大段参数 |
| `third_party_platform` | VARCHAR(32) | NOT NULL，**第三方算力平台编码**（稳定枚举，如 `runninghub`）。标明本条 Task 由哪家执行；多供应商时 Worker 按此路由。 |
| `priority_type` | VARCHAR(32) | NOT NULL，业务侧优先级/算力档位编码（如 `lite` / `default` / `plus`）；请求上游前映射为 `instanceType` 等字段 |
| `input_payload` | JSONB | NOT NULL，**按 `task_type` 解释**的结构化入参快照；**须包含该平台所需的资源标识**（如 RunningHub 的 **workflow ID**，建议键名 `workflow_id` 或与各 `task_type` schema 一致）。另含业务参数；控制体积，敏感字段脱敏；大文件仅存 URL/对象键/上游引用，不塞 base64 |
| `result_payload` | JSONB | NULL，结果摘要（如输出 URL 列表） |
| `upstream_task_id` | VARCHAR(128) | NULL，**第三方在创建本次运行后返回的执行实例 ID**（用于轮询状态、客服对账）；创建运行成功后由 Worker 写入。**Workflow 等资源 ID** 仅存于 **`input_payload`**，与本列语义不同。 |
| `queued_at` | TIMESTAMPTZ | NOT NULL，默认 `now()` |
| `started_at` | TIMESTAMPTZ | NULL |
| `completed_at` | TIMESTAMPTZ | NULL |
| `billable_seconds` | NUMERIC(12,3) | NULL，本 Task 可计费秒数 |
| `charged_amount` | NUMERIC(15,6) | NULL，结算后实际扣费（美元） |
| `pricing_version` | VARCHAR(32) | NULL，价目版本，便于对账 |
| `error_code` | VARCHAR(64) | NULL |
| `error_message` | TEXT | NULL |
| `idempotency_key` | VARCHAR(64) | NULL，幂等键；建议 **部分唯一索引** `UNIQUE (telegram_id, idempotency_key) WHERE idempotency_key IS NOT NULL` |
| `celery_task_id` | VARCHAR(128) | NULL，Celery 任务 ID，便于排障 |

**`input_payload` 中的资源 ID 与 `upstream_task_id`** — **不重复**：前者是 **请求里指定的「跑哪个资源」**（如 `workflow_id`），随 Task 创建即写入 JSON；后者是 **第三方返回的「这一次运行」** 的实例 ID，仅在创建运行成功后写入。同一 `workflow_id` 可对应多次不同 `upstream_task_id`。

**索引建议**

- `(telegram_id, queued_at DESC)`：用户任务列表、调用记录查询。
- `(status, queued_at)`：堆积与调度监控。
- `(task_type, queued_at DESC)`：按任务类型统计与运营筛选（可选）。
- `(third_party_platform, upstream_task_id)`：按平台 + 执行实例 ID 反查、对账（`upstream_task_id` 是否全局唯一依各平台约定）。

**说明**：若未来「一次用户请求」对应 **多个** 上游子任务，可新增子表（如 `task_subtasks`）按子任务分别记录 `billable_seconds`，再汇总到父 `task_id`；当前设计按 **一 Task 对应一个上游任务** 为默认。

**与多能力（换脸 / 编辑等）的关系**：**不要求**为每种能力增加表字段；通过 **`third_party_platform` + `task_type` + 类型化 `input_payload`（含各能力对应的 `workflow_id` 等）** 即可扩展。若需对某类任务单独限价、单独并发，可在配置或未来扩展表 **`task_type_quotas`** 中实现（当前文档不强制）。

### 8.3 表 `task_balance_holds`（Task 余额冻结）

用于 **预授权**：在 Task 执行前冻结一笔美元 **上限**，结束后 **多退少补**；与 `users.balance` 及流水联动更新。

| 列名 | 类型 | 约束 / 说明 |
|------|------|-------------|
| `hold_id` | UUID | 主键 |
| `task_id` | UUID | FK → `tasks.task_id`，NOT NULL；**默认一对一**：`UNIQUE(task_id)` |
| `telegram_id` | BIGINT | FK → `users.telegram_id`，NOT NULL（与 Task 一致，便于按用户汇总冻结） |
| `amount_usd` | NUMERIC(15,6) | NOT NULL，冻结额度上限 |
| `status` | VARCHAR(16) | NOT NULL：`active`（占用中）/ `released`（已解冻未扣）/ `captured`（已从冻结中划扣） |
| `created_at` | TIMESTAMPTZ | NOT NULL，默认 `now()` |
| `released_at` | TIMESTAMPTZ | NULL，解冻或完成 capture 的时间 |
| `captured_amount_usd` | NUMERIC(15,6) | NULL，`captured` 时实际划扣金额，应 ≤ `amount_usd` |

**索引建议**

- `(telegram_id, status)`：查询用户当前 `active` 冻结总额、风控。

**业务规则（建议）**

- 创建 Task 且策略为预授权时：插入 `task_balance_holds`（`active`），并记流水类型 `hold`（若采用）。
- Task 成功结束：按 `billable_seconds` × 单价计算应付，受 hold 上限保护 → `captured_amount_usd`，余额扣减，剩余冻结释放 → 流水 `consumption` + `hold_release`。
- Task 失败 / 取消：不计费，写 0 费用并释放冻结，`released_at` 落库。

若产品需要 **同一 Task 多次冻结**，可去掉 `task_id` UNIQUE，增加 `sequence` SMALLINT；当前文档按 **一 Task 一条 hold** 简化。

### 8.4 表 `balance_transactions` 扩展

在现有 `deposit` / `withdraw` / `payment` / `refund` 等类型基础上，为算力消费与冻结增加类型，例如：

- `consumption`：Task 实际扣费。
- `hold`：冻结余额（可选，若冻结不降低 `balance` 而仅记「可用额度」，则需独立字段或账本设计；若冻结即减少可用余额，则与现有 `balance` 语义对齐后入账）。
- `hold_release`：解冻退回可用。

并增加 **可空** 外键：

- `task_id` UUID NULL，FK → `tasks.task_id`（`ON DELETE SET NULL` 或 `RESTRICT`，依审计要求选择）。

便于按 `task_id` 联查「该 Task 对应哪几条流水」。

### 8.5 审计与「API 调用记录」

- **最小实现**：以表 **`tasks`** 为主数据源即可满足「按用户 / 时间 / 状态」查询与导出。
- **细粒度审计（可选）**：新增追加型表 `task_events`（`task_id`、`event_type`、`payload` JSONB、`created_at`），记录轮询、回调等，避免 `tasks` 行被频繁覆盖丢失过程。

### 8.6 ER 简图

```
users (telegram_id)
  ├── payments
  ├── balance_transactions [+ task_id FK 可选]
  └── tasks (telegram_id)
        └── task_balance_holds (task_id, 建议 1:1)
```

---

## 9. 任务状态机（建议）

```
queued ──► running ──► succeeded
           │    │
           │    └──► failed
           └──► cancelled（若产品支持取消且上游允许）
```

- `queued`：已入队，可能尚未占槽。
- `running`：已占槽且已提交上游或正在执行。
- `failed`：亦可由 **API 层校验失败** 在从未进入 Worker 前写入（与 Worker 内失败共用终态时，建议用 `error_code` 区分来源）。
- 终态需 **幂等**：重复回调或重复轮询不重复扣费。

---

## 10. 错误、重试与补偿

- **可重试错误**（网络抖动、429）：Celery 退避重试，限制最大次数。
- **不可重试错误**（参数错误、API Key 无效）：直接失败，记录原因，不无限重试。
- **扣费失败**：与 Task 终态解耦处理（例如标记欠费、冻结新任务），避免静默丢失。
- **超长运行**：超时策略需与上游计费规则一起定义（取消是否计费）。

---

## 11. 安全与合规

- 上游 API Key、用户上传的敏感图片：**最小权限**、**不落日志明文**。
- 开放 HTTP API 时：鉴权（Token / 签名）、限流、与 Bot 共用用户体系。
- 结果链接：限时签名 URL，避免永久公开。

---

## 12. 与当前仓库的演进关系

| 现状 | 演进方向 |
|------|----------|
| `frontend/bot/` + `frontend/integrations/` | 单 Bot：用户通过首页 inline UI 进入账户、充值、任务历史与 AI 换脸；`/task` 仅保留为编号查询入口，业务访问均经 HTTP 调 FastAPI。 |
| `backend/services/balance_service.py` 等 | 复用余额；扩展「消费 / 冻结」流水类型与扣费接口；对齐表 `tasks`、`task_balance_holds`。 |
| FastAPI 路由 | 已含 **`/tasks`**（鉴权）与 **`/api/webhooks/runninghub/{task_id}`**（公开）；支付回调与算力 Webhook 按路由拆分。 |
| Celery / Redis | 已实现 **`tasks.execute_compute`**、`CELERY_BROKER_URL`、Compose **`worker`** 服务；未配 broker 时 API 仅告警不入队。 |

---

## 13. 文档维护

- 上游 API、机型、价格变更时，同步更新 **第 6 节** 与内部 **单价配置**，不必复制全文到本文档。
- Celery 队列名、重试策略、Worker 与槽位实现变更时，同步更新 **第 7 节**。
- 本文档修订时请在提交说明中标注 `docs:`。

---

**版本**：1.12（§12：`frontend/bot` + HTTP 集成层）  
**关联**：[01-PRD.md](01-PRD.md) · [02-ARCHITECTURE.md](02-ARCHITECTURE.md) · [03-PROJECT.md](03-PROJECT.md)
