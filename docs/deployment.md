# 内网部署

1. 安装 Python 3.12，创建虚拟环境并安装依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

2. 设置环境变量：复制 `.env.example` 为 `.env`，填写随机 `DJANGO_SECRET_KEY`、`DJANGO_ALLOWED_HOSTS` 和受控备份目录；生产环境设置 `DJANGO_DEBUG=False`。

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

5. 备份：每天计划任务运行：

```powershell
python scripts/backup_sqlite.py --target D:\daily-report-backups
```

脚本使用 SQLite 在线备份，不直接复制使用中的数据库文件。恢复前停止服务，保留当前数据库副本，再将备份文件替换为 `data/daily_report.sqlite3` 并运行 `python manage.py check`。
