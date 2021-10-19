FROM python:3.8-slim

ENV PYTHONUNBUFFERED=1

RUN mkdir /app
WORKDIR /app

ARG version=develop
ENV VERSION="${version}"

# first copy requirements, readme and license file
COPY requirements.txt /app/

# install requirements
RUN pip install --no-cache-dir -r requirements.txt

# now copy the source code
COPY . /app

EXPOSE 8000

WORKDIR /app

ENV MYSUPERMON_USERNAME=

ENV MYSUPERMON_PASSWORD=

ENV MYSUPERMON_ENDPOINT=

ENV KEPTN_ENDPOINT=

ENV KEPTN_API_TOKEN=

CMD ["python", "main.py"]