#!/usr/bin/env python3
from gevent import monkey  # isort:skip
monkey.patch_all()  # isort:skip

import logging
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv
from rotkehlchen.chain.evm.nodes import populate_rpc_nodes_in_database
from rotkehlchen.config import default_data_directory
from rotkehlchen.data_handler import DataHandler
from rotkehlchen.db.dbhandler import DBHandler
from rotkehlchen.db.settings import ModifiableDBSettings
from rotkehlchen.globaldb.handler import GlobalDBHandler
from rotkehlchen.logging import TRACE, add_logging_level
from rotkehlchen.premium.premium import PremiumCredentials
from rotkehlchen.types import ApiKey, ExternalService, ExternalServiceApiCredentials
from rotkehlchen.user_messages import MessagesAggregator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s: %(message)s',
)
logger = logging.getLogger('sync-util')
logger.setLevel(logging.DEBUG)

BACKUP_DIR = Path.joinpath(Path.cwd(), 'backups')

load_dotenv()


def data_directory(dev: bool) -> Path:
    if dev is False:
        sys.frozen = True  # type: ignore
    data_dir = default_data_directory()
    sys.frozen = False  # type: ignore
    return data_dir


def set_external_api_key(
        db: DBHandler,
        service: ExternalService,
        key: Optional[str],
) -> None:
    if key is None:
        return

    logger.info(f'Setting up {service}')

    with db.conn.write_ctx() as write_cursor:
        db.add_external_service_credentials(
            write_cursor=write_cursor,
            credentials=[
                ExternalServiceApiCredentials(
                    service=service,
                    api_key=ApiKey(key),
                ),
            ],
        )


@click.group()
def cli() -> None:
    """Set of utilities to deal with rotki testing/development"""


