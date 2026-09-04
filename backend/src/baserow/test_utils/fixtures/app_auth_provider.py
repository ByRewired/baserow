from typing import Optional

import pytest

from baserow.core.app_auth_providers.auth_provider_types import AppAuthProviderType
from baserow.core.app_auth_providers.registries import app_auth_provider_type_registry
from baserow.core.registry import InstanceTypeDoesNotExist


def get_app_auth_provider_type_or_skip(
    type_name: Optional[str] = None,
) -> AppAuthProviderType:
    """
    Returns a registered app auth provider type, or skips the test that asked for it
    when it isn't available. App auth provider types are provided by plugins, so a
    plain installation doesn't necessarily have any of them.

    :param type_name: The name of the required type. When omitted the first
        registered type is returned.
    :return: The requested app auth provider type.
    """

    try:
        if type_name is None:
            return next(iter(app_auth_provider_type_registry.get_all()))
        return app_auth_provider_type_registry.get(type_name)
    except (StopIteration, InstanceTypeDoesNotExist):
        pytest.skip(
            f"The {type_name or 'first'} app auth provider type is not registered "
            f"because no plugin providing it is installed."
        )


class AppAuthProviderFixtures:
    def create_app_auth_provider_with_first_type(self, **kwargs):
        first_type = get_app_auth_provider_type_or_skip()
        return self.create_app_auth_provider(first_type.model_class, **kwargs)

    def create_app_auth_provider(
        self, model_class, user=None, user_source=None, **kwargs
    ):
        if not user_source:
            user_source_args = kwargs.pop("user_source_args", {})
            user_source = self.create_user_source_with_first_type(
                user=user, **user_source_args
            )

        user_source = model_class.objects.create(user_source=user_source, **kwargs)

        return user_source
