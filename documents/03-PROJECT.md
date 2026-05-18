# Eshow（易修）项目结构文档

## 1. 项目概述

Eshow（易修）是一个基于 Telegram Bot API 和 FastAPI 构建的支付与算力服务系统。系统采用前后端分离架构，其中 Telegram Bot 作为用户交互界面，FastAPI 作为后端服务，提供支付处理和数据管理功能。

## 2. 项目目录结构

```
eshow/   # 仓库根目录名以克隆时为准
├── frontend/                    # Telegram Bot - 多机器人架构
│   ├── core/                    # 共享核心组件
│   │   ├── __init__.py
│   │   ├── base_bot.py          # 基础Bot类
│   │   ├── i18n.py              # 国际化工具
│   │   └── utils.py             # 通用工具
│   ├── locales/                 # 多语言支持
│   │   ├── en/messages.json
│   │   └── zh/messages.json
│   ├── bot/                     # Telegram 机器人（支付 + 算力等）
│   │   ├── bot.py               # build_telegram_app
│   │   ├── handlers/            # 命令与对话
│   │   └── keyboards.py
│   ├── integrations/            # 调 FastAPI 的 HTTP 客户端
│   ├── admin_bot/               # 管理机器人 (可选)
│   │   ├── __init__.py
│   │   ├── bot.py               # 主程序
│   │   ├── handlers.py          # 管理处理
│   │   ├── commands.py          # 管理命令
│   │   └── keyboards.py         # 管理键盘
│   ├── shared/                  # 共享组件
│   │   ├── error_handler.py     # 错误处理
│   │   └── callback_handler.py  # 回调处理
│   └── runner.py                # 多机器人启动器
├── backend/                     # FastAPI后端服务
│   ├── database/                # 🗄️ 数据库层
│   │   ├── models/              # 📋 数据模型
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # 基础模型类 (Base)
│   │   │   ├── user.py          # 用户模型
│   │   │   ├── payment.py       # 支付模型
│   │   │   └── balance_transaction.py # 余额交易模型
│   │   ├── repositories/        # 🏪 数据访问层
│   │   │   ├── __init__.py
│   │   │   ├── base_repository.py # 基础仓库类
│   │   │   ├── user_repository.py # 用户数据访问
│   │   │   ├── payment_repository.py # 支付数据访问
│   │   │   └── balance_transaction_repository.py # 余额交易数据访问
│   │   └── session.py           # 数据库会话管理
│   ├── services/                # 🔧 业务逻辑层
│   │   ├── __init__.py
│   │   ├── user_service.py      # 用户业务逻辑
│   │   ├── payment_service.py   # 支付业务逻辑
│   │   └── balance_service.py   # 余额业务逻辑
│   ├── api/                     # 🌐 API层
│   │   ├── routers/            # 🔀 路由模块
│   │   │   ├── __init__.py
│   │   │   ├── users.py        # 👤 用户相关API路由
│   │   │   ├── payments.py     # 💳 支付相关API路由
│   │   │   ├── balance.py      # 💰 余额相关API路由
│   │   │   └── health.py       # ❤️ 健康检查路由
│   │   ├── dependencies.py     # 🔗 依赖注入配置
│   │   ├── middleware.py       # 🛡️ 中间件配置
│   │   ├── main.py            # 🚀 API主入口 (集成所有路由)
│   │   └── __init__.py
│   ├── config.py                # ⚙️ 配置定义
│   ├── globals.py               # 🌍 全局实例管理
│   ├── main.py                  # 🚀 FastAPI应用入口
│   ├── payments/                # 💳 支付集成
│   │   ├── __init__.py
│   │   ├── base.py              # 支付提供商接口
│   │   ├── alipay.py            # 支付宝集成
│   │   ├── wechat.py            # 微信支付集成
│   │   ├── trc20_usdt.py        # TRC20 USDT 链上支付提供商
│   │   ├── trc20_monitor.py     # TRC20 USDT 链上到账监控后台任务
│   │   └── callbacks.py         # 支付回调处理
│   └── utils/                   # 🛠️ 工具模块
│       ├── __init__.py
│       └── payment_utils.py     # 支付工具函数
├── scripts/                     # 部署和维护脚本
│   ├── setup_db.py              # 数据库初始化
│   ├── migrate_db.py            # 数据库迁移
│   ├── seed_data.py             # 测试数据生成
│   └── deploy.sh                # 部署脚本
├── tests/                       # 测试代码
│   ├── __init__.py
│   ├── test_bot.py              # Bot功能测试
│   ├── test_api.py              # API测试
│   ├── test_services.py         # 服务测试
│   └── test_payments.py         # 支付集成测试
├── docker/                      # 容器化配置
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── nginx.conf
├── docs/                        # 项目文档
│   ├── README.md
│   ├── API.md
│   └── DEPLOYMENT.md
├── config/                      # 配置文件
│   ├── default.yaml
│   ├── development.yaml
│   └── production.yaml
├── logs/                        # 日志目录 (git忽略)
├── .env                         # 环境变量
├── .env.example                 # 环境变量示例
├── pyproject.toml               # 项目配置
├── docker-compose.yml           # 主Docker配置
├── Dockerfile                   # 容器构建
├── .gitignore                   # Git忽略
├── .python-version              # Python版本
└── README.md                    # 项目说明
```

