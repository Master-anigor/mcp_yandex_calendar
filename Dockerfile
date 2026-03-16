FROM ubuntu:24.04

ENV PYTHONUNBUFFERED 1

WORKDIR /app

RUN apt-get update
RUN apt-get install -y python3 python3-pip python3-dev libpq-dev
RUN apt-get clean

COPY requirements.txt requirements.txt
RUN pip install --default-timeout=120 --break-system-packages -r requirements.txt

COPY . /app

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

EXPOSE 8088

ENTRYPOINT ["python3", "main.py"]
