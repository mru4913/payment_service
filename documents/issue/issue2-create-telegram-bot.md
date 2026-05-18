## Issue-02: 实现 Telegram Bot 交互层（支付机器人 + 多语言支持）

### 1. 需求分析

#### 功能点清单
- [ ] **Bot 核心框架**: 基于 python-telegram-bot 的异步 Bot 基类和启动器
- [ ] **用户注册/欢迎**: `/start` 命令，自动注册用户到数据库
- [ ] **充值流程**: `/recharge` 命令，创建 TRC20 USDT 充值订单，返回收款地址和精确金额
- [ ] **余额查询**: `/balance` 命令，查询当前余额和累计充值/消费
- [ ] **充值记录**: `/history` 命令，查看最近的充值和交易记录
- [ ] **帮助信息**: `/help` 命令，展示所有可用命令
- [ ] **Inline Keyboard 交互**: 充值金额选择、支付方式选择、确认操作
- [ ] **多语言支持**: 繁体中文、简体中文、英文，用户可切换语言
- [ ] **到账通知**: TRC20 Monitor 到账后推送充值成功消息（已有基础）
- [ ] **错误处理**: 统一的错误提示和异常捕获

#### 用户交互流程
```
用户 /start
  → 欢迎消息 + 语言选择按钮
  → 注册/更新用户信息到数据库

用户 /recharge
  → 展示金额选择键盘 (10/20/50/100 USDT 或自定义)
  → 用户选择金额
  → 创建 TRC20 USDT 订单（唯一金额）
  → 返回收款地址 + 精确转账金额 + 二维码(可选)
  → 提示"请在30分钟内完成转账"

用户 /balance
  → 显示当前余额、累计充值、累计消费

用户 /history
  → 分页展示最近交易记录

用户 /lang
  → 切换语言（繁体中文/简体中文/英文）
```

#### 边界情况
- 用户连续发送多条充值请求（应提示有未完成订单）
- 用户发送无效金额（非数字、负数、过小/过大）
- Bot Token 未配置时的优雅降级
- Telegram API 限流处理
- 用户在充值等待期间查询状态
- 未注册用户直接使用其他命令

#### 依赖模块
- **python-telegram-bot**: Bot 框架（已在 pyproject.toml）
- **httpx**: HTTP 客户端（已安装）
- **backend API**: 通过内部 Service 层调用，不走 HTTP
- **TRC20 Monitor**: 到账通知（已实现）

### 2. 目录结构设计

```
frontend/
├── __init__.py
├── core/                        # 共享核心组件
│   ├── __init__.py
│   ├── base_bot.py              # Bot 基类（初始化、错误处理、日志）
│   ├── i18n.py                  # 国际化工具（加载/切换语言）
│   └── utils.py                 # 通用工具（格式化金额、分页等）
├── locales/                     # 多语言资源
│   ├── zh_hans/                 # 简体中文
│   │   └── messages.json
│   ├── zh_hant/                 # 繁体中文
│   │   └── messages.json
│   └── en/                      # 英文
│       └── messages.json
├── frontend/bot/                # Telegram 机器人（支付 + 算力等）
│   ├── __init__.py
│   ├── bot.py                   # Bot 主程序（Application 创建和启动）
│   ├── handlers/                # 按功能分组的 Handler
│   │   ├── __init__.py
│   │   ├── start.py             # /start, /help 命令
│   │   ├── recharge.py          # /recharge 充值流程（含 Callback 处理）
│   │   ├── balance.py           # /balance 余额查询
│   │   ├── history.py           # /history 交易记录
│   │   └── language.py          # /lang 语言切换
│   └── keyboards.py             # 所有 InlineKeyboard 定义
├── shared/                      # 共享组件
│   ├── __init__.py
│   ├── error_handler.py         # 全局错误处理
│   └── middleware.py            # Bot 中间件（日志、限流）
└── runner.py                    # Bot 启动入口
```

### 3. 多语言设计

#### 3.1 支持语言
| 语言代码 | 名称 | 说明 |
|---------|------|------|
| `zh_hans` | 简体中文 | 默认语言 |
| `zh_hant` | 繁体中文 | |
| `en` | English | |

#### 3.2 语言文件结构 (messages.json 示例)

