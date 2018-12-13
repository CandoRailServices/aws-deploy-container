# Introduction

This repository contains the source for a container image that will deploy ECS
services to AWS from a CodeShip pipeline.

# Usage
To deploy a new ECS service:
```
docker build -t aws-deploy-container .
docker run -it --rm 
       -e AWS_SECRET_ACCESS_KEY 
       -e AWS_ACCESS_KEY_ID 
       -e AWS_DEFAULT_REGION 
       aws-deploy-container deploy ecs\
            --task-definition-family name-of-task-family \
            --ecs-cluster cluster_name \
            --ecs-service-name my_service \
            --ecr-repository-uri 00000000.dkr.ecr.us-west-2.amazonaws.com/myrepository  \
            --ci-commit-id 8af3ej \
            --ci-message "this is a commit message" \
            --ci-branch master \
            --ci-build-number 5 \
            --ci-committer-email jane.doe@domain.com \
            --ci-committer-username jane.doe \
            --ci-commiter-name "Jane Doe"
```

To deploy static content to an S3 bucket and optionally invalidate modified objects in a CloudFront distribution:
```
docker run -it --rm 
       -e AWS_SECRET_ACCESS_KEY 
       -e AWS_ACCESS_KEY_ID 
       -e AWS_DEFAULT_REGION 
       aws-deploy-container deploy s3\
            --source-dir /path/to/local/directory \
            --s3-bucket bucket-name \
            --cloudfront-distribution-id E27WRG54TG \
            --ci-commit-id 8af3ej \
            --ci-message "this is a commit message" \
            --ci-branch master \
            --ci-build-number 5 \
            --ci-committer-email jane.doe@domain.com \
            --ci-committer-username jane.doe \
            --ci-commiter-name "Jane Doe"
```


# How it Works
This assumes that a new image has already been pushed to the ECS Container
Registry as specified in `ecr-repository-uri` with a tag that is the same as
the `ci-commit-id`. It will updated the ECS Task
Definition with the new image name, keeping all other parameters the same.
The new task definition will include tags that correspond to the various CI
variables from the build. 

Once the new task definition has been created, the service specified in
`ecs-service-name` will be updated with the new task definition.


