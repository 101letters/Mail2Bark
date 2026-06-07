# Mail2Bark 部署文档

本文档给部署和运维人员使用，覆盖当前 Docker 部署方案。

## 服务说明

Mail2Bark 是一个后台服务，用 IMAP 读取邮箱新邮件，提取验证码、登录令牌、验证链接、确认链接等关键信息，并推送到 Bark。

当前部署策略：

- 使用 Docker Compose 长期运行。
- 默认只处理最近 3 天内邮件。
- 只有识别到验证码或验证链接时才推送 Bark。
- 推送成功后默认把邮件标记为已读。
- SQLite 状态库持久化保存，服务重启后不会重复推送已处理邮件。
- LLM 可选开启，用于多链接邮件和广告/动作邮件判断。

## 服务器目录

推荐部署目录：

```bash
/opt/Mail2Bark
```

目录结构：

```text
/opt/Mail2Bark/
  .env
  config.yaml
  docker-compose.yml
  Dockerfile
  mail_bark_forwarder/
  data/
```

重要文件：

- `.env`：敏感配置，包含 Bark key、邮箱账号授权码、LLM API key。
- `config.yaml`：服务配置，包含邮箱 IMAP 地址、轮询间隔、推送策略。
- `data/state.sqlite3`：去重状态库，不要随意删除。

## 安装 Docker

如果服务器还没有 Docker：

```bash
curl -fsSL https://get.docker.com | sh
docker version
docker compose version
```

如果 Docker Hub 拉镜像慢，可以把 Dockerfile 第一行改成国内镜像：

```dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim
```

## 首次部署

上传项目后进入目录：

```bash
cd /opt/Mail2Bark
```

创建配置：

```bash
cp config.example.yaml config.yaml
cp .env.example .env
mkdir -p data
chmod 600 .env
```

编辑 `.env`：

```env
BARK_SERVER=https://api.day.app
BARK_DEVICE_KEY=你的 Bark device key

MAIL_PERSONAL_USER=邮箱地址
MAIL_PERSONAL_PASSWORD=邮箱授权码或应用专用密码

LLM_BASE_URL=https://api-inference.modelscope.cn/v1
LLM_API_KEY=你的 ModelScope API key
LLM_MODEL=Qwen/Qwen3.5-35B-A3B
```

编辑 `config.yaml`，QQ 邮箱示例：

```yaml
poll_interval: 30
since_days: 3
state_path: /data/state.sqlite3
startup_mark_seen: true
post_action: mark_seen
log_level: INFO

bark:
  server: ${BARK_SERVER}
  device_key: ${BARK_DEVICE_KEY}
  group: mail-code

llm:
  enabled: true
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
  timeout: 30
  max_text_chars: 6000

accounts:
  - name: qq
    host: imap.qq.com
    port: 993
    username: ${MAIL_PERSONAL_USER}
    password: ${MAIL_PERSONAL_PASSWORD}
    auth: password
    mailbox: INBOX
    ssl: true
    idle: true
    search: ALL
    since_days: 3
    post_action: mark_seen
```

启动：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f mail2bark
```

正常日志应包含：

```text
starting Mail2Bark for 1 accounts
startup marked current matching mail as processed: qq
account worker started: qq
```

## 日常运维

查看容器：

```bash
cd /opt/Mail2Bark
docker compose ps
```

查看实时日志：

```bash
docker compose logs -f mail2bark
```

重启服务：

```bash
docker compose restart
```

停止服务：

```bash
docker compose down
```

更新代码后重建：

```bash
docker compose up -d --build
```

检查 Compose 配置：

```bash
docker compose config
```

## 配置修改

修改 `.env` 或 `config.yaml` 后需要重启：

```bash
docker compose restart
```

如果修改了代码、Dockerfile 或依赖：

```bash
docker compose up -d --build
```

## 状态库说明

状态库位置：

```bash
/opt/Mail2Bark/data/state.sqlite3
```

它记录每个邮箱已经处理过的 UID / Message-ID，避免重复推送。

不要随意删除 `data/state.sqlite3`。删除后服务可能重新扫描符合条件的旧邮件。

## 邮件处理策略

关键配置：

- `since_days: 3`：只读取最近 3 天邮件。
- `startup_mark_seen: true`：首次启动时把当前匹配邮件标记为已处理，避免历史邮件刷屏。
- `search: ALL`：扫描最近 3 天所有邮件，由 SQLite 去重。
- `post_action: mark_seen`：成功推送后标记已读，不删除邮件。

可选 `post_action`：

- `mark_seen`：标记已读。
- `delete`：删除邮件。
- `move`：移动到 `move_to` 指定文件夹。
- `none`：不处理邮件状态。

## Bark 推送格式

验证码邮件：

```text
标题：验证码 - 发件人显示名
内容：验证码：123456
copy：123456
```

验证链接邮件：

```text
标题：验证链接 - 发件人显示名
内容：点击通知打开链接
url：验证链接
```

同时包含验证码和链接：

```text
标题：验证码/验证链接 - 发件人显示名
内容：验证码：123456
      点击通知打开链接
copy：123456
url：验证链接
```

## 常见问题

### 没收到 Bark 推送

检查：

```bash
docker compose logs -f mail2bark
```

重点看：

- 是否能连接 IMAP。
- 是否有 `no code/link signal`。
- 是否有 Bark API 请求错误。
- `.env` 中 `BARK_DEVICE_KEY` 是否正确。

### 新邮件没有被推送

确认邮件是否在最近 3 天内，并且内容确实包含验证码或验证链接。

也可以临时调高日志：

```yaml
log_level: DEBUG
```

然后重启：

```bash
docker compose restart
```

### 首次启动没有推送旧邮件

这是预期行为。`startup_mark_seen: true` 会把启动时已有的匹配邮件标记为已处理，避免历史邮件刷屏。后续新邮件才会继续推送。

### Docker Hub 拉镜像失败

可把 Dockerfile 第一行改为：

```dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim
```
