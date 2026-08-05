# ---- 阶段 1: 构建虚拟环境 ----
FROM python:3.13-slim AS builder

WORKDIR /app

# 安装依赖到独立目录
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/deps -r requirements.txt

# ---- 阶段 2: 运行镜像 ----
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 复制已安装的依赖
COPY --from=builder /app/deps /usr/local/lib/python3.13/site-packages

# 复制应用代码
COPY app.py database.py models.py seed.py ./
COPY templates/ ./templates/
COPY data.db ./data.db

# 创建数据目录（挂载卷用）
RUN mkdir -p /app/data && chmod 755 /app/data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    DB_PATH=/app/data/data.db \
    TZ=Asia/Shanghai

EXPOSE 5001

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "app.py"]
