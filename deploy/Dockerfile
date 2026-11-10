# 机器人镜像：纯 Python 跨平台，Linux/Windows 通吃
FROM python:3.12-slim

ENV TZ=Asia/Shanghai PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 只拷贝程序所需（Windows 专用脚本不进镜像）
COPY core/ core/
COPY plugins/ plugins/
COPY db/ db/
COPY scripts/healthcheck.py scripts/healthcheck.py
COPY main.py .

CMD ["python", "main.py"]
