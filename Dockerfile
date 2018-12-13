FROM python:3.7-alpine
RUN pip install boto3
RUN mkdir -p /artifacts
WORKDIR /src/app
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt
ADD . .
VOLUME ["/artifacts"]
ENTRYPOINT ["python", "entrypoint.py"]