### 2.1 与当前仓库的差异说明（以代码为准）

上图为历史骨架；下列与树形不一致处请以此为准：

- **设计文档目录**：根目录 **`documents/`**（含 `API.md`、`DEPLOYMENT.md`、`04-BUSINESS-DESIGN.md` 等）；树中的 **`docs/`** 若不存在则忽略。
- **`common/`**：根级共享包（如上传路径 **`storage.py`**），镜像构建已 **`COPY common/`**。
- **`backend/api/routers/`**：除 `users`、`payments`、`balance`、`health` 外，另有 **`tasks.py`**（算力任务）、**`webhooks.py`**（RunningHub 回调，公开）。
- **`backend/workers/`**：Celery 应用、**`compute_runner`**、**`rh_pipeline`**（RunningHub 提交链）。
- **`backend/third_party/runninghub/`**：RunningHub HTTP 客户端。
- **`backend/database/models/`**：含 **`task.py`**、**`task_balance_hold.py`** 等；`repositories/`、`services/` 有对应 Task / 预授权逻辑。
- **`backend/config/workflow_recipes.yaml`**、**`tier_platform_catalog.yaml`**：算力配方与档位映射。
- **`scripts/cleanup_uploads.py`**：临时上传目录清理（配合 `upload_dir` 配置）。
- **`frontend/bot/`**：Telegram 应用（`build_telegram_app`）；`handlers/` 含支付、**`/balance`/`/task`/`/compute`**（经 HTTP）；充值等部分 handler 仍可能直连 DB。
- **`frontend/integrations/`**：`BackendClient` 调 FastAPI（`BACKEND_BASE_URL`、`X-API-Key`），**不** import `backend.database`。

## 3. 核心模块说明

### 3.1 Frontend (Telegram Bot)

**职责**: 多机器人架构，支持支付、管理等不同功能，提供国际化的用户界面

**主要组件**:
- `bot/`: Telegram 机器人（支付、算力对话等；`integrations` 调后端 HTTP）
- `admin_bot/`: 管理机器人，处理管理功能 (可选)
- `core/`: 共享基础组件 (Bot基类、国际化工具等)
- `locales/`: 多语言支持 (中文、英文等)
- `shared/`: 可复用的处理器和中间件

### 3.2 Backend (FastAPI Service)

**职责**: 提供RESTful API，处理业务逻辑，管理数据

**主要文件**:
- `main.py`: FastAPI应用入口，路由注册
- `config.py`: 配置类定义 (Pydantic Settings)
- `globals.py`: 全局配置实例和logger管理
- `database.py`: PostgreSQL连接和会话管理
- `models.py`: SQLAlchemy数据模型定义
- `services.py`: 核心业务逻辑（支付处理、用户管理）
- `api.py`: RESTful API路由定义
- `payments/`: 支付平台集成代码

