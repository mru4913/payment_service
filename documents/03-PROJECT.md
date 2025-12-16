# TG支付机器人项目结构文档

## 1. 项目概述

TG支付机器人是一个基于Telegram Bot API和FastAPI构建的支付服务系统。系统采用前后端分离架构，其中Telegram Bot作为用户交互界面，FastAPI作为后端服务，提供支付处理和数据管理功能。

## 2. 项目目录结构

```
tg-payment-bot/
├── frontend/                    # Telegram Bot - 多机器人架构
│   ├── core/                    # 共享核心组件
│   │   ├── __init__.py
│   │   ├── base_bot.py          # 基础Bot类
│   │   ├── i18n.py              # 国际化工具
│   │   └── utils.py             # 通用工具
│   ├── locales/                 # 多语言支持
│   │   ├── en/messages.json
│   │   └── zh/messages.json
│   ├── payment_bot/             # 支付机器人
│   │   ├── __init__.py
│   │   ├── bot.py               # 主程序
│   │   ├── handlers.py          # 消息处理
│   │   ├── commands.py          # 支付命令
│   │   └── keyboards.py         # 支付键盘
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
│   ├── __init__.py
│   ├── main.py                  # FastAPI应用入口
│   ├── config.py                # 配置管理
│   ├── database.py              # 数据库连接
│   ├── models.py                # 数据模型
│   ├── schemas.py               # 数据验证
│   ├── services.py              # 业务逻辑服务
│   ├── api.py                   # API路由
│   ├── payments/                # 支付集成
│   │   ├── __init__.py
│   │   ├── alipay.py            # 支付宝集成
│   │   ├── wechat.py            # 微信支付集成
│   │   └── callbacks.py         # 支付回调处理
│   └── utils.py                 # 工具函数
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

## 3. 核心模块说明

### 3.1 Frontend (Telegram Bot)

**职责**: 多机器人架构，支持支付、管理等不同功能，提供国际化的用户界面

**主要组件**:
- `payment_bot/`: 支付机器人，处理所有支付相关交互
- `admin_bot/`: 管理机器人，处理管理功能 (可选)
- `core/`: 共享基础组件 (Bot基类、国际化工具等)
- `locales/`: 多语言支持 (中文、英文等)
- `shared/`: 可复用的处理器和中间件

### 3.2 Backend (FastAPI Service)

**职责**: 提供RESTful API，处理业务逻辑，管理数据

**主要文件**:
- `main.py`: FastAPI应用入口，路由注册
- `config.py`: 多环境配置管理
- `database.py`: PostgreSQL连接和会话管理
- `models.py`: SQLAlchemy数据模型定义
- `schemas.py`: Pydantic请求/响应数据验证
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
# 数据库配置
DATABASE_URL=postgresql://user:password@localhost:5432/tg_payment

# Telegram Bot配置
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_WEBHOOK_URL=https://your-domain.com/webhook

# 支付平台配置
ALIPAY_APP_ID=your_alipay_app_id
ALIPAY_PRIVATE_KEY=your_private_key
WECHAT_APP_ID=your_wechat_app_id
WECHAT_MCH_ID=your_merchant_id

# 应用配置
APP_ENV=development
SECRET_KEY=your_secret_key
DEBUG=true
```

## 6. 开发工作流

### 6.1 本地开发

```bash
# 1. 克隆项目
git clone <repository-url>
cd tg-payment-bot

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
# 或单独启动: python -m frontend.payment_bot.bot
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
docker build -f docker/Dockerfile -t tg-payment-bot:latest .

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
- [API.md](docs/API.md) - API接口文档
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) - 部署指南

## 10. 常见问题

### Q: 如何添加新的支付方式？
A: 在 `backend/payments/` 目录下创建新的支付提供商文件，实现统一的接口。

### Q: 如何修改Bot命令？
A: 在 `frontend/commands.py` 中添加新的命令处理函数，并在 `bot.py` 中注册。

### Q: 如何添加新的API接口？
A: 在 `backend/api.py` 中添加新的路由函数，使用Pydantic进行数据验证。

### Q: 如何进行数据库迁移？
A: 修改 `backend/models.py` 中的模型后，运行 `python scripts/migrate_db.py`。

---

**注意**: 本文档会随着项目发展持续更新，请及时查看最新版本。
