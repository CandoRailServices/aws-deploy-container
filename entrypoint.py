"""
Provides various command-line utilities for deploying to AWS
"""

import click
import boto3
import os
import mimetypes
from datetime import datetime
import hashlib
import datadog

# Initialize DataDog if envvars exist
dd_api_key = os.environ.get('DD_API_KEY')
dd_app_key = os.environ.get('DD_APP_KEY')
dd_initialized = False

if dd_api_key and dd_app_key:
    options = {
        'api_key': dd_api_key,
        'app_key': dd_app_key
    }

    datadog.initialize(**options)
    dd_initialized = True


class CIBuildMetadata(object):
    def __init__(self, ci_commit_id, ci_message, ci_branch, ci_build_number, ci_committer_email, ci_committer_username, ci_committer_name):
        self.commit_id = ci_commit_id
        self.message = ci_message
        self.branch = ci_branch
        self.build_number = ci_build_number
        self.committer_email = ci_committer_email
        self.committer_username = ci_committer_username
        self.committer_name = ci_committer_name

    def to_tags(self, lowercase_keys=True):
        tags = {
            'CI_COMMIT_ID': self.commit_id,
            'CI_BRANCH': self.branch,
            'CI_BUILD_NUMBER': self.build_number,
            'CI_COMMITTER_EMAIL': self.committer_email,
            'CI_COMMITTER_NAME': self.committer_name,
            'CI_COMMITTER_USERNAME': self.committer_username}
        return unpack_dict(tags, lowercase_keys)

def resolve_envvars(envvar_prefix):
    """Strips the specified prefix from all envvars that match as a method to parameterize the envvars for different configs"""
    for key in os.environ:
        # Any environment variables that start with the branch name, strip of the branch name
        # this provides a parameterization of envvars based on the CI_BRANCH
        if key.upper().replace('-','_').startswith(envvar_prefix.upper().replace('-','_')):
            stripped_envvar_key = key[len(envvar_prefix)+1:]
            os.environ[stripped_envvar_key] = os.getenv(key)

def print_envvars():
    print('Environment variables set: ')
    for a in os.environ:
        if 'SECRET' in a:
            print(a, ': <redacted>')
        else:
            print(a, ': ', os.getenv(a))


@click.group()
@click.option('--envvar-prefix', envvar='ENVVAR_PREFIX', default=os.environ.get('CI_BRANCH'))
def cli(envvar_prefix):
    if envvar_prefix:
        resolve_envvars(envvar_prefix)


@cli.group()
@click.option('--ci-commit-id', required=True, envvar='CI_COMMIT_ID')
@click.option('--ci-message', default='', envvar='CI_COMMIT_MESSAGE')
@click.option('--ci-branch', default='', envvar='CI_BRANCH')
@click.option('--ci-build-number', default='', envvar='CI_BUILD_ID')
@click.option('--ci-committer-email', default='', envvar='CI_COMMITTER_EMAIL')
@click.option('--ci-committer-username', default='', envvar='CI_COMMITTER_USERNAME')
@click.option('--ci-committer-name', default='', envvar='CI_COMMITTER_NAME')
@click.pass_context
def deploy(ctx, **kwargs):
    ctx.obj = CIBuildMetadata(**kwargs)

@deploy.command()
@click.option('--task-definition-family', required=True, envvar='TASK_DEFINITION_FAMILY')
@click.option('--ecs-cluster', required=True, envvar='ECS_CLUSTER')
@click.option('--ecr-repository-uri', required=True, envvar='ECR_REPOSITORY_URI')
@click.option('--ecs-service-name', required=True, envvar='ECS_SERVICE_NAME')
@click.pass_obj
def ecs(build,
        task_definition_family,
        ecs_cluster,
        ecr_repository_uri,
        ecs_service_name):
    session = boto3.session.Session()
    client = session.client('ecs')
    task_definition = register_ecs_task_definition(
        client,
        task_definition_family,
        ecr_repository_uri,
        build)
    print('New task definition created ', task_definition)

    update_ecs_service(client,task_definition,ecs_cluster, ecs_service_name)

@deploy.command()
@click.option('--s3-bucket', required=True, envvar='S3_BUCKET')
@click.option('--source-dir', required=True, default='/artifacts/', envvar='SOURCE_DIR', type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True))
@click.option('--cloudfront-distribution-id', envvar='CLOUDFRONT_DISTRIBUTION_ID')
@click.option('--s3-prefix', default='', envvar='S3_PREFIX')
@click.pass_obj
def s3(build, s3_bucket, source_dir, cloudfront_distribution_id, s3_prefix):
    """Uploads a local directory to S3 and optionally invalidates CloudFront objects"""
    session = boto3.Session()
    client = session.client('s3')

    # Keep track of overwritten files to invalidate in CloudFront
    overwritten_files = []

    for root, dirs, files in os.walk(source_dir):
        for filename in files:

            # construct the full local path
            local_path = os.path.join(root, filename)

            # construct the full Dropbox path
            relative_path = os.path.relpath(local_path, source_dir)
            s3_path = os.path.join(s3_prefix, relative_path)

            # Keep track if we are overwriting an existing file
            try:
                object_metadata = client.head_object(Bucket=s3_bucket, Key=s3_path)

                # Compare md5 contents to see if file is identical, and skip if so
                etag = object_metadata['ETag'][1:-1]
                file_md5 = get_md5(local_path)
                if etag == md5:
                    print ('File %s with identical md5 already exists; skipping' % s3_path)
                    continue

                overwritten_files.append(s3_path)
                print('File %s will be overwritten ' % (s3_path))
            except:
                pass

            content_type, content_encoding = mimetypes.guess_type(local_path)
            print ("Uploading %s ..." % (s3_path))
            client.upload_file(local_path, s3_bucket, s3_path, ExtraArgs={'ContentType': content_type} if content_type else None)
            client.put_object_tagging(Bucket=s3_bucket, Key=s3_path, Tagging={'TagSet': build.to_tags()})

    invalidate_cloudfront(cloudfront_distribution_id, overwritten_files, session)

