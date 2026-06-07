# Mail2Bark 开发文档

本文档给后续开发人员使用，说明项目结构、核心流程、测试方式和扩展点。

## 技术栈

- Python 3.9+
- 标准库 IMAP 客户端 `imaplib`
- `PyYAML` 读取配置
- SQLite 保存去重状态
- Docker Compose 部署
- Bark V2 REST API 推送
- 可选 OpenAI-compatible LLM API

## 项目结构

```text
mail_bark_forwarder/
  __main__.py      # python -m mail_bark_forwarder 入口
  cli.py           # CLI 参数解析
  config.py        # config.yaml 和 .env 加载
  service.py       # 主服务流程和多账号 worker
  imap_client.py   # IMAP 连接、搜索、拉取、IDLE、邮件后处理
  parser.py        # MIME 解析、HTML 转文本、验证码和链接提取
  bark.py          # Bark V2 API 请求
  llm.py           # LLM 分类和链接裁决
  state.py         # SQLite 去重状态
tests/
  test_*.py        # 单元测试
```

## 核心流程

服务启动：

```text
cli.main
  -> load_config
  -> ForwarderService
  -> run_once 或 run_forever
```

长期运行：

```text
run_forever
  -> install_signal_handlers
  -> startup_mark_seen 时标记现有邮件为已处理
  -> 每个账号启动一个 worker 线程
  -> worker 循环 process_account
```

单个账号处理：

```text
process_account
  -> ImapClient.connect
  -> fetch_new
  -> process_mail
  -> wait_for_change
```

单封邮件处理：

```text
process_mail
  -> parse_mail
  -> StateStore.is_processed
  -> classify_mail
  -> BarkClient.push
  -> StateStore.mark_processed
  -> client.apply_post_action
```

## 配置加载

入口：

```python
mail_bark_forwarder.config.load_config
```

配置文件：

- `config.yaml`：结构化配置。
- `.env`：敏感值。

支持 `${ENV_NAME}` 环境变量展开。

账号配置使用 `MailAccount`：

```yaml
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

## IMAP 客户端

文件：

```text
mail_bark_forwarder/imap_client.py
```

职责：

- 建立 IMAP SSL 或普通连接。
- 登录邮箱。
- 选择 mailbox。
- 按 UID 搜索和拉取邮件。
- 尝试 IMAP IDLE；失败时回退到定时等待。
- 推送成功后执行 `post_action`。

搜索条件：

```python
criteria = [account.search]
if account.since_days > 0:
    criteria.extend(["SINCE", "..."])
