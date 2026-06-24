FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置时区（供日志使用）
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY main.py .

# 暴露 8000 端口
EXPOSE 8000

# 启动高并发的 Uvicorn ASGI 服务器
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]