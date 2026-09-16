ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# apt 镜像容错:阿里云为主源,下载失败自动回退清华 TUNA;
# 单条 fetch 重试 5 次 + 30s 超时,避免网络抖动导致整层构建失败
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && export APT_OPTS='-o Acquire::Retries=5 -o Acquire::http::Timeout=30' \
    && (apt-get update $APT_OPTS && apt-get install -y --no-install-recommends gdal-bin libgdal-dev $APT_OPTS) \
    || (sed -i 's|mirrors.aliyun.com|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
        && apt-get update $APT_OPTS \
        && apt-get install -y --no-install-recommends gdal-bin libgdal-dev $APT_OPTS) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
# pip 镜像容错:阿里云 PyPI 为主,失败回退清华 PyPI
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ \
    && pip config set global.trusted-host mirrors.aliyun.com \
    && (pip install --no-cache-dir --timeout 120 --retries 5 . \
        || (pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
            && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
            && pip install --no-cache-dir --timeout 120 --retries 5 .))

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
