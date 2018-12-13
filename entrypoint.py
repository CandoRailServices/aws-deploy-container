"""
Provides various command-line utilities for depolying to AWS
"""

import click
import boto3
import os
import mimetypes
from datetime import datetime

ci_branch = os.environ.get('CI_BRANCH')

def get_envvars_for_current_branch():
    for a in os.environ:
        # Any environment variables that start with the branch name, strip of the branch name
        # this provides a parameterization of envvars based on the CI_BRANCH
        if ci_branch and a.upper().replace('-','_').startswith(ci_branch.upper().replace('-','_')):
            stripped_envvar_key = a[len(ci_branch)+1:]
            os.environ[stripped_envvar_key] = os.getenv(a)

def print_envvars():
    print('Environment variables set: ')
    for a in os.environ:
        if 'SECRET' in a:
            print(a, ': <redacted>')
        else:
            print(a, ': ', os.getenv(a))


@click.group()
def cli():
    pass

class CIBuildMetadata(object):
    def __init__(self, ci_commit_id, ci_message, ci_branch, ci_build_number, ci_committer_email, ci_committer_username, ci_committer_name):
        self.commit_id = ci_commit_id
        self.message = ci_message
        self.branch = ci_branch
        self.build_number = ci_build_number
        self.committer_email = ci_committer_email
        self.committer_username = ci_committer_username
        self.committer_name = ci_committer_name
    
    def to_tags(self):
        tags = {
            'CI_COMMIT_ID': self.commit_id,
            'CI_MESSAGE': self.message,
            'CI_BRANCH': self.branch,
            'CI_BUILD_NUMBER': self.build_number,
            'CI_COMMITTER_EMAIL': self.committer_email,
            'CI_COMMITTER_NAME': self.committer_name,
            'CI_COMMITTER_USERNAME': self.committer_username}
        return unpack_dict(tags)

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
@click.option('--source-dir', required=True, default='/tmp/dist/', envvar='SOURCE_DIR', type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True))
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
                client.head_object(Bucket=s3_bucket, Key=s3_path)
                overwritten_files.append(s3_path)
                print('File %s will be overwritten ' % s3_path)
            except:
                pass

            content_type, content_encoding = mimetypes.guess_type(local_path)
            print ("Uploading %s ..." % (s3_path))
            client.upload_file(local_path, s3_bucket, s3_path, ExtraArgs={'ContentType': content_type})
            client.put_object_tagging(Bucket=s3_bucket, Key=s3_path, Tagging={'TagSet': build.to_tags()})
    
    if cloudfront_distribution_id:
        num_objects_to_invalidate = len(overwritten_files)
        invalidation_caller_reference = datetime.utcnow().isoformat()
        print('Invalidating %s objects in CloudFront distribution %s with caller reference %s' %(num_objects_to_invalidate, cloudfront_distribution_id, invalidation_caller_reference))
        cloudfront_client = session.client('cloudfront')
        cloudfront_client.create_invalidation(DistributionId=cloudfront_distribution_id,
            InvalidationBatch = {
                'Paths': {
                    'Quantity': len(overwritten_files),
                    'Items': ['/' + key for key in overwritten_files] # Paths must be prefixed with root `/`
                },
                'CallerReference': invalidation_caller_reference
            })

@deploy.command()
@click.option('--function-name', required=True, multiple=True) # Possible to deploy to multiple lambdas simultaneously
@click.pass_obj
def lambda_func(build, function_name, path_to_zip):
    raise NotImplementedError('Deploying lambdas not yet implemented')


def unpack_dict(dict_to_unpack):
    """Takes a dictionary and returns an array of 'key', 'value' dicts"""
    unpacked_dict = []
    for k,v in dict_to_unpack.items():
        unpacked_dict.append({'Key': k, 'Value': v})
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

    task_definition['tags'] = build.to_tags()

    response = client.register_task_definition(**task_definition)
    new_task_revision = response['taskDefinition']['revision']
    new_task_definition_name = task_definition_family + ':' + str(new_task_revision)
    return new_task_definition_name

def update_ecs_service(client,task_definition, cluster, service):
    """Updates an ECS service with a new task definition. The provided task definition must be name:version"""
    response = client.update_service(cluster=cluster, service=service, taskDefinition=task_definition)

if __name__ == '__main__':
    get_envvars_for_current_branch()
    print_envvars()
    cli()