```

注意：

- `SINCE` 是 IMAP 日期过滤，精度按天。
- `search: ALL` 会扫描更多邮件，必须依赖 SQLite 去重。
- `search: UNSEEN` 只处理未读邮件，但如果邮箱客户端自动标记已读，可能漏处理。

## 解析策略

文件：

```text
mail_bark_forwarder/parser.py
```

职责：

- 解析 `text/plain`。
- 解析 `text/html` 并转成文本。
- 从多段 MIME 中合并正文。
- 提取验证码。
- 提取 URL 候选。
- 格式化 Bark body。

验证码策略：

- 匹配 4-8 位数字或字母数字。
- 优先带有上下文关键词的片段：
  - `验证码`
  - `code`
  - `verification`
  - `OTP`
  - `login`
  - `token`

链接策略：

- 先提取 HTTP/HTTPS URL。
- 对重复链接去重。
- 优先动作类链接：
  - `verify`
  - `verification`
  - `confirm`
  - `activate`
  - `login`
  - `reset`
  - `auth`
  - `invite`

## LLM 分类

文件：

```text
mail_bark_forwarder/llm.py
```

LLM 只在配置开启时使用：

```yaml
llm:
  enabled: true
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
```

设计原则：

- 规则能明确提取验证码时，优先规则。
- 多链接或低置信度链接邮件，交给 LLM 判断。
- LLM 只能从 `url_candidates` 中选择链接。
- LLM 返回的验证码必须存在于邮件原文。
- LLM 返回无效内容时不推送，避免误推广告或无关链接。

返回 schema：

```json
{
  "should_push": true,
  "kind": "code | link | code_and_link | none",
  "code": "string|null",
  "url": "string|null",
  "reason": "short string"
}
```

## Bark 推送

文件：

```text
mail_bark_forwarder/bark.py
```

推送规则：

- 标题不显示收件邮箱。
- 标题使用发件人显示名。
- 验证码 body 只显示关键值。
- 链接邮件 body 只显示 `点击通知打开链接`。
- 验证码设置 `copy` 字段。
- 链接设置 `url` 字段。

示例：

```text
验证码 - Changjie Shi
验证码：0333771
```

```text
验证链接 - Changjie Shi
点击通知打开链接
```

## 状态库

文件：

```text
mail_bark_forwarder/state.py
```

数据库：

```text
/data/state.sqlite3
```

记录维度：

- account name
- UID
- Message-ID
- processed_at

处理顺序：

1. 拉取邮件。
2. 解析 Message-ID。
3. 查询是否已处理。
4. 未处理才进行分类和推送。
5. 推送后写入状态库。

## 开发环境

创建虚拟环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

运行一次：

```bash
python -m mail_bark_forwarder --once --config config.yaml
```

长期运行：

```bash
python -m mail_bark_forwarder --config config.yaml
```

## 测试

运行完整测试：

```bash
.venv/bin/python -m unittest discover -s tests
```

当前测试覆盖：

- text/plain 邮件解析。
- HTML 邮件解析。
- 多段 MIME 邮件解析。
- 中文验证码。
- 英文 OTP / code。
- 验证链接和密码重置链接。
- 无验证码/链接时不推送。
- UID / Message-ID 去重。
- Bark 请求字段。
- IMAP 搜索条件。
- 邮件后处理动作。
- LLM 结果校验。

## Docker 本地验证

检查 Compose 配置：

```bash
docker compose config
```

构建并启动：

```bash
docker compose up -d --build
```

看日志：

```bash
docker compose logs -f mail2bark
```

停止：

```bash
docker compose down
```

## 添加新邮箱

在 `.env` 增加：

```env
MAIL_WORK_USER=you@example.com
MAIL_WORK_PASSWORD=邮箱授权码
```

在 `config.yaml` 的 `accounts` 增加：

```yaml
  - name: work
    host: imap.example.com
    port: 993
    username: ${MAIL_WORK_USER}
    password: ${MAIL_WORK_PASSWORD}
    auth: password
    mailbox: INBOX
    ssl: true
    idle: true
    search: ALL
    since_days: 3
    post_action: mark_seen
```

重启：

```bash
docker compose restart
```

## 修改解析规则

优先修改：

```text
mail_bark_forwarder/parser.py
```

修改后补测试：

```text
tests/test_parser.py
```

建议新增真实邮件的最小文本样本，不要把完整敏感邮件写进测试。

## 修改 LLM 判断

优先修改：

```text
mail_bark_forwarder/llm.py
```

重点保持两个约束：

- 不允许 LLM 编造链接。
- 不允许 LLM 返回邮件原文不存在的验证码。

修改后补测试：

```text
tests/test_llm.py
```

## 修改 Bark 格式

优先修改：

```text
mail_bark_forwarder/service.py
mail_bark_forwarder/bark.py
mail_bark_forwarder/parser.py
```

相关测试：

```text
tests/test_bark.py
tests/test_service.py
```

## 安全注意事项

- 不要把 `.env` 提交到 Git。
- 不要在日志中打印 Bark key、邮箱授权码、LLM API key。
- 测试样本不要包含真实 token、真实验证码、真实邮箱授权码。
- 服务器上的 `.env` 建议权限为 `600`。

## 已知限制

- 当前主要支持 IMAP 用户名 + 授权码/应用专用密码。
- LLM 判断依赖外部 API 可用性；不可用时会保守跳过低置信度链接邮件。
- Bark 的剪贴板复制能力取决于 Bark iOS 客户端支持和系统权限。
- `IMAP IDLE` 不保证所有邮箱长期稳定，服务会在失败时回退轮询。
