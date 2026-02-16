FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# install yandex cloud cli
RUN curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash -s -- -i /usr/local/bin
ENV PATH="/usr/local/bin/bin:$PATH"
RUN apt-get update && apt-get install -y ca-certificates

COPY . .
