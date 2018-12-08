import click
import boto3

@click.group()
def cli():
    pass

@cli.command()
@click.option('--task-definition-family', required=True)
@click.option('--aws-region', required=True)
@click.option('--ecs-cluster', required=True)
@click.option('--ecr-repository-uri', required=True)
@click.option('--ecs-service-name', required=True)
@click.option('--ci-commit-id', required=True, envvar='CI_COMMIT_ID')
@click.option('--ci-message', default='', envvar='CI_COMMIT_MESSAGE')
@click.option('--ci-branch', default='', envvar='CI_BRANCH')
@click.option('--ci-build-number', default='', envvar='CI_BUILD_ID')
@click.option('--ci-build-url', default='')
@click.option('--ci-committer-email', default='', envvar='CI_COMMITTER_EMAIL')
@click.option('--ci-committer-username', default='', envvar='CI_COMMITTER_USERNAME')
@click.option('--ci-committer-name', default='', envvar='CI_COMMITTER_NAME')

def deploy(task_definition_family,
        aws_region,
        ecs_cluster,
        ecr_repository_uri,
        ecs_service_name,
        ci_commit_id,
        ci_message,
        ci_branch,
        ci_build_number,
        ci_build_url,
        ci_committer_email,
        ci_committer_username,
        ci_committer_name):
    session = boto3.session.Session()
    client = session.client('ecs', region_name='us-west-2')
    task_definition = register_task_definition(
        client,
        task_definition_family,
        ecr_repository_uri,
        ci_commit_id,
        ci_message,
        ci_branch,
        ci_build_number,
        ci_build_url,
        ci_committer_email,
        ci_committer_name,
        ci_committer_username)
    print('New task definition created ', task_definition)

    update_service(client,task_definition,ecs_cluster, ecs_service_name)

def unpack_dict(dict_to_unpack):
    unpacked_dict = []
    for k,v in dict_to_unpack.items():
        unpacked_dict.append({'key': k, 'value': v})
    return unpacked_dict

def register_task_definition(client,
                             task_definition_family,
                             ecr_repository_uri,
                             CI_COMMIT_ID,
                             CI_MESSAGE,
                             CI_BRANCH,
                             CI_BUILD_NUMBER,
                             CI_BUILD_URL,
                             CI_COMMITTER_EMAIL,
                             CI_COMMITTER_NAME,
                             CI_COMMITTER_USERNAME):
    task_definition = client.describe_task_definition(taskDefinition=task_definition_family)['taskDefinition']

    # Remove elements from response that are not to be sent back in updating the task definition
    task_definition_elements_to_remove = ['taskDefinitionArn', 'status', 'compatibilities', 'requiresAttributes', 'revision']
    for k in task_definition_elements_to_remove:
        task_definition.pop(k, None)

    new_image_label = CI_COMMIT_ID

    new_image = ecr_repository_uri + ':' + new_image_label

    task_definition['containerDefinitions'][0]['image'] = new_image

    tags = {
        'CI_COMMIT_ID': CI_COMMIT_ID,
        'CI_MESSAGE': CI_MESSAGE,
        'CI_BRANCH': CI_BRANCH,
        'CI_BUILD_NUMBER': CI_BUILD_NUMBER,
        'CI_BUILD_URL': CI_BUILD_URL,
        'CI_COMMITTER_EMAIL': CI_COMMITTER_EMAIL,
        'CI_COMMITTER_NAME': CI_COMMITTER_NAME,
        'CI_COMMITTER_USERNAME': CI_COMMITTER_USERNAME}
    task_definition['tags'] = unpack_dict(tags)

    response = client.register_task_definition(**task_definition)
    new_task_revision = response['taskDefinition']['revision']
    new_task_definition_name = task_definition_family + ':' + str(new_task_revision)
    return new_task_definition_name

def update_service(client,task_definition, cluster, service):
    response = client.update_service(cluster=cluster, service=service, taskDefinition=task_definition)

if __name__ == '__main__':
    cli(auto_envvar_prefix="DEPLOY")


