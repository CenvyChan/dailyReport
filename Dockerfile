FROM python:3.12-slim

# 时区跟 settings.TIME_ZONE 保持一致，否则邮件的「到点发送」判断会偏 8 小时。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 换国内镜像源：UB 服务器拉境外 Debian/PyPI 源极慢且易断连（56MB 的 fonts-noto-cjk
# 曾因此卡死构建）。Debian 13(trixie)用 DEB822 格式的 .sources 文件，直接改其中的
# URI 到清华镜像；pip 同样指向清华，加速 playwright 等包安装。
RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g; s|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# apt 网络健壮性：限制单次连接超时并自动重试，避免拉大包（如 fonts-noto-cjk）时
# 对端静默断开导致 apt 永久 hang 卡死整个镜像构建。
RUN printf 'Acquire::http::Timeout "30";\nAcquire::https::Timeout "30";\nAcquire::Retries "5";\nAPT::Install-Recommends "false";\n' > /etc/apt/apt.conf.d/99-build-robust

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium 运行所需系统库。老 CPU（Core2，无 avx）实测可正常运行 Chromium 渲染 PDF。
# 字体独立成下一层：即使中文字体源拉取变慢，这一层仍可命中缓存，缩短重建时间。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxcb1 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 中文字体：否则 PDF 中文显示为方块。单独成层便于缓存与网络重试。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
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