def invalidate_cloudfront(cloudfront_distribution_id, overwritten_files, session):
    if cloudfront_distribution_id:
        paths_to_invalidate = ['/' + key for key in overwritten_files] # Paths must be prefixed with root `/`
        num_objects_to_invalidate = len(paths_to_invalidate)
        if num_objects_to_invalidate:
            invalidation_caller_reference = datetime.utcnow().isoformat()
            print('Invalidating %s objects in CloudFront distribution %s with caller reference %s' %(num_objects_to_invalidate, cloudfront_distribution_id, invalidation_caller_reference))
            cloudfront_client = session.client('cloudfront')
            cloudfront_client.create_invalidation(DistributionId=cloudfront_distribution_id,
                InvalidationBatch = {
                    'Paths': {
                        'Quantity': len(overwritten_files),
                        'Items':  paths_to_invalidate
                    },
                    'CallerReference': invalidation_caller_reference
                })
        else:
            print('No CloudFront objects to invalidate')

@deploy.command()
@click.option('--function-name', required=True, multiple=True, envvar='FUNCTION_NAME') # Possible to deploy to multiple lambdas simultaneously
@click.option('--path-to-zip', required=True, type=click.Path(exists=True, file_okay=True, dir_okay=False, resolve_path=True), envvar='PATH_TO_ZIP', help='The local filepath of the zip file to upload')
@click.option('--s3-bucket', envvar='S3_BUCKET', help='The path of the S3 bucket to upload the zip file to')
@click.option('--s3-prefix', envvar='S3_PREFIX', default='')
@click.pass_obj
def lambda_func(build, function_name, path_to_zip, s3_bucket, s3_prefix):
    """Uploads a zip package to S3 and updates a lambda function to use the package"""
    session = boto3.Session(profile_name='quasar-preprod')
    s3_client = session.client('s3')

    s3_key = os.path.join(s3_prefix, os.path.basename(path_to_zip) + '.' + build.commit_id)
    s3_client.upload_file(path_to_zip, s3_bucket, s3_key)
    s3_client.put_object_tagging(Bucket=s3_bucket, Key=s3_key, Tagging={'TagSet': build.to_tags()})

    lambda_client = session.client('lambda')

    # Deploy to each function
    for function in function_name:
        lambda_client.update_function_code(FunctionName=function, S3Bucket=s3_bucket, S3Key=s3_key)

def unpack_dict(dict_to_unpack, lowercase_keys):
    # Different AWS APIs use "Key", "Value" or "key", "value"
    key_string = "key" if lowercase_keys else "Key"
    value_string = "value" if lowercase_keys else "Value"
    """Takes a dictionary and returns an array of 'key', 'value' dicts"""
    unpacked_dict = []
    for k,v in dict_to_unpack.items():
        unpacked_dict.append({key_string: k, value_string: v})
    return unpacked_dict

def register_ecs_task_definition(client,
                             task_definition_family,
                             ecr_repository_uri,
                             build: CIBuildMetadata):
    """Registers a new ECS task definition based on an existing one, but updates the image label with the CI_COMMIT_ID"""

    task_definition = client.describe_task_definition(taskDefinition=task_definition_family)['taskDefinition']

    # Remove elements from response that are not to be sent back in updating the task definition
    task_definition_elements_to_remove = ['taskDefinitionArn', 'status', 'compatibilities', 'requiresAttributes', 'revision']
    for k in task_definition_elements_to_remove:
        task_definition.pop(k, None)

    new_image_label = build.commit_id

    new_image = ecr_repository_uri + ':' + new_image_label

    task_definition['containerDefinitions'][0]['image'] = new_image

    task_definition['tags'] = build.to_tags(lowercase_keys=False)

    response = client.register_task_definition(**task_definition)
    new_task_revision = response['taskDefinition']['revision']
    new_task_definition_name = task_definition_family + ':' + str(new_task_revision)
    return new_task_definition_name

def update_ecs_service(client,task_definition, cluster, service):
    """Updates an ECS service with a new task definition. The provided task definition must be name:version"""
    response = client.update_service(cluster=cluster, service=service, taskDefinition=task_definition, forceNewDeployment=True)

# Shortcut to MD5
# borrowed from https://gist.github.com/nateware/4735384
def get_md5(filename):
  f = open(filename, 'rb')
  m = hashlib.md5()
  while True:
    data = f.read(10240)
    if len(data) == 0:
        break
    m.update(data)
  return m.hexdigest()

def post_datadog_event(build_metadata: CIBuildMetadata):
    title = f'CodeShip: Application deployed to '
    source_type_name = 'codeship'
    tags = ['']
    #datadog.api.Event.create(title=title, alert_type=text=text, tags=tags)

if __name__ == '__main__':
    cli()



