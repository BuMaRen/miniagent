FROM python:3.12-slim

WORKDIR /app

# 先只拷贝依赖清单,依赖没变时能命中 layer 缓存,不用每次改代码都重新装包
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/site/runs \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# site/server.py 默认监听 0.0.0.0:8000(局域网/容器网络可访问),
# 用 docker run -p 8000:8000 把端口映射出来即可。
CMD ["python", "site/server.py"]
