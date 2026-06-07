# Mail2Bark

把多个 IMAP 邮箱里的验证码、OTP、验证链接、登录链接等关键信息提取出来，并推送到 Bark。

首版特性：

- 多邮箱 IMAP 接入，默认监听 `UNSEEN` 邮件
- 支持 `text/plain`、`text/html` 和多段 MIME 邮件
- 提取 4-8 位验证码和常见验证/登录/重置链接
- Bark V2 `POST /push` 推送，点通知可直接打开验证链接
- SQLite 去重，重启后不重复推送已处理邮件
- 支持源码运行和 Docker Compose 部署

## 快速开始

复制配置：

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

编辑 `.env`，填入 Bark key 和邮箱账号。多数邮箱需要使用“应用专用密码”或邮箱授权码，不要直接使用网页登录密码。

测试跑一次：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m mail_bark_forwarder --once --config config.yaml
```

长期运行：

```bash
python -m mail_bark_forwarder --config config.yaml
```

## Docker 部署

```bash
cp config.example.yaml config.yaml
cp .env.example .env
mkdir -p data
docker compose up -d
docker compose logs -f
```

`docker-compose.yml` 会挂载：

- `./config.yaml` 到 `/app/config.yaml`
- `./data` 到 `/data`，保存 SQLite 状态库

## 配置说明

```yaml
poll_interval: 30
since_days: 3
state_path: /data/state.sqlite3
startup_mark_seen: true
post_action: mark_seen

bark:
  server: ${BARK_SERVER}
  device_key: ${BARK_DEVICE_KEY}
  group: mail-code

llm:
  enabled: false
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}

accounts:
  - name: personal
    host: imap.example.com
    port: 993
    username: ${MAIL_PERSONAL_USER}
    password: ${MAIL_PERSONAL_PASSWORD}
    auth: password
    mailbox: INBOX
    ssl: true
    idle: true
    search: UNSEEN
    since_days: 3
    post_action: mark_seen
```

字段要点：

- `startup_mark_seen: true`：首次启动时会把当前匹配到的邮件标记为已处理，避免历史邮件刷屏。首次测试时可以改成 `false`。
- `search: UNSEEN`：只处理未读邮件。也可以改成 `ALL`，但去重状态库会承担更多工作。
- `since_days: 3`：只读取最近 3 天内的邮件，避免历史未读邮件被扫描。
- `post_action`：成功推送后的邮件处理方式。`mark_seen` 标记已读，`delete` 删除，`move` 移动到 `move_to` 指定文件夹，`none` 不处理。
- `auth`：默认 `password`，使用 IMAP 用户名和授权码/应用专用密码。
- `llm.enabled`：开启后会用 OpenAI-compatible API 对多链接/低置信度邮件做裁决；LLM 只能从邮件候选 URL 中选择，不能编造链接。
- `idle: true`：优先尝试 IMAP IDLE；服务器或 Python imaplib 不兼容时自动回退到轮询。
- `bark.server`：官方 Bark 是 `https://api.day.app`，自建 Bark server 填你的服务地址。

## 常见 IMAP 地址

- Outlook/Hotmail：`outlook.office365.com:993`。如果账号禁止授权码/应用专用密码登录则无法使用。
- QQ 邮箱：`imap.qq.com:993`，通常需要开启 IMAP 并使用授权码。
- 163 邮箱：`imap.163.com:993`，通常需要开启 IMAP 并使用授权码。

## systemd 示例

假设项目放在 `/opt/mail2bark`：

```ini
[Unit]
Description=Mail2Bark
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/mail2bark
EnvironmentFile=/opt/mail2bark/.env
ExecStart=/opt/mail2bark/.venv/bin/python -m mail_bark_forwarder --config /opt/mail2bark/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 开发测试

```bash
python -m unittest discover -s tests
```

如果需要检查 Docker Compose 配置：

```bash
docker compose config
```
