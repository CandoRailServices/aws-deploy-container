import click
import boto3
import os

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

def unpack_dict(dict_to_unpack):
    unpacked_dict = []
    for k,v in dict_to_unpack.items():
        unpacked_dict.append({'key': k, 'value': v})
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

    tags = {
        'CI_COMMIT_ID': build.commit_id,
        'CI_MESSAGE': build.mesage,
        'CI_BRANCH': build.branch,
        'CI_BUILD_NUMBER': build.build_number,
        'CI_COMMITTER_EMAIL': build.committer_email,
        'CI_COMMITTER_NAME': build.committer_name,
        'CI_COMMITTER_USERNAME': build.committer_username}
    task_definition['tags'] = unpack_dict(tags)

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


