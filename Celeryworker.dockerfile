FROM python:3.12

WORKDIR /routing
COPY routing ./
RUN python -m compileall .
RUN pip install --no-cache-dir .

WORKDIR /www
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /www
COPY Routing_Api ./
RUN python -m compileall .

ENV PYTHONUNBUFFERED=1
ENV IS_CELERY_APP yes

ENTRYPOINT ["celery", "-A", "Routing_Api", "worker", "-l", "INFO"]