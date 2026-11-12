FROM python:3.12-slim
WORKDIR /opt/gallery
COPY pyproject.toml README.md ./
COPY app ./app
COPY web ./web
COPY run.py ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com .
ENV HOST=0.0.0.0 PORT=9999
EXPOSE 9999
CMD ["python", "run.py"]