### 3.3 Scripts (部署工具)

**职责**: 自动化部署、数据库管理和维护任务

**主要文件**:
- `setup_db.py`: 数据库初始化脚本
- `migrate_db.py`: 数据库迁移脚本
- `seed_data.py`: 生成测试数据
- `deploy.sh`: 一键部署脚本

## 4. 技术栈配置

### 4.1 核心技术栈

| 组件 | 技术选型 | 版本要求 | 说明 |
|------|----------|----------|------|
| **编程语言** | Python | 3.12+ | 现代Python版本，支持最新的语言特性 |
| **Web框架** | FastAPI | 最新稳定版 | 高性能异步Web框架，自动生成API文档 |
| **Bot框架** | python-telegram-bot | 20.7+ | Telegram官方Bot框架，支持异步操作 |
| **数据库** | PostgreSQL | 18+ | 强大的开源关系型数据库 |
| **HTTP客户端** | httpx | 0.28+ | 异步HTTP客户端，用于TronScan API调用 |
| **ORM** | SQLAlchemy | 2.0+ | 现代Python ORM，支持异步操作 |
| **项目管理** | uv | 最新版 | 快速的Python包管理器 |
| **代码格式化** | Ruff | 最新版 | 快速的Python代码检查和格式化工具 |
| **容器化** | Docker & Docker Compose | 24.0+ & 2.0+ | 容器化部署和编排 |

### 4.2 开发工具链

```bash
# 项目管理
uv init                    # 初始化项目
uv add fastapi             # 添加依赖
uv sync                    # 同步依赖

# 代码质量
ruff check .              # 代码检查
ruff format .             # 代码格式化

# 容器化
docker build -t tg-bot .  # 构建镜像
docker-compose up -d      # 启动服务
```

### 4.3 环境要求

- **操作系统**: Linux/macOS/Windows (推荐Linux)
- **内存**: 至少4GB RAM
- **磁盘**: 至少10GB可用空间
- **网络**: 稳定的互联网连接

## 5. 配置管理

### 5.1 环境变量配置

```bash
# .env
# 数据库配置（与 docker-compose 默认一致：用户/库名 eshow）
DATABASE_URL=postgresql+asyncpg://eshow:password@localhost:5432/eshow

# Telegram Bot配置
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_WEBHOOK_URL=https://your-domain.com/webhook

# 支付平台配置
ALIPAY_APP_ID=your_alipay_app_id
ALIPAY_PRIVATE_KEY=your_private_key
WECHAT_APP_ID=your_wechat_app_id
WECHAT_MCH_ID=your_merchant_id

# TRC20 USDT 配置
TRC20_WALLET_ADDRESS=your_trc20_wallet_address    # 设置后自动启用链上监控
TRC20_CHECK_INTERVAL=15                            # 轮询间隔(秒)，默认15
TRC20_ORDER_TIMEOUT_MINUTES=15                     # 订单超时(分钟)，默认15

# 应用配置（见 backend/config.py Settings）
ENVIRONMENT=development
SECRET_KEY=your_secret_key
DEBUG=true
```

## 6. 开发工作流

### 6.1 本地开发

```bash
# 1. 克隆项目
git clone <repository-url>
cd eshow   # 若目录名不同请改为你的克隆路径

# 2. 创建虚拟环境 (使用uv)
uv venv --python 3.12

# 3. 激活虚拟环境
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 4. 同步项目依赖
uv sync

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置数据库和API密钥

# 6. 初始化数据库
python scripts/setup_db.py

# 7. 运行FastAPI后端服务
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 8. 运行Telegram Bot (新终端)
python frontend/runner.py           # 启动所有机器人
# 或单独启动 Bot: python -m frontend.runner
```

### 6.2 代码开发流程

```bash
# 代码检查和格式化
uv run ruff check .              # 检查代码问题
uv run ruff format .             # 格式化代码

# 运行测试
uv run pytest tests/             # 运行所有测试
uv run pytest tests/test_api.py  # 运行API测试

# 类型检查 (如果配置了mypy)
uv run mypy .

# 构建和部署
docker-compose build             # 构建镜像
docker-compose up -d             # 启动服务
```

