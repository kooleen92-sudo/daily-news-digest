# 每日财经与中国深度简报（海外五大权威外媒）

每天早上 08:00 准时自动抓取**彭博社 (Bloomberg)、路透社 (Reuters)、华尔街日报 (WSJ)、金融时报 (FT)、联合早报 (Zaobao)**最新财经消息与中国大陆要闻，利用 AI 深度剖析其对**中国宏观经济、A股/港股/中概股、离岸人民币汇率、核心产业与企业**的影响，并以精美响应式 HTML + Markdown 附件形式推送到你的个人邮箱。

---

## 🌟 核心特色

1. **精准覆盖五大国际权威信源**：
   - **彭博社 (Bloomberg)**：全球市场行情、大宗商品、央行流动性与中国宏观。
   - **路透社 (Reuters)**：全球经济动向、跨国企业资本运作、突发财经。
   - **华尔街日报 (WSJ)**：深度商业调查、中美经贸博弈、宏观风险报道。
   - **金融时报 (FT)**：全球资本市场、地缘政治与外媒前瞻观点（含 FT 中文网权威翻译）。
   - **联合早报 (Zaobao)**：立足亚洲视角的中国大陆政经与高层政策第一手分析报道。
2. **深度影响剖析（不仅仅是新闻摘要）**：
   - **今日核心研判（Executive Summary）**：直击本质的 3~5 条宏观研判。
   - **资产与市场影响速查矩阵**：以表格清晰梳理 A股/港股、离岸人民币汇率、中概科技、大宗商品、国债收益率的利好/利空/震荡倾向与驱动逻辑。
   - **各家外媒逐条深度分析**：提炼客观事实 + 剖析对中国经济/产业/政策传导机制 + 附原文可点击链接。
3. **高可用双轨兜底设计**：
   - 配置 `OPENAI_API_KEY`（支持 DeepSeek / OpenAI / Qwen 等）时，输出万字级资深宏观分析报告。
   - 未配置或 API 超时，自动启用**精美结构化新闻列表兜底**，确保定时任务 100% 准时送达。
4. **精美邮件排版**：
   - 专为手机与桌面邮箱适配的响应式 Newsletter 模板，带有五大媒体专属辨识色标。
   - 正文附带渲染好的排版表格，同时附带 `.md` 文件附件便于 Obsidian / 知识库归档。
5. **灵活调度方式**：
   - **Windows 计划任务**：一键注册系统级后台任务，无需每天开着命令行黑窗口。
   - **Python 常驻守护进程**：直接 `python main.py --schedule` 运行。
   - **Docker / 服务器部署**：提供 Dockerfile 与 docker-compose，方便一键搬到云服务器。

---

## 🚀 快速开始

### 1. 配置环境（填写 `.env`）

在本项目根目录下，复制或编辑 `.env` 文件：

```bash
# 复制模板（如果已有 .env 则直接编辑）
cp .env.example .env
```

打开 `.env` 填写以下内容：

```ini
# 1. 定时任务时间（默认每天早上 08:00）
DIGEST_TIME=08:00
DIGEST_TIMEZONE=Asia/Shanghai

# 2. 接收邮箱
MAIL_TO=你的邮箱@qq.com

# 3. 发件 SMTP 配置（以 QQ 邮箱为例）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_USER=你的QQ号@qq.com
SMTP_PASSWORD=你的QQ邮箱授权码  # 网页版 QQ 邮箱 -> 设置 -> 账户 -> 生成授权码
MAIL_FROM=你的QQ号@qq.com

# 4. AI 影响分析配置（推荐性价比极高的 DeepSeek，也支持 OpenAI / 任意兼容接口）
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

> **常见邮箱 SMTP 设置说明：**
> - **QQ 邮箱**：服务器 `smtp.qq.com`，端口 `465`，开启 SSL。密码必须是网页端「设置 - 账户 - POP3/IMAP」生成的 16 位授权码，不是 QQ 登录密码。
> - **163 网易邮箱**：服务器 `smtp.163.com`，端口 `465`，开启 SSL，密码为客户端授权密码。
> - **Gmail**：服务器 `smtp.gmail.com`，端口 `587`，开启 TLS，密码使用 Google 账户「安全性 - 应用专用密码」。

---

### 2. 常用操作命令

进入项目目录 `d:\code\mess\dailyNews`：

#### ① 测试五大外媒连接性与新闻拉取
```bash
python main.py --test-sources
```
*检查彭博社、路透社、华尔街日报、金融时报、联合早报是否可正常抓取最新新闻条目。*

#### ② 本地执行预览（不发邮件）
```bash
python main.py --dry-run
```
*拉取最新新闻并生成报告，自动在 `output/` 目录下生成 `digest_YYYYMMDD.html` 与 `digest_YYYYMMDD.md`。可用浏览器打开 HTML 查看精美排版。*

#### ③ 测试邮件配置与连通性
```bash
python main.py --test-mail
```
*验证 SMTP 账号密码是否正确，并向目标邮箱发送一封测试验证邮件。*

#### ④ 立即执行一次并推送邮件
```bash
python main.py --run-now
```

---

## ⏰ 定时任务部署指南（每天早上 08:00）

### 方案 A：Windows 原生计划任务（推荐 Windows 用户）

无需保持黑窗口常开，由 Windows 系统在每天早上 08:00 准时后台静默调用：

1. **一键注册计划任务**：
   以普通或管理员身份打开 PowerShell，执行：
   ```powershell
   cd d:\code\mess\dailyNews
   powershell -ExecutionPolicy Bypass -File .\setup_windows_task.ps1
   ```
2. **测试计划任务**：
   ```powershell
   schtasks.exe /run /tn "DailyNewsFinanceDigest8AM"
   ```
3. **查看运行日志**：
   任务每次执行日志将自动写入 `d:\code\mess\dailyNews\logs\runner.log`。
4. **如需取消/删除计划任务**：
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\remove_windows_task.ps1
   ```

---

### 方案 B：后台常驻守护进程（跨平台）

直接启动内置轻量调度器，进程在后台等待，每天早上 08:00 自动触发：

```bash
python main.py --schedule
```

---

### 方案 C：Docker 服务器部署（Ubuntu / CentOS / 云主机）

若你将代码推送到 Linux VPS 或 NAS 上：

```bash
# 1. 确保服务器安装了 Docker 和 Docker Compose
# 2. 将代码目录复制到服务器
# 3. 配置 .env
# 4. 启动容器
docker compose up -d --build

# 5. 查看运行日志
docker compose logs -f
```

---

## 📁 目录结构说明

```
dailyNews/
├── main.py                 # 主入口（支持 CLI 各类参数调度）
├── collector.py            # 五大外媒（彭博、路透、WSJ、FT、早报）抓取与去重
├── analyzer.py             # 财经与宏观影响深度剖析大模型 Prompt 与逻辑
├── mailer.py               # 响应式 HTML 邮件渲染与 SMTP 发送器
├── config.py               # 环境变量与应用配置加载
├── run_digest.bat          # Windows 计划任务调用的启动脚本
├── setup_windows_task.ps1  # 一键注册 Windows 08:00 计划任务脚本
├── remove_windows_task.ps1 # 一键卸载 Windows 计划任务脚本
├── .env.example            # 配置说明与模板样例
├── .env                    # 当前运行配置（请填入邮箱与密钥）
├── requirements.txt        # Python 依赖清单
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker 编排配置
├── output/                 # 历史生成的 HTML / Markdown 预览文件归档
└── logs/                   # 执行运行日志
```
