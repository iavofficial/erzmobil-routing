FROM python:3.12

WORKDIR /routing
COPY routing ./
RUN python -m compileall .
RUN pip install --no-cache-dir .
RUN apt update
RUN apt install -y iputils-ping

WORKDIR /www
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /log-storage-routing

WORKDIR /maps
COPY maps .

WORKDIR /www
COPY Routing_Api ./
RUN python -m compileall .

ENV PYTHONUNBUFFERED=1

# default timeout of 30 sec may be too low
ENTRYPOINT ["gunicorn", "Routing_Api.wsgi", "--bind", "0.0.0.0:8080", "-k", "gevent", "--timeout", "180"]
