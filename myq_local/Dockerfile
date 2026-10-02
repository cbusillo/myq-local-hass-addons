FROM python:3.14.7-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv
WORKDIR /app
COPY src/ /app/src/
COPY requirements.txt /app/requirements.txt
RUN uv pip install --system --no-cache --require-hashes -r /app/requirements.txt
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "-m", "myq_local"]