@click.command()
@click.option(
    '--dev',
    type=click.BOOL,
    is_flag=True,
    help='If set it will do a backup of the development directory instead.',
)
def backup(dev: bool) -> None:
    """Creates a backup of the user directory"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rotki_data = data_directory(dev=dev)
    today = datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')
    postfix = '.dev' if dev else ''
    backup_file = Path.joinpath(BACKUP_DIR, f'rotki_data_{today}{postfix}.zip')
    logger.info(f'Preparing to save {rotki_data} to archive {backup_file}')
    with zipfile.ZipFile(backup_file, mode='w') as archive:
        for file_path in rotki_data.rglob('*'):
            archive.write(
                file_path,
                arcname=file_path.relative_to(rotki_data),
            )


@click.command()
@click.option(
    '--file',
    type=click.Path(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        path_type=Path,
    ),
    required=True,
    help='The zip archive to restore from',
)
@click.option(
    '--dev',
    type=click.BOOL,
    is_flag=True,
    help='If set it will do a restore to the develop directory.',
)
def restore(file: Path, dev: bool) -> None:
    """Replaces the data directory contents with that of a backup archive"""
    with zipfile.ZipFile(file, mode='r') as archive:
        data_dir = data_directory(dev=dev)
        logger.info(f'deleting {data_dir}')
        shutil.rmtree(data_dir)
        logger.info(f'preparing to extract to {data_dir}')
        archive.extractall(data_dir)


@click.command()
@click.option(
    '--username',
    type=click.STRING,
    help='The username of the new account',
    required=True,
)
@click.option(
    '--password',
    type=click.STRING,
    default='1234',
    help='The password of the new account',
)
def new_user(username: str, password: str) -> None:
    """Creates a new user with the specified username and password
    and initializes api keys with the values from the .env file
    """
    data_dir = data_directory(dev=True)
    vm_instructions = 500
    GlobalDBHandler(
        data_dir=data_dir,
        sql_vm_instructions_cb=vm_instructions,
    )
    aggregator = MessagesAggregator()

    data_handler = DataHandler(
        data_directory=data_dir,
        msg_aggregator=aggregator,
        sql_vm_instructions_cb=vm_instructions,
    )

    logger.info(f'Creating new user {username} in {data_dir}')

    data_handler.unlock(
        username=username,
        password=password,
        create_new=True,
        initial_settings=ModifiableDBSettings(
            premium_should_sync=False,
            submit_usage_analytics=False,
        ),
    )

    with data_handler.db.conn.write_ctx() as write_cursor:
        populate_rpc_nodes_in_database(write_cursor)

    api_key = os.environ.get('ROTKI_API_KEY')
    api_secret = os.environ.get('ROTKI_API_SECRET')

    if api_key is not None and api_secret is not None:
        logger.info('Setting up rotki API keys')
        credentials = PremiumCredentials(
            given_api_key=api_key,
            given_api_secret=api_secret,
        )
        data_handler.db.set_rotkehlchen_premium(credentials=credentials)

    set_external_api_key(
        db=data_handler.db,
        service=ExternalService.CRYPTOCOMPARE,
        key=os.environ.get('CRYPTOCOMPARE_API_KEY'),
    )

    set_external_api_key(
        db=data_handler.db,
        service=ExternalService.ETHERSCAN,
        key=os.environ.get('ETHERSCAN_API_KEY'),
    )

    set_external_api_key(
        db=data_handler.db,
        service=ExternalService.OPTIMISM_ETHERSCAN,
        key=os.environ.get('OPTIMISM_ETHERSCAN_API_KEYS'),
    )

    data_handler.logout()


@click.command()
@click.option(
    '--username',
    type=click.STRING,
    required=True,
    help='The username of the account to copy',
)
@click.option(
    '--include-global',
    type=click.BOOL,
    is_flag=True,
    help='If set it will also copy the global_data (global.db)',
)
def sync_user(username: str, include_global: bool) -> None:
    """Copies the specified user from the develop_data to data"""
    production_data_dir = data_directory(dev=False)
    develop_data_dir = data_directory(dev=True)

    user_data = production_data_dir.joinpath(username)
    develop_data = develop_data_dir.joinpath(username)
    if not user_data.exists():
        logger.error(f'{user_data} does not exist')
        sys.exit(1)

    if develop_data.exists() is True:
        logger.info(f'deleting {develop_data}')
        shutil.rmtree(develop_data)

    logger.info(f'copying ${user_data} to {develop_data}')
    shutil.copytree(user_data, develop_data)

    if include_global is True:
        global_data = production_data_dir.joinpath('global_data')
        develop_global_data = develop_data_dir.joinpath('global_data')

        if develop_global_data.exists():
            logger.info(f'deleting {develop_global_data}')
            shutil.rmtree(develop_global_data)

        logger.info(f'copying ${global_data} to {develop_global_data}')
        shutil.copytree(global_data, develop_global_data)


@click.command()
@click.option(
    '--username',
    type=click.STRING,
    required=True,
    help='The username of which an archive will be created.',
)
@click.option(
    '--dev',
    type=click.BOOL,
    is_flag=True,
    help='If set it will do a restore to the develop directory.',
)
def zip_account(username: str, dev: bool) -> None:
    """Creates an archive of the data_directory of the specified user"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    develop_data_dir = data_directory(dev=dev)
    user_data = develop_data_dir.joinpath(username)
    today = datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')
    postfix = '.dev' if dev else ''
    backup_file = Path.joinpath(BACKUP_DIR, f'rotki_{username}_{today}{postfix}.zip')
    logger.info(f'Preparing to save {user_data} to archive {backup_file}')
    with zipfile.ZipFile(backup_file, mode='w') as archive:
        for file_path in user_data.rglob('*'):
            archive.write(
                file_path,
                arcname=file_path.relative_to(user_data),
            )


cli.add_command(backup)
cli.add_command(restore)
cli.add_command(new_user)
cli.add_command(sync_user)
cli.add_command(zip_account)

if __name__ == '__main__':
    add_logging_level('TRACE', TRACE)
    cli()
