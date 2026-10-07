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

# Chromium 运行所需系统库 + 中文字体（fonts-noto-cjk，否则 PDF 中文显示为方块）。
# 老 CPU（Core2，无 avx）实测可正常运行 Chromium 渲染 PDF。
# 字体包名随 Debian 版本变化，这里显式列出已验证可用的依赖，避免 install-deps 因
# 过时字体包（ttf-unifont 等）报错中断。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxcb1 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Chromium 二进制装到全局路径，让运行期的 app 用户也能访问（默认装到 ~/.cache，
# 会随 USER 切换而找不到）。不带 --with-deps，系统库已由上一步显式安装。
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN python -m playwright install chromium \
    && chmod -R a+rX /opt/pw-browsers

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
