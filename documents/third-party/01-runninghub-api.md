# 第三方 01：RunningHub（ComfyUI / 工作流）API 对接方案

> **状态（与代码同步）**：**`RunningHubClient`**、**`run_runninghub_pipeline`**、**轮询终态**（`tasks.poll_terminal`、`poll_tasks.py`：批内复用 client、`POLL_MAX_CONCURRENT`、`poll_terminal: tick` 日志，与 **`query_snapshot`** 共用 **`query_task`**）、**Webhook 路由**（`POST /api/webhooks/runninghub/{task_id}`，**可选**，配公网 `RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL` 时启用）、**本地临时文件 + cron 清理**均已落地。**非 `runninghub` 平台**在 `compute_runner` 中仍为 **stub 终态**（开发联调）。  
> **架构决策（当前默认）**：以 **`POLL_ENABLED` + Celery Beat（`poll_schedule`）+ `tasks.poll_terminal`** 为主路径，用 **`query_task`** 收敛终态，并按 **`POLL_MAX_RUNNING_SEC`**（默认 2h）对仍无终态的 **`running`** 做 **discard**（标 `failed`、结算、释槽）。**公网 HTTPS + `RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`** 时可选启用 **Webhook**（通常延迟更低）；Webhook 与轮询共用 **`cas_transition_running_to_terminal`** 幂等，避免双路径重复结算。  
> **官方文档入口**：[RunningHub API 文档（中文）](https://www.runninghub.cn/runninghub-api-doc-cn/)

---

## 1. 目的与范围

- **`third_party_platform == runninghub`**：Worker 向 RH 发起任务；`running` 后 **默认**由 **`tasks.poll_terminal`** 周期性 **`query_task`** 写终态并 **`settle_task_balance_hold_async`**。若配置 **`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`**，可同时启用 **HTTP Webhook**（回调内可选再 **`query_task`** 固 `results`），与轮询 **CAS 幂等**。**其它平台**仍为 stub 终态路径，便于联调。
- 本文只覆盖 **HTTP API 行为、字段映射与实施阶段**；价目、美元换算、按秒计费等以 `04-BUSINESS-DESIGN.md` 为准另行拍板。

---

## 2. 官方文档索引（本项目会引用到的页面）

| 主题 | 链接 |
|------|------|
| 模型 / 任务错误码说明 | [doc-8435517](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8435517) |
| `nodeId` / `fieldName` / `nodeInfoList` 说明 | [doc-8287336](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287336) |
| 文件上传（binary，`multipart/form-data`） | [api-425749007](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749007) |
| 发起 ComfyUI 任务（高级，`/task/openapi/create`） | [api-425749013](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749013) |
| 获取工作流 API 格式 JSON | [api-425749014](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749014) |
| 查询任务生成结果 V2（`/openapi/v2/query`） | [api-425767306](https://www.runninghub.cn/runninghub-api-doc-cn/api-425767306) |
| 获取 Webhook 事件详情（调试用） | [api-425749005](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749005) |
| 重新发送指定 Webhook 事件 | [api-425749006](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749006) |

---

## 3. 基础约定

- **Base URL**：`https://www.runninghub.cn`（与 OpenAPI `servers` 一致）。
- **鉴权**：文档示例普遍要求请求头 **`Authorization: Bearer <API_KEY>`**；部分接口另要求 **`Host: www.runninghub.cn`**。
- **请求体中的 `apiKey`**：发起任务等 JSON 体内仍常带 `apiKey` 字段，与 Header 的关系以实现时官方最新文档为准（建议实现层集中从配置读取，避免重复硬编码）。

### 3.1 Python 客户端（`backend/third_party`）

- **实现位置**：[`backend/third_party/runninghub/client.py`](../../backend/third_party/runninghub/client.py) 中的 `RunningHubClient`（`httpx.AsyncClient` 异步）；子模块含类型、错误、常量及 **priority → `instanceType`** 的 YAML 读取（[`instance_type.py`](../../backend/third_party/runninghub/instance_type.py)）。
- **包入口**：[`backend/third_party/__init__.py`](../../backend/third_party/__init__.py) 导出 `RunningHubClient`、`RunningHubAPIError`、`MISSING_API_KEY`、`get_runninghub_client`。
- **已封装方法**：`upload_media`、`create_comfy_task`、`query_task`（兼容扁平 V2 与 `{code,msg,data}` 信封）、`get_workflow_json`（`getJsonApiFormat`，返回 `data.prompt` 原始字符串）、`get_webhook_detail`、`retry_webhook`；支持 `async with` 与 `aclose()`。
- **请求头**：`Authorization: Bearer …`；`Host` 由 `runninghub_base_url` 的主机名推导（与自定义镜像/环境一致），解析失败时回退 `www.runninghub.cn`。
- **应用配置**（[`backend/config.py`](../../backend/config.py) / [`.env.example`](../../.env.example)）：`RUNNINGHUB_API_KEY`、`RUNNINGHUB_BASE_URL`；**`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL` 非空**时 `rh_pipeline` 拼装 `webhookUrl`（**可选**，当前产品默认不配、以轮询为主）。**轮询**：**`POLL_ENABLED`**、**`POLL_INTERVAL_SEC`**、**`POLL_BATCH_SIZE`**、**`POLL_MAX_CONCURRENT`**、**`POLL_MAX_RUNNING_SEC`**；须 **`CELERY_BROKER_URL`** 才会注册 Beat 的 `poll_schedule`（见 `DEPLOYMENT.md`）。
- **工厂**：`get_runninghub_client(settings)` 在 `runninghub_api_key` 为空时抛出 `RunningHubAPIError`（`rh_code == MISSING_API_KEY`），与客户端方法缺密钥时一致；调用方可统一 `except RunningHubAPIError`，并用 ``exc.is_retryable()`` 区分是否适合退避重试（配置类错误为不可重试）。
- **单测**：[`tests/backend/test_runninghub_client.py`](../../tests/backend/test_runninghub_client.py)（`httpx.MockTransport`，不调真实 RH）。

---

## 4. 核心接口速查（与 Worker 相关）

### 4.1 发起任务

- **路径**：`POST /task/openapi/create`
- **用途**：基于 `workflowId` + 可选 `nodeInfoList` 覆盖节点参数，创建一次 ComfyUI 运行。
- **关键入参**（摘自文档）：
  - `apiKey`、`workflowId`（必填）
  - `nodeInfoList`：`[{ nodeId, fieldName, fieldValue }, ...]`
  - `instanceType`：如 `plus`，与当前系统的 `priority_type` 映射需定义（见 §6）
  - 可选：`webhookUrl`、`retainSeconds`（企业共享 Key、计费相关）、`accessPassword` 等
- **成功响应**：`code === 0`，`data.taskId`（字符串）、`data.taskStatus`（如 `QUEUED` / `RUNNING`）、`clientId`、`promptTips` 等。

### 4.2 查询结果（`query`，当前默认主路径）

- **路径**：`POST /openapi/v2/query`
- **Body**：`{ "taskId": "<RunningHub 返回的 taskId>" }`
- **响应语义**（文档示例）：`status` 为 `SUCCESS` | `RUNNING` | `FAILED`；失败时带 `errorCode`、`errorMessage`；成功时 `results` 含输出 URL、`outputType` 等。
- **与本项目（当前默认）**：**`tasks.poll_terminal`**（`backend/workers/poll_tasks.py`）在 **`POLL_ENABLED`** 时由 Celery Beat 周期性扫 **`running`** + **`upstream_task_id`** 并调 **`query_task`**；单 tick 内 **复用同一 `RunningHubClient`**，并发度由 **`POLL_MAX_CONCURRENT`**（默认 1）限制；超时 **`POLL_MAX_RUNNING_SEC`** 则 discard。每次 tick 打 **`poll_terminal: tick`** 结构化日志（见 `DEPLOYMENT.md`）。若已启用 **Webhook**，回调内仍可选 **一次** `query` 拉齐 `results`（与 `query_snapshot` 共用逻辑，支持注入 `rh_client` 避免重复建连）。**退避重试** 等细化留待后续迭代（见 §8）。

### 4.3 资源上传（无外链场景）

- **路径**：`POST /openapi/v2/media/upload/binary`
- **用途**：multipart 上传图片/音视频/ZIP；响应中 **`fileName`** 填入 Comfy 节点（如 `LoadImage` 的 `image`）；**`download_url`** 用于标准模型 API 场景。
- **注意**：文档说明上传链接**非永久存储**，有效期等限制以官方为准。

### 4.4 获取工作流 API JSON（辅助）

- **路径**：`POST /api/openapi/getJsonApiFormat`
- **用途**：按 `workflowId` 拉取 `api_format`，用于运营/开发对齐 `nodeId`、字段名，或做服务端校验（可选）。

### 4.5 Webhook（可选：公网 HTTPS 时启用）

- 发起任务时在 `POST /task/openapi/create` 中 **可选** 填写 **`webhookUrl`**（由 **`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`** 控制；不配则不下发）。任务完成时平台 **POST** 到该地址（文档示例含 `event: TASK_END`、`taskId`、`eventData` JSON 字符串）。
- **与本项目**：
  - **当前默认不依赖 Webhook**：以 §4.2 **轮询 `query_task`** 收敛终态；Webhook 为 **增强项**（低延迟、少打 RH 查询）。
  - 启用时需要 **公网 HTTPS** 可达的专用路由，**快速返回 2xx**；重逻辑在 **`BackgroundTasks`** 中异步执行（见 `webhooks.py`）。
  - **幂等**：同一 RH `taskId` / 同一 `event` 可能重复投递，终态写库须按 `tasks.upstream_task_id`（或内部 `task_id`）去重。
  - **验签 / IP 白名单**：以官方最新说明为准；若无签名机制，至少依赖 **path 密钥、速率限制、仅接受 JSON** 等减小滥用面。
- **运维与调试**：
  - [获取 webhook 事件详情](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749005)：`POST /task/openapi/getWebhookDetail`，按 `taskId` 查看 `callbackStatus`、`callbackResponse`、`retryCount` 等。
  - [重新发送指定 webhook 事件](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749006)：`POST /task/openapi/retryWebhook`，`webhookId` 为详情接口返回的 `id`，用于投递失败后的补偿。

---

## 5. 错误码与可重试性

- 完整对照表见官方：[模型 API 错误码说明](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8435517)。
- **原则**（草案）：
  - **限流 / 繁忙 / 超时 / 内部错误**（如 1003、1010、1011、1005、1006、1504 等）：可对 **创建任务**、**轮询 / Webhook 触发的单次 `query` 拉结果** 做有限次退避重试；轮询侧细化策略见 §11 / `DEPLOYMENT.md`。
  - **参数/权限/内容安全**（如 1007、1002、1501、1505 等）：一般 **不重试同一 payload**，应标记任务失败并 `error_code` / `error_message` 回写 `tasks`，释放或按策略结算预授权。
- **`/openapi/v2/query` 的 `errorCode`/`errorMessage`**：与 doc-8435517 中模型错误体系对齐存储，便于客服与对账。

---

## 6. 与本项目数据模型的映射（草案）

| 本系统 | RunningHub / 说明 |
|--------|-------------------|
| `tasks.task_id`（UUID） | 内部主键；与 RH `taskId` **不同**，勿混用。 |
| `tasks.upstream_task_id` | 存 RH 返回的 **`data.taskId`（字符串）**。 |
| `tasks.third_party_platform` | 固定语义 `runninghub`（与现有枚举一致）。 |
| `tasks.priority_type` | 映射到 RH `instanceType`：`lite`→`lite`，`default`→`standard`，`plus`→`plus`（见 `backend/config/tier_platform_catalog.yaml`）。 |
| `tasks.input_payload` | 见 §7；配方或透传模式下须能解析出 RH `workflowId` 与 `nodeInfoList`。 |
| `tasks.result_payload` | 存 **`eventData` 解析结果** 与/或 **`query` 返回的 `results` 摘要**（URL 列表、类型等），按需裁剪体积。 |
| `tasks.status` | `queued` → 入队未提交 RH；`running` → 已拿到 `upstream_task_id` 且 RH 侧运行中；`succeeded` / `failed` / `cancelled` 与 RH 终态对齐规则需固化（见 §8）。 |
| `tasks.error_code` / `error_message` | RH 失败时的 `errorCode` / `errorMessage`（或 HTTP 层错误）。 |

---

## 7. `input_payload` 约定（与 `workflow_recipes.yaml` 对齐）

当前仓库 [`backend/config/workflow_recipes.yaml`](../../backend/config/workflow_recipes.yaml) 中 **已登记** 的 `task_type` 键含 **`face_swap`**、**`universal_edit`** 等（配方将 `input_payload` 译为 RH `nodeInfoList`；`workflow_id` 在 YAML 或 payload 中须为真实 RH `workflowId`）。**`task_type` 在 API 层为自由字符串**（`CreateTaskRequest.task_type`，最长 64），Worker 按配方表解析；新增能力时在 YAML 增加键即可。

**透传模式**（`nodes: null`、`workflow_id` 来自 payload）仍被 `recipe` 模块支持，YAML 中未预置条目时也可在将来增加新键。

换脸类 **`face_swap`** 的 `input_payload` 示例（字段名须与配方 `nodes` 键一致）：

```json
{
  "source_image": "https://…/a.jpg",
  "target_image": "https://…/b.jpg"
}
```

- **`workflow_id`**：配方中写死时由 Worker 使用；配方为 `null` 时须出现在 `input_payload`（见 `recipe.get_recipe` 逻辑）。
- 若值为 **本机绝对路径**：Worker 经 `common.storage.resolve_file_ref` 读文件或下载 URL 后 **`upload_media`**，再写 RH `fieldValue`。
- 官方 **`nodeInfoList`** 字段说明：[doc-8287336](https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287336)。

---

## 8. Worker 执行状态机（草案）

1. **领取内部任务**：Celery 消费 `tasks.task_id`（UUID），DB 行锁或乐观更新，避免重复提交。
2. **提交 RH**：`POST /task/openapi/create`；**`webhookUrl` 可选**（仅当配置 **`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`** 时由 `rh_pipeline` 拼装）。成功则写 **`upstream_task_id`**，`status` → `running`，`started_at`。
3. **等待完成（已实现）**：
   - Worker **`rh_pipeline`** 在 `create` 成功后写 **`upstream_task_id`**、`status=running`，**不阻塞**等 RH 跑完。
   - **默认：轮询终态**：**`POLL_ENABLED`** 时由 Celery Beat 调度 **`tasks.poll_terminal`**，对 **`running`** 且已有 **`upstream_task_id`** 的任务批量 **`query_task`**，与 Webhook 路径共用 **`query_snapshot`**；超过 **`POLL_MAX_RUNNING_SEC`** 仍无终态则 **discard**（标 `failed`、结算、释槽）。**后续可选**：告警、[getWebhookDetail](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749005) / [retryWebhook](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749006) 排障与补偿 UI。
   - **可选：HTTP 回调**：[`backend/api/routers/webhooks.py`](../../backend/api/routers/webhooks.py) **`POST /api/webhooks/runninghub/{task_id}`**（公开路由，无 API Key）。Handler **立即 200**，在 **`BackgroundTasks`** 中：加载 `task_id`、幂等跳过已终态、可选 **`query_task`**、写 **`result_payload` / 终态 / `error_*`**，再 **`settle_task_balance_hold_async`**（与文档原建议「finalize Celery 任务」等价，当前为进程内异步任务，非独立 Celery finalize）。
4. **终态**：写 `result_payload` / `error_*` / `completed_at`，再调用现有 **`settle_task_balance_hold_async`**（`charged_amount` 来源见 §9）。
5. **幂等**：同一 `tasks.task_id` 重复执行时，若已有 `upstream_task_id` 则 **不重复 create**（除非业务定义「重试 = 新任务」）；**Webhook / 轮询** 多次到达时须 **幂等落终态**（**`cas_transition_running_to_terminal`**）。
6. **`query` 为 `SUCCESS` 与 `results` 空否**：是否在 **`results` 为空** 时仍落 **`succeeded`**，**须对照 RH 官方响应与线上样本再拍板**；未验证前不在代码中做强校验，以免任务长期无法终态。

---

## 9. 计费与 `charged_amount`

- MVP 已定稿为 **按运行秒数计费**：优先读取 RH 返回的 **`taskCostTime`** 等耗时字段；缺失时回退本地 `started_at` → `completed_at`。
- 价格配置在 **`backend/config/pricing_table.yaml`**，维度为 **`task_type + priority_type`**；结算写入 **`billable_seconds` / `charged_amount` / `pricing_version`**。
- 仅 **`succeeded`** 任务扣费；**`failed` / `cancelled`** 写 0 费用并释放 hold。若计算费用超过 hold，则按 hold 上限 capture 并在 `result_payload.billing.charge_capped` 记录。

---

## 10. 配置项（`Settings` / `.env`）

以下已在 [`backend/config.py`](../../backend/config.py) 与 [`.env.example`](../../.env.example) 中落地：

- **`RUNNINGHUB_API_KEY`**：Bearer 与 JSON 体内 `apiKey` 同源配置。
- **`RUNNINGHUB_BASE_URL`**：默认 `https://www.runninghub.cn`。
- **`RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL`**：**可选**；非空则拼 **`webhookUrl`** 与 FastAPI 挂载一致；**空则不下发**（**当前默认**，以轮询为主）。
- **后续可选**：`RUNNINGHUB_WEBHOOK_PATH_SECRET` / 官方验签字段；轮询侧退避（`POLL_*` 已含 **`POLL_INTERVAL_SEC`**、**`POLL_BATCH_SIZE`**、**`POLL_MAX_CONCURRENT`**、**`POLL_MAX_RUNNING_SEC`**，见 `.env.example` 与 `DEPLOYMENT.md`）。

---

## 11. 分阶段实施建议

| 阶段 | 内容 | 验收 |
|------|------|------|
| **P0** | `httpx` 封装 + `create`；**轮询终态**（`POLL_*` + Beat + `tasks.poll_terminal`）+ **`query_task`** + 写 `upstream_task_id` / 终态 / `result_payload` + 结算；**可选**公网 **Webhook 路由**（配 `RUNNINGHUB_WEBHOOK_PUBLIC_BASE_URL` 时下发 `webhookUrl`） | **已实现**；默认部署以轮询闭环，端到端需 `RUNNINGHUB_*`、`CELERY_BROKER_URL`、Beat、`worker_poll`、真实 `workflow_id` |
| **P1** | 错误码映射、create/**轮询与回调**链路的重试与幂等、`error_code` 对齐；接入 [getWebhookDetail](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749005) 排障 | 失败可解释；回调失败可定位并 [retryWebhook](https://www.runninghub.cn/runninghub-api-doc-cn/api-425749006) |
| **P2** | 继续细化 RH 账单字段、价格运营后台与对账报表 | 流水与 RH 侧可追溯 |
| **P3** | **binary 上传、多模态工作流**等能力扩展（轮询终态已在 P0） | 无外链素材可走通；Webhook 仍为可选增强 |

---

## 12. 讨论清单（需要你方拍板）

1. **`priority_type` → `instanceType`**：以 `tier_platform_catalog.yaml` 为准；若 RH 文档变更需同步该文件。
2. **结算运营**：是否需要价格运营后台、历史价目查询与 RH 账单自动对账？
3. **`webhookUrl` 形态**：固定 path + 密钥、是否带内部 `task_id` query、与多环境（staging/prod）域名如何隔离？
4. **`input_payload`**：是否允许客户端传 **完整 `workflow` JSON**（RH 支持覆盖 `workflowId`），还是仅允许平台登记过的 `workflow_id`？
5. **合规与内容安全**：1501/1505 等失败时，对用户展示文案与退款/释放 hold 策略？

---

## 13. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-05-14 | 架构叙述：**当前默认轮询为主**，Webhook 为可选增强；§4.2 / §4.5 / §8 / §11 同步 |
| 2026-05-12 | 与代码同步：Worker/Webhook/本地存储已接；§7 配方仅 `face_swap`；§8 回调实现描述 |
| 2026-05-11 | 初稿：整理官方链接、接口要点与与本项目 `Task` 模型映射 |
| 2026-05-08 | 历史决策（已由 2026-05-14 起以轮询默认叙述为准）：曾拟首版以 **Webhook** 为主、**轮询兜底** 延后；补充 `retryWebhook` 文档索引与配置项 |
