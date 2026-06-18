# ☁️ OCI Monitor - 甲骨文云监控指挥中心

自托管的甲骨文云监控服务，部署在本地 NAS 上，通过 Webhook 实时告警通知。

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📊 **实例监控** | CPU、内存、磁盘、网络等资源使用率实时监控 |
| 💰 **账单监控** | 预算使用情况、花费变动检测、$0 持续监控 |
| 🔄 **状态变更** | 实例启动/停止/删除实时通知 |
| 🆓 **免费套餐检查** | ARM/AMD 实例配置是否超出 Always Free 限制 |
| 👤 **多账号支持** | 一个面板管理多个 OCI 账号 |
| 🔔 **Webhook 通知** | 支持企业微信、飞书、钉钉、Slack 及任意自定义接口 |
| 🔐 **登录鉴权** | 用户名密码登录保护，防止未授权访问面板 |
| 🖥️ **3D 指挥中心** | 科幻风格 Web 面板，鼠标跟随 3D 倾斜效果 |
| ⚙️ **在线设置** | 前端直接调整监控间隔、告警阈值、通知开关 |
| 🐳 **Docker 一键部署** | 从 Docker Hub 拉取即用 |

---

## 🚀 快速开始

### 方式一：Docker Hub 拉取

```bash
# 1. 创建项目目录
mkdir -p ~/oci-monitor/config ~/oci-monitor/data
cd ~/oci-monitor

# 2. 下载 compose 文件
curl -O https://raw.githubusercontent.com/serenalee87/OCI-Monitor/main/docker-compose.hub.yml
mv docker-compose.hub.yml docker-compose.yml

# 3. 编辑 docker-compose.yml，修改用户名密码
nano docker-compose.yml

# 4. 放入 OCI API 私钥
cp /path/to/your/oci_api_key.pem config/oci_api_key.pem
chmod 600 config/oci_api_key.pem

# 5. 启动
docker-compose up -d
```

### 方式二：本地构建

```bash
git clone https://github.com/serenalee87/OCI-Monitor.git
cd oci-monitor

# 放入私钥，修改 compose 中的用户名密码
mkdir -p config && cp /path/to/key.pem config/oci_api_key.pem

# 构建并启动
docker-compose up -d --build
```

---

### 📋 docker-compose.yml（推荐）

```yaml
services:
  oci-monitor:
    image: serenalee/oci-monitor:latest
    container_name: oci-monitor
    restart: unless-stopped
    ports:
      - "8199:8199"
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    environment:
      - TZ=Asia/Shanghai
      - WEB_USERNAME=admin
      - WEB_PASSWORD=changeme
```

启动后访问 `http://<NAS-IP>:8199`，首次登录面板即可配置 OCI 认证、Webhook、监控参数等。


---

## 📋 OCI API Key 配置指南

### 第一步：登录 OCI 控制台

打开 https://cloud.oracle.com 登录。

### 第二步：生成 API Key

1. 点击右上角 **头像** → **User Settings**
2. 左侧菜单 → **API Keys**
3. 点击 **Add API Key** → **Generate API key pair**
4. 下载私钥文件（.pem）
5. 点击 **Add** 确认

### 第三步：记录配置信息

从配置示例中提取，填入 `docker-compose.yml` 的 `environment`：

| 字段 | 环境变量 | 说明 |
|------|-----------|------|
| user | `OCI_USER_OCID` | ocid1.user.oc1.. |
| fingerprint | `OCI_FINGERPRINT` | aa:bb:cc:dd:... |
| tenancy | `OCI_TENANCY_OCID` | ocid1.tenancy.oc1.. |
| region | `OCI_REGION` | ap-osaka-1 等 |
| key_file | `OCI_KEY_FILE` | 默认 /app/config/oci_api_key.pem，无需修改 |

### 第四步：确认 Region

| Region | 代码 |
|--------|------|
| 大阪 | ap-osaka-1 |
| 东京 | ap-tokyo-1 |
| 首尔 | ap-seoul-1 |
| 新加坡 | ap-singapore-1 |
| 上海 | ap-shanghai-1 |
| 圣何塞 | us-sanjose-1 |
| 阿什本 | us-ashburn-1 |
| 法兰克福 | eu-frankfurt-1 |

---

## 🔔 Webhook 配置

### 企业微信机器人

```yaml
- WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY
- WEBHOOK_TYPE=wecom
```

### 飞书机器人

```yaml
- WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_HOOK_ID
- WEBHOOK_TYPE=feishu
```

### 钉钉机器人

```yaml
- WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN
- WEBHOOK_TYPE=dingtalk
```

### 自定义 Webhook

```yaml
- WEBHOOK_URL=https://your-endpoint.com/alert
- WEBHOOK_TYPE=custom
```

发送格式：

```json
{
  "title": "告警标题",
  "content": "告警内容",
  "timestamp": "2024-01-01T00:00:00Z",
  "data": { ... }
}
```

---

## 🔐 登录鉴权

在 `docker-compose.yml` 的 `environment` 中配置用户名和密码即可启用登录保护：

```yaml
environment:
  - TZ=Asia/Shanghai
  - WEB_USERNAME=admin
  - WEB_PASSWORD=your_secure_password_here
```

### 配置说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `WEB_USERNAME` | ✅ | 登录用户名 |
| `WEB_PASSWORD` | ✅ | 登录密码 |
| `SECRET_KEY` | ❌ | 会话签名密钥，留空则自动生成 |

### 行为

- **未配置**（`WEB_USERNAME` 或 `WEB_PASSWORD` 为空）→ 面板完全开放，无需登录，与现有行为一致
- **已配置** → 所有页面和 API 接口均受保护，未登录访问会跳转到登录页
- 会话有效期 7 天，Cookie 为 HttpOnly，支持退出登录
- API 接口未认证时返回 `401 Unauthorized` JSON

