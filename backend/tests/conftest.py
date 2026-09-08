from __future__ import print_function

from io import IOBase
from pathlib import Path

from django.core.management import call_command
from django.db import connections
from django.test.testcases import TransactionTestCase

import pytest

# noinspection PyUnresolvedReferences
from baserow.test_utils.pytest_conftest import *  # noqa: F403, F401
from baserow.test_utils.pytest_conftest import (  # noqa: F401
    pytest_collection_modifyitems as _skip_by_command_line_flag,
)


def _fixture_teardown(self):
    """
    This is a custom implementation of `TransactionTestCase._fixture_teardown`
    from Django (https://github.com/django/django/blob/main/django/test/testcases.py)
    that flushes test database after test runs with allow_cascade=True.

    This is needed as our custom Baserow tables won't be in the list of tables
    to truncate, and hence may create problems when rows are
    referencing other tables.
    """

    # Allow TRUNCATE ... CASCADE and don't emit the post_migrate signal
    # when flushing only a subset of the apps
    for db_name in self._databases_names(include_mirrors=False):
        # Flush the database
        inhibit_post_migrate = (
            self.available_apps is not None
            or (  # Inhibit the post_migrate signal when using serialized
                # rollback to avoid trying to recreate the serialized data.
                self.serialized_rollback
                and hasattr(connections[db_name], "_test_serialized_contents")
            )
        )
        call_command(
            "flush",
            verbosity=0,
            interactive=False,
            database=db_name,
            reset_sequences=False,
            allow_cascade=True,  # CHANGED FROM DJANGO
            inhibit_post_migrate=inhibit_post_migrate,
        )


TransactionTestCase._fixture_teardown = _fixture_teardown


@pytest.fixture()
def test_data_dir() -> Path:
    """
    Returns root path for test data directory
    """

    return Path(__file__).parent.joinpath("test_data")


@pytest.fixture()
def open_test_file(test_data_dir):
    """
    Opens a test data file on a given path.

    usage:

    def test_me(open_test_file):
        with open_test_file('baserow/core/test.data', 'rt') as f:
            assert not f.closed

    Note: the caller can treat this as a context manager factory.
    """

    fhandle: IOBase | None = None

    def get_path(tpath, /, mode="rb") -> IOBase:
        nonlocal fhandle
        fhandle = (test_data_dir / (tpath)).open(mode=mode)

        return fhandle

    yield get_path
    if fhandle and not fhandle.closed:
        fhandle.close()


@pytest.fixture()
def on_db_connection(db):
    def register(callback):
        from django.db import connection

        callback(connection)

    yield register


def pytest_collection_modifyitems(config, items):
    # `import *` above already brought in a hook of this name, and defining one
    # here replaces it rather than adding to it, so call it explicitly first.
    _skip_by_command_line_flag(config, items)

    from baserow.contrib.database.views.registries import (
        view_ownership_type_registry,
    )

    if "personal" in view_ownership_type_registry.registry:
        return

    skip = pytest.mark.skip(reason="the personal view ownership type is not installed")
    for item in items:
        if "view_ownership" in item.keywords:
            item.add_marker(skip)
