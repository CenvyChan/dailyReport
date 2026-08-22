# 部署

两种方式二选一：[Docker 部署](#docker-部署)（推荐，环境一致）或[直接在 Windows 上跑](#内网部署直接运行)。

## Docker 部署

1. 复制 `.env.example` 为 `.env`，至少填写 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS` 和邮件相关变量。**通过 IP 或域名访问时必须填 `DJANGO_CSRF_TRUSTED_ORIGINS`**（例如 `http://192.168.1.10:8000`），否则登录、切换公司等 POST 会被 CSRF 拦下。

2. 构建并启动：

```bash
docker compose up -d --build
```

`web` 容器启动时自动执行 `migrate`，然后用 waitress 监听 8000 端口。`mailer` 容器复用同一镜像，每 10 分钟跑一次 `send_daily_report`，替代 Windows 计划任务。

3. 创建管理员：

```bash
docker compose exec web python manage.py createsuperuser
```

4. 注意事项：

- 数据库是 SQLite，`./data`、`./backups` 和 `./logs` 已挂成卷；**不要删卷**，否则数据全丢。两个容器共享同一个库文件，靠 WAL 模式并发（`core/signals.py` 里已开启）。
- 容器内以非 root 用户（uid 10001）运行。在 Linux 宿主上如果挂载目录属于别的用户，会因为没有写权限导致 `attempt to write a readonly database`，先执行 `sudo chown -R 10001:10001 data backups logs`。Docker Desktop for Windows/macOS 不受此影响。
- 容器时区固定为 `Asia/Shanghai`，与 `settings.TIME_ZONE` 一致；否则邮件的「到点发送」判断会偏 8 小时。
- 静态文件在镜像构建期 `collectstatic`，改了 `static/` 下的文件要重新 build。
- 备份由 `backup` 容器自动执行：启动 60 秒后备一次，之后每 24 小时一次，保留最近 30 份，日志写 `logs/backup.log`。手工立刻备一份：`docker compose exec web python scripts/backup_sqlite.py`（不带参数就落到 `BACKUP_DIRECTORY`）。
- 应用日志在 `logs/app.log`，发信日志在 `logs/mail.log`，均按天轮转保留 30 天。

## 内网部署（直接运行）

1. 安装 Python 3.12，创建虚拟环境并安装依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

2. 设置环境变量：复制 `.env.example` 为 `.env`，填写随机 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS` 和受控备份目录；生产环境设置 `DJANGO_DEBUG=False`。通过 IP 或域名访问时补上 `DJANGO_CSRF_TRUSTED_ORIGINS`。

3. 初始化数据库：

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

4. 启动内网服务：

```powershell
python scripts/run_waitress.py
```

Windows 将该命令注册为系统服务，Linux 使用 systemd 或 supervisor 守护。默认地址为 `http://<内网服务器>:8000/`。

5. 备份：注册计划任务每天跑一次（脚本会自动轮转，只保留最近 30 份）：

```powershell
schtasks /create /tn "DailyReportBackup" /tr "E:\DEV\dailyReport\scripts\backup_daily.bat" /sc daily /st 23:30 /ru SYSTEM
```

也可以直接手工备一份：

```powershell
python scripts/backup_sqlite.py            # 落到 .env 里的 BACKUP_DIRECTORY
python scripts/backup_sqlite.py --keep 14  # 只保留最近 14 份
```

脚本使用 SQLite 在线备份，不直接复制使用中的数据库文件，运行中执行也安全；备份完会跑 `PRAGMA integrity_check`，校验不过就非零退出。

**恢复步骤**（务必先演练一次，别等真出事才第一次用）：停止服务 → 把当前数据库另存一份 → 将备份文件复制成 `data/daily_report.sqlite3` → 运行 `python manage.py check` 和 `python manage.py migrate --check` 确认结构一致 → 启动服务后登录抽查几笔当天数据。

## 多公司数据隔离

`migrate` 会自动预置 A、B 两家公司，并把升级前已有的客户、供应商、汇率、销售和采购日报全部挂到排序最靠前的那家（默认「A 公司」），同时给所有已有账号授予这家公司的访问权限。升级后需要在后台按实际情况调整：

1. 「基础管理 → 公司」维护公司代码和名称，代码会用在导出文件名和邮件附件名上。
2. 「基础管理 → 用户公司授权」决定每个账号登录时能选哪几家公司。用户、角色、密码在两家公司之间共用，只有业务数据隔离。
3. 客户、供应商、汇率、日报都带公司字段。同名客户可以在两家公司各存一份，同一月份也可以维护两套不同汇率。
4. 登录页必须选择公司；登录后导航栏可以切换（只有被授权多家公司的账号才会看到切换控件）。切换后所有列表、报表、导出、导入都跟着切换。

原有数据如果实际属于 B 公司，升级后在后台把对应记录的公司字段改过去即可，历史金额和汇率快照不受影响。

## 历史数据导入与导出

导入一律「先预览、再正式导入」：预览只校验不写库，有任何错误行都不允许提交。所有导入都写入**当前登录选择的公司**，切换公司重新导入不会互相覆盖。每个导入页面都有「下载导入模板」按钮，模板里带表头、两行示例和一个「填写说明」工作表（说明单独一个 sheet，不会被当成数据读）。`.xls` 和 `.xlsx` 都能上传。

| 导入 | 页面 | 工作表与字段 |
|---|---|---|
| 客户 | `/core/customers/imports/` | 单表：客户名称（兼容「名称」） |
| 供应商 | `/core/suppliers/imports/` | 单表：供应商名称（兼容「供应商」「名称」） |
| 用户 | `/core/users/imports/` | 单表：用户名、姓名、角色、初始密码 |
| 销售历史 | `/sales/imports/` | 「数据表」：客户名称、业务跟单、销售类型、出货日期、数量、金额；「汇率」：日期、汇率 |
| 采购历史 | `/purchase/imports/` | 首个工作表：供应商、采购员、采购类型、采购日期、数量、金额（兼容销售样表的列名） |

导入的行为要点：

- 销售/采购导入会按「业务跟单」「采购员」列的用户名自动建号、加对应角色、并**授予当前公司的访问权限**；客户/供应商也会自动在当前公司下建档并建立归属关系。如果列里写的是另一家公司已有的用户名，那个账号会同时获得这家公司的访问权限，导入前请核对名单。
- 销售导入的「汇率」表会一并写入当前公司的月度汇率。采购导入没有汇率表，**国外采购必须先在 `/core/rates/` 维护好对应月份的汇率**，否则预览会报「缺少该月份美元兑人民币汇率」。
- 角色列只接受：管理员、销售、采购、报表查看者。销售类型只接受内销、外销；采购类型只接受国内采购、国外采购。
- 已存在的用户名不会被覆盖，会在预览里报错；同名客户/供应商不会重复创建。
- 导入全过程写操作日志，每行记录来源文件和来源行号，可在「操作日志」里回溯。

导出：销售报表和采购报表页面各有「导出 Excel」，导出的是**当前公司**且当前筛选条件下的明细，文件名带公司代码（如 `sales-report-A.xlsx`）。邮件推送的附件是当日明细，销售、采购分两个工作表。

## 每日邮件推送（阿里云企业邮箱）

1. 在 `.env` 里填写发信配置。阿里云要求 `EMAIL_HOST_USER` 和 `DEFAULT_FROM_EMAIL` 是同一个已开通 SMTP 的邮箱地址，密码是邮箱密码（若开启了客户端专用密码则填专用密码）：

```
EMAIL_HOST=smtp.qiye.aliyun.com
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_USE_TLS=False
EMAIL_HOST_USER=report@yourdomain.com
EMAIL_HOST_PASSWORD=******
DEFAULT_FROM_EMAIL=report@yourdomain.com
```

465 端口走 SSL。若内网只放通 587，改成 `EMAIL_PORT=587`、`EMAIL_USE_SSL=False`、`EMAIL_USE_TLS=True`。个人版邮箱主机名是 `smtp.aliyun.com`。

2. 用管理员登录，进入「邮件推送」，按公司分别新建收件组：填写收件人（逗号或换行分隔）、推送内容（销售/采购/两者）、每日发送时间、是否附带 Excel 明细。每家公司要各建一个收件组，一个收件组只会发本公司的数据。

3. 注册计划任务，每 10 分钟触发一次，命令内部判断是否到点、当天是否已发过：

```powershell
schtasks /create /tn "DailyReportMail" /tr "E:\DEV\dailyReport\scripts\send_daily_report.bat" /sc minute /mo 10 /ru SYSTEM
```

4. 手工发送和排查：

```powershell
python manage.py send_daily_report --dry-run --now      # 只列出将要发送的收件组
python manage.py send_daily_report --now                # 忽略发送时间立即发送
python manage.py send_daily_report --company A --now    # 只发 A 公司
python manage.py send_daily_report --date 2026-08-20 --force   # 补发指定日期
python manage.py send_daily_report --now --allow-empty  # 当天没数据也发
```

邮件正文含当日、本月累计、本年累计三档汇总（人民币、美元原币金额与折算人民币合计分列），以及当日明细表格；附件是当日明细的 Excel。当天没有任何数据时默认跳过不发。每次发送成败都会写入「邮件发送记录」，同一收件组同一天成功发送后不会重复发送，除非加 `--force`。页面上的「立即发送」按钮走同一条发送路径，可用于试发。
