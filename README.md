# Introduction

This repository contains the source for a container image that will deploy ECS
services to AWS from a CodeShip pipeline.

The built Docker image can be found [here](https://hub.docker.com/r/seandunn/aws-deploy-container/)

# Usage
To deploy a new ECS service:
```
docker build -t aws-deploy-container .
docker run -it --rm 
       -e AWS_SECRET_ACCESS_KEY 
       -e AWS_ACCESS_KEY_ID 
       -e AWS_DEFAULT_REGION 
       aws-deploy-container deploy \
        --ci-commit-id 8af3ej \
        --ci-message "this is a commit message" \
        --ci-branch master \
        --ci-build-number 5 \
        --ci-committer-email jane.doe@domain.com \
        --ci-committer-username jane.doe \
        --ci-commiter-name "Jane Doe" \
       ecs \
        --task-definition-family name-of-task-family \
        --ecs-cluster cluster_name \
        --ecs-service-name my_service \
        --ecr-repository-uri 00000000.dkr.ecr.us-west-2.amazonaws.com/myrepository  \
```

To deploy static content to an S3 bucket and optionally invalidate modified objects in a CloudFront distribution:
```
docker run -it --rm 
       -e AWS_SECRET_ACCESS_KEY 
       -e AWS_ACCESS_KEY_ID 
       -e AWS_DEFAULT_REGION 
       aws-deploy-container deploy \
        --ci-commit-id 8af3ej \
        --ci-message "this is a commit message" \
        --ci-branch master \
        --ci-build-number 5 \
        --ci-committer-email jane.doe@domain.com \
        --ci-committer-username jane.doe \
        --ci-commiter-name "Jane Doe" \
       s3\
        --source-dir /path/to/local/directory \
        --s3-bucket bucket-name \
        --cloudfront-distribution-id E27WRG54TG
```

# Environment Variables 
Most command line arguments can be also passed into the container as environment variables. The script will automatically resolve any environment variables that begin with the same value as `$CI_BRANCH`. I.e. when built with `CI_BRANCH=master` the environment variable `master_AWS_ACCESS_KEY_ID` will become `AWS_ACCESS_KEY_ID` prior to any further processing, and overriding any previous value in `AWS_ACCESS_KEY_ID`. Matching the branch name and environment variable keys is case insensitive and treates dashes/underscores as equivalent.

# How it Works
This assumes that a new image has already been pushed to the ECS Container
Registry as specified in `ecr-repository-uri` with a tag that is the same as
the `ci-commit-id`. It will updated the ECS Task
Definition with the new image name, keeping all other parameters the same.
The new task definition will include tags that correspond to the various CI
variables from the build. 

Once the new task definition has been created, the service specified in
`ecs-service-name` will be updated with the new task definition.

# Codeship Configuration
For Codeship 

`codeship-services.yaml`: 
```
app:
  build:
    dockerfile_path: Dockerfile
  cached: true
  volumes:
    - ./artifacts:/artifacts

awsdeployhelper:
  image: seandunn/aws-deploy-container:latest
  env_file: aws-deployment.env
  encrypted_env_file: deployment-creds.env.encrypted
  cached: true
  volumes:
    - ./artifacts:/artifacts
```

`codeship-steps.yaml`:
```
- name: COPY_STATIC_SITE_FILES
  service: app
  command: cp -r -v /src/dist/. /artifacts/

- name: AWS_DEPLOY_TO_S3
  service: awsdeployhelper
  tag: ^(dev|prod)
  command: deploy s3 --source-dir=/artifacts
```

`aws-deployment.env`
```
AWS_DEFAULT_REGION=us-west-2

# dev
dev_S3_BUCKET=dev-bucket-name
dev_CLOUDFRONT_DISTRIBUTION_ID=dev-cf-dist-id

# prod
prod_S3_BUCKET=prod-bucket-name
prod_CLOUDFRONT_DISTRIBUTION_ID=prod-cf-dist-id
```

