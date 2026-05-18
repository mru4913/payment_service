# Eshow（易修）

基于 Telegram Bot API 与 FastAPI 的支付与算力服务：美元基准、多支付方式，Bot 与 API 分离部署。

## ✨ 主要特性

- 💰 **多支付方式支持**: 集成支付宝、微信支付等多种主流支付方式
- 🌍 **美元基准设计**: 所有金额以美元为统一货币单位，确保财务数据一致性
- 🤖 **多机器人架构**: 支持支付、管理等多个独立机器人实例
- 🌐 **国际化支持**: 内置多语言支持 (中文、英文等)
- 🔒 **安全合规**: 符合PCI DSS标准的企业级安全保障
- ⚡ **高性能**: 支持100+并发用户，响应时间<3秒
- 🐳 **容器化部署**: 完整的Docker支持，易于部署和扩展

## 🛠️ 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| **编程语言** | Python 3.12+ | 现代Python版本 |
| **Web框架** | FastAPI | 高性能异步Web框架 |
| **Bot框架** | python-telegram-bot | Telegram官方Bot框架 |
| **数据库** | PostgreSQL 18+ | 强大的关系型数据库 |
| **ORM** | SQLAlchemy 2.0+ | 现代Python ORM |
| **项目管理** | uv | 快速的Python包管理器 |
| **容器化** | Docker & Docker Compose | 现代化部署方案 |

## 📁 项目结构

```
eshow/   # 仓库克隆目录名以实际为准
├── frontend/          # 🤖 Telegram Bot - 多机器人架构
│   ├── bot/             # Telegram 机器人（支付 + 算力对话等）
│   ├── integrations/  # Bot 调 FastAPI 的 HTTP 客户端（无直连 DB）
│   ├── admin_bot/     # 管理机器人 (可选)
│   ├── core/          # 共享核心组件
│   ├── locales/       # 🌍 多语言支持
│   └── shared/        # 共享组件
├── backend/           # 🚀 FastAPI后端服务
│   ├── main.py        # 应用入口
│   ├── config.py      # 配置管理
│   ├── database.py    # 数据库连接
│   ├── models.py      # 数据模型
│   ├── services.py    # 业务逻辑
│   ├── api.py         # RESTful API
│   └── payments/      # 支付集成
├── scripts/           # 🔧 部署和维护脚本
├── tests/             # 🧪 测试代码
├── docker/            # 🐳 容器化配置
└── docs/              # 📚 项目文档
```

Telegram Bot（`frontend/`）不直连数据库：业务经 `BACKEND_BASE_URL` 调用 FastAPI，持久化与支付逻辑在 `backend/` 完成。可选执行 `./scripts/check_frontend_zero_db.sh` 确认未误引入 `backend` 包。

## 🚀 快速开始

### 环境要求
- Python 3.12+
- PostgreSQL 18+
- Docker & Docker Compose (推荐)

### 安装和运行

```bash
# 1. 克隆项目
git clone <repository-url>
cd eshow   # 若目录名不同请改为你的克隆路径

# 2. 创建虚拟环境 (使用uv)
uv venv --python 3.12
source .venv/bin/activate

# 3. 安装依赖
uv sync

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置数据库和API密钥

# 5. 初始化数据库
python scripts/setup_db.py

# 6. 运行后端服务
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 7. 运行Telegram Bot (新终端)
python frontend/runner.py
```

### Docker 开发环境

```bash
# 使用Docker Compose启动完整开发环境
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f backend
```

## 📋 核心功能

- ✅ **支付处理**: 支持美元金额输入，自动转换为本地货币支付
- ✅ **余额管理**: 用户余额实时查询和管理
- ✅ **交易记录**: 完整的支付历史和交易追踪
- ✅ **多语言界面**: 支持中文、英文等语言切换
- ✅ **安全验证**: 支付回调签名验证和风险控制
- ✅ **管理员功能**: 交易监控、用户管理和系统统计

## 🏗️ 系统架构

系统采用前后端分离架构：

- **Frontend**: Telegram Bot作为用户交互界面，支持多机器人实例
- **Backend**: FastAPI提供RESTful API和业务逻辑处理
- **Database**: PostgreSQL存储用户数据、交易记录和系统配置
- **Payments**: 集成支付宝、微信等第三方支付平台

## 📚 相关文档

- **[产品需求文档](documents/01-PRD.md)** - 详细的产品功能和业务需求
- **[系统架构文档](documents/02-ARCHITECTURE.md)** - 完整的技术架构设计
- **[项目结构文档](documents/03-PROJECT.md)** - 详细的项目组织和开发指南

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目！

## 📄 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

---

**注意**: 这是一个支付相关项目，请确保遵守相关法律法规和支付平台的使用条款。