### 6.2 Docker开发

```bash
# 1. 确保Docker和Docker Compose已安装
docker --version
docker-compose --version

# 2. 启动完整开发环境
docker-compose up -d

# 3. 查看服务状态
docker-compose ps

# 4. 查看日志
docker-compose logs -f backend    # 查看后端日志
docker-compose logs -f bot        # 查看Bot日志

# 5. 进入容器调试
docker-compose exec backend bash
docker-compose exec db psql -U postgres

# 6. 停止服务
docker-compose down

# 7. 清理数据卷 (如果需要重新开始)
docker-compose down -v
```

### 6.3 运行测试

```bash
# 运行所有测试
uv run pytest tests/

# 运行特定测试
uv run pytest tests/test_api.py
uv run pytest tests/test_bot.py

# 生成覆盖率报告
uv run pytest --cov=backend --cov=frontend --cov-report=html --cov-report=term

# 运行带性能分析的测试
uv run pytest tests/ --durations=10

# 运行CI模式 (停止首次失败)
uv run pytest tests/ --tb=short -x
```

## 7. 部署流程

### 7.1 生产部署

```bash
# 1. 构建生产镜像
docker build -f docker/Dockerfile -t eshow:latest .

# 2. 使用生产配置启动
docker-compose -f docker/docker-compose.prod.yml up -d

# 3. 运行数据库迁移
docker-compose -f docker/docker-compose.prod.yml exec backend python scripts/migrate_db.py
```

### 7.2 自动化部署

```bash
# 使用部署脚本
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

## 8. 代码规范

### 8.1 命名约定

- **文件**: snake_case (user_service.py)
- **类**: PascalCase (UserService)
- **函数/变量**: snake_case (get_user_balance)
- **常量**: UPPER_SNAKE_CASE (MAX_RETRY_COUNT)

### 8.2 代码格式化

```bash
# 使用Ruff进行代码格式化和检查
pip install ruff
ruff check .          # 检查代码问题
ruff format .         # 格式化代码
```

### 8.3 提交规范

```
feat: 新功能
fix: 修复bug
docs: 文档更新
style: 代码格式调整
refactor: 代码重构
test: 测试相关
chore: 构建过程或工具配置更新
```

## 9. 相关文档

- [01-PRD.md](01-PRD.md) - 产品需求文档
- [02-ARCHITECTURE.md](02-ARCHITECTURE.md) - 系统架构设计文档
- [04-BUSINESS-DESIGN.md](04-BUSINESS-DESIGN.md) - 整体业务处理设计（双 Bot、队列、计费）
- [third-party/01-runninghub-api.md](third-party/01-runninghub-api.md) - 第三方 01：RunningHub ComfyUI API 对接方案
- [API.md](API.md) - API接口文档
- [DEPLOYMENT.md](DEPLOYMENT.md) - 部署指南

## 10. 常见问题

### Q: 如何添加新的支付方式？
A: 在 `backend/payments/` 目录下创建新的支付提供商文件，继承 `PaymentProvider` 基类实现统一接口，然后在 `callbacks.py` 中注册。参考 `trc20_usdt.py` 的实现。

### Q: TRC20 USDT 支付如何工作？
A: 用户创建充值订单后获得收款地址和唯一金额，转账后后台 `TRC20Monitor` 每15秒轮询 TronScan API，按金额自动匹配订单并完成充值。在 `.env` 中设置 `TRC20_WALLET_ADDRESS` 即可启用。

### Q: 如何修改Bot命令？
A: 在 `frontend/commands.py` 中添加新的命令处理函数，并在 `bot.py` 中注册。

### Q: 如何添加新的API接口？
A: 在 `backend/api.py` 中添加新的路由函数，使用Pydantic进行数据验证。

### Q: 如何进行数据库迁移？
A: 修改 `backend/models.py` 中的模型后，运行 `python scripts/migrate_db.py`。

---

**注意**: 本文档会随着项目发展持续更新，请及时查看最新版本。