### 建议

- 使用强密码，避免使用默认或简单密码
- 如通过 HTTPS 反向代理（Nginx/Caddy）访问，将 `secure=False` 改为 `True`
- `SECRET_KEY` 建议设置为随机字符串以增强会话安全性

---

## 📊 监控策略

### 自动监控

| 检查项 | 默认间隔 | 触发通知 |
|--------|----------|----------|
| 实例状态检查 | 10 分钟 | 状态变更时 |
| 资源用量监控 | 10 分钟 | CPU/内存/磁盘超阈值 |
| 账单/费用检查 | 1 小时 | **检测到任何非零花费** |
| 免费套餐合规 | 随实例检查 | 仅面板展示（不推送） |

### 告警阈值

| 指标 | 默认阈值 | 说明 |
|------|----------|------|
| CPU | 85% | 运行中实例 CPU 使用率 |
| 内存 | 90% | 运行中实例内存使用率 |
| 磁盘 | 85% | 运行中实例磁盘使用率 |
| 费用 | $0.00 | Always Free 用户任何花费 |

### 去重机制

- 同一条告警只记录一次，不会重复推送
- 费用告警例外：每次花费变动都会通知

---

## 👤 多账号管理

### 通过 Web 面板添加

1. 点击右上角 **👤 按钮**
2. 点击 **+ ADD ACCOUNT**
3. 填入 Tenancy OCID、User OCID、Fingerprint、Region、私钥路径
4. 确认添加

### 通过 docker-compose 配置（单账号）

在 `docker-compose.yml` 的 `environment` 中填入 OCI 认证信息即可，面板会自动使用。

**优先级**：面板添加的账号 > docker-compose 默认配置

---

## ⚙️ 在线设置

点击右上角 **⚙️ 按钮**，可直接在面板调整：

- 检查间隔（秒）
- 告警阈值（%）
- 通知开关

修改后**立即生效**，无需重建容器。

---

## 🖥️ 面板功能

| 区域 | 说明 |
|------|------|
| 顶部状态栏 | OCI 连接状态、Webhook 状态、账号/设置入口 |
| SYSTEM STATUS | 标题 + SCANNING 扫描动画 |
| 统计卡片 | 总实例、活跃、停止、告警数（鼠标 3D 倾斜） |
| 操作按钮 | 手动触发检查、测试 Webhook |
| 免费套餐 | ARM/AMD 资源用量 vs 限制，超标 tooltip |
| 实例列表 | 所有实例状态、规格、账号归属 |
| 告警历史 | 最近告警记录 |
| 账单 | 当前总花费、预算明细 |
| 状态变更 | 实例状态变更历史 |
| 定时任务 | 调度器运行状态、下次执行时间 |

---

## 📁 项目结构

```
oci-monitor/
├── docker-compose.yml          # Docker Compose 配置（所有配置在此）
├── docker-compose.hub.yml      # Docker Hub 版 compose
├── Dockerfile                  # 镜像构建文件
├── requirements.txt            # Python 依赖
├── README.md                   # 本文件
│
├── config/
│   └── oci_api_key.pem         # OCI API 私钥（需放入）
│
├── data/
│   └── monitor.db              # SQLite 数据库（自动创建）
│
└── app/
    ├── __init__.py
    ├── main.py                 # FastAPI 入口
    ├── config.py               # 配置加载
    ├── oci_client.py           # OCI SDK 封装
    ├── database.py             # 数据库操作 + 多账号管理
    ├── notifier.py             # Webhook 通知
    ├── scheduler.py            # 定时任务调度
    │
    ├── monitors/
    │   ├── __init__.py
    │   ├── instance_monitor.py     # 实例监控
    │   ├── billing_monitor.py      # 账单/费用监控
    │   └── freetier_monitor.py     # 免费套餐合规检查
    │
    └── templates/
        └── dashboard.html          # 3D 风格 Web 面板
```

---

## 🔧 API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 面板 |
| `/api/instances` | GET | 实例列表 |
| `/api/alerts` | GET | 告警历史 |
| `/api/budgets` | GET | 预算信息 |
| `/api/accounts` | GET | 账号列表 |
| `/api/accounts` | POST | 添加账号 |
| `/api/accounts/{id}` | DELETE | 删除账号 |
| `/api/check/instances` | POST | 手动触发实例检查 |
| `/api/check/billing` | POST | 手动触发账单检查 |
| `/api/check/free-tier` | POST | 手动触发套餐检查 |
| `/api/test-webhook` | POST | 发送测试通知 |
| `/api/free-tier` | GET | 免费套餐合规数据 |
| `/api/config` | GET | 当前配置 |
| `/api/settings` | POST | 更新设置 |

---

## 🐛 常见问题

### Q: 容器启动后 500 错误

检查数据库迁移：

```bash
docker logs oci-monitor
```

首次启动会自动迁移旧数据库，添加 `account_id` 等新列。

### Q: OCI 连接失败

1. 确认 `docker-compose.yml` 中 OCI 认证信息填写正确
2. 确认私钥文件已放入 `config/` 目录
3. 确认 `OCI_KEY_FILE` 路径与私钥实际路径一致

### Q: 不产生费用告警

这是正常的！Always Free 用户花费应该是 $0。只有当 OCI 政策变化导致产生费用时才会告警。

### Q: 免费套餐显示超标

这是预期行为——ARM 实例是 4 OCPU/24 GB（老配置），新限制是 2 OCPU/12 GB。系统仅展示信息，不会自动降配。

---

## 📜 License

MIT

---
