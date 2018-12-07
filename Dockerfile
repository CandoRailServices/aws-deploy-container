FROM python:3.6
RUN pip install boto3
RUN mkdir -p /src/app
WORKDIR /src/app
ADD requirements.txt requirements.txt
RUN pip install -r requirements.txt
ADD . .
ENTRYPOINT ["python", "entrypoint.py"]