```json
{
  "welcome": {
    "greeting": "👋 欢迎使用支付机器人！",
    "registered": "您的账户已创建成功。",
    "returning": "欢迎回来，{name}！"
  },
  "recharge": {
    "select_amount": "请选择充值金额（USDT）：",
    "custom_amount": "自定义金额",
    "confirm": "请向以下地址转账 **{amount} USDT**：",
    "address": "收款地址（TRC20）：",
    "timeout_warning": "⏰ 请在 {minutes} 分钟内完成转账",
    "pending_exists": "您有一笔未完成的充值订单，请先完成或等待超时。",
    "success": "✅ 充值成功！{amount} USDT 已到账。",
    "cancelled": "❌ 充值订单已超时取消。",
    "invalid_amount": "请输入有效的金额（最小 1 USDT）。"
  },
  "balance": {
    "title": "💰 账户信息",
    "current": "当前余额：{balance} USD",
    "total_deposit": "累计充值：{deposits} USD",
    "total_withdraw": "累计消费：{withdrawals} USD"
  },
  "history": {
    "title": "📋 交易记录",
    "empty": "暂无交易记录。",
    "entry": "{type} | {amount} USD | {time}",
    "page": "第 {current}/{total} 页",
    "no_more": "没有更多记录了。"
  },
  "language": {
    "select": "请选择语言 / Please select language：",
    "changed": "语言已切换为：{lang}"
  },
  "common": {
    "error": "❌ 操作失败，请稍后重试。",
    "help": "📖 可用命令：\n/start - 开始使用\n/recharge - 充值\n/balance - 查询余额\n/history - 交易记录\n/lang - 切换语言\n/help - 帮助信息",
    "unknown": "未知命令，请输入 /help 查看帮助。"
  }
}
```

#### 3.3 i18n 实现方案
```python
class I18n:
    """国际化工具"""
    def __init__(self, locales_dir: str, default_lang: str = "zh_hans"):
        ...

    def t(self, key: str, lang: str = None, **kwargs) -> str:
        """获取翻译文本，支持参数插值"""
        # key 格式: "recharge.confirm"
        # kwargs: amount=10.003700
        ...
```

用户语言偏好存储在 `User.preferences` JSONB 字段中（已有该字段）。

### 4. 技术方案

#### 4.1 Bot 与 Backend 的集成方式

Bot 和 FastAPI 运行在**同一进程**中，Bot handler 直接通过 `async_session_maker` 创建数据库会话，调用 Service 层，**不走 HTTP API**：

```python
# handler 中直接调用 Service
async def handle_recharge(update, context):
    async with async_session_maker() as session:
        svc = PaymentService(session)
        payment = await svc.create_payment(...)
```

#### 4.2 Bot 启动方式

在 FastAPI lifespan 中同时启动 Bot（polling 模式）：

```python
# backend/main.py lifespan 中
bot_app = create_bot_application()
asyncio.create_task(bot_app.run_polling())
```

或者独立进程启动（`frontend/runner.py`），通过环境变量控制。

#### 4.3 Inline Keyboard 设计

充值流程使用 `InlineKeyboardMarkup`：
- 第一步：金额选择 `[10] [20] [50] [100] [自定义]`
- 第二步：显示收款信息 + `[查询状态] [取消订单]`
- Callback data 格式：`recharge:amount:10`, `recharge:cancel:{payment_id}`

### 5. 创建 TODO

按依赖顺序排列：

1. ⬜ **创建 frontend 基础结构** - `__init__.py`、`core/`、`shared/`
2. ⬜ **实现 i18n 国际化模块** - `core/i18n.py` + 三语言 messages.json
3. ⬜ **实现 Bot 基类** - `core/base_bot.py`（初始化、错误处理）
4. ⬜ **实现通用工具** - `core/utils.py`（金额格式化、分页）
5. ⬜ **实现 /start 和 /help** - `handlers/start.py`
6. ⬜ **实现 /recharge 充值流程** - `handlers/recharge.py` + `keyboards.py`
7. ⬜ **实现 /balance 余额查询** - `handlers/balance.py`
8. ⬜ **实现 /history 交易记录** - `handlers/history.py`
9. ⬜ **实现 /lang 语言切换** - `handlers/language.py`
10. ⬜ **实现全局错误处理** - `shared/error_handler.py`
11. ⬜ **实现 Bot 主程序和启动器** - `frontend/bot/bot.py` + 启动入口（见仓库实际结构）
12. ⬜ **集成到 FastAPI lifespan** - 修改 `backend/main.py`
13. ⬜ **端到端测试** - 本地 Bot 测试所有命令

### 6. 验收标准

- [ ] `/start` 正确注册用户并展示欢迎消息
- [ ] `/recharge 10` 创建订单并返回收款地址和唯一金额
- [ ] `/balance` 正确显示余额信息
- [ ] `/history` 分页展示交易记录
- [ ] `/lang` 切换语言后所有消息使用新语言
- [ ] 三种语言（简中/繁中/英文）消息完整无遗漏
- [ ] TRC20 到账后用户收到通知（使用对应语言）
- [ ] 错误情况有友好的提示信息
- [ ] 有未完成充值订单时提示用户

### 7. 风险和注意事项

- **Bot polling vs webhook**: 开发阶段用 polling，生产切 webhook
- **并发安全**: handler 中每次请求创建独立的 db session
- **Telegram 限流**: sendMessage 限制 ~30 msg/s，需注意批量通知场景
- **语言回退**: 翻译 key 缺失时回退到简体中文
- **用户隐私**: 不在日志中记录用户消息内容

---

**状态**: ⬜ 待开始
**优先级**: P0 - 最高
**预计工作量**: 中等
**前置依赖**: Issue-01 (Backend) ✅ 已完成
