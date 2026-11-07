FROM docker.io/astral/uv:python3.13-trixie-slim
LABEL maintainer="Computer Science House <webmaster@csh.rit.edu>"

WORKDIR /opt/chronically-slacktive-helper
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt
COPY run.py .
ADD app app

CMD ["python", "run.py"]
