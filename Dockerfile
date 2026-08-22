FROM python:3.12-slim

# 时区跟 settings.TIME_ZONE 保持一致，否则邮件的「到点发送」判断会偏 8 小时。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 静态文件在构建期收集，运行期不需要写权限。
# 这一步只读 settings，不连数据库，所以给个占位 key 就够。
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

# SQLite 和备份都落在卷上，容器重建不丢数据；logs 需在容器内可写。
# chown 必须放在 collectstatic 之后，否则 staticfiles/ 归 root。
RUN mkdir -p data backups logs \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python scripts/run_waitress.py"]
