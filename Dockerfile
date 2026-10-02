FROM python:3.14-slim AS build
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements-cloud.txt
COPY . .

FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LD_MODE=cloud LD_DATA_ROOT=/var/data PORT=8000
RUN useradd --create-home --uid 10001 ld && mkdir -p /var/data && chown ld:ld /var/data
WORKDIR /app
COPY --from=build /install /usr/local
COPY --from=build /app /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)"
ENTRYPOINT ["python", "container_entrypoint.py"]
CMD ["python", "serve_cloud.py"]
