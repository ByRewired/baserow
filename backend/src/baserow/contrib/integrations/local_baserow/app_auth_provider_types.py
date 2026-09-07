from typing import Any, Dict, Optional

from django.contrib.auth.hashers import check_password, make_password

from rest_framework import serializers

from baserow.contrib.database.fields.exceptions import FieldDoesNotExist
from baserow.contrib.database.fields.handler import FieldHandler
from baserow.contrib.integrations.local_baserow.models import (
    LocalBaserowPasswordAppAuthProvider,
)
from baserow.core.app_auth_providers.auth_provider_types import AppAuthProviderType
from baserow.core.app_auth_providers.types import AppAuthProviderTypeDict
from baserow.core.user.exceptions import UserNotFound
from baserow.core.user_sources.exceptions import UserSourceImproperlyConfigured
from baserow.core.user_sources.user_source_user import UserSourceUser

# Hashing a throwaway value costs the same as checking a real one. Comparing
# against it when no row matched keeps a failed sign in indistinguishable from a
# sign in for an address that isn't in the table.
ABSENT_USER_PASSWORD = make_password(None)


class LocalBaserowPasswordAppAuthProviderType(AppAuthProviderType):
    """
    Signs a user in against a password stored, hashed, in a column of the table
    that backs the user source.
    """

    type = "local_baserow_password"
    model_class = LocalBaserowPasswordAppAuthProvider

    compatible_user_source_types = ["local_baserow"]

    allowed_fields = ["password_field"]
    serializer_field_names = ["password_field_id"]
    serializer_field_overrides = {
        "password_field_id": serializers.IntegerField(
            required=False,
            allow_null=True,
            help_text="The id of the field holding the hashed password of the user.",
        ),
    }

    class SerializedDict(AppAuthProviderTypeDict):
        password_field_id: int

    def enhance_queryset(self, queryset):
        return queryset.select_related("password_field")

    def prepare_values(
        self,
        values: Dict[str, Any],
        user,
        instance: Optional[LocalBaserowPasswordAppAuthProvider] = None,
    ) -> Dict[str, Any]:
        """
        Swaps the incoming field id for the field itself, and refuses one that
        belongs to another table than the user source reads from.
        """

        if "password_field_id" in values:
            field_id = values.pop("password_field_id")

            if field_id is None:
                values["password_field"] = None
                return super().prepare_values(values, user, instance)

            user_source = values.get("user_source") or getattr(
                instance, "user_source", None
            )
            table = getattr(
                user_source.specific if user_source else None, "table", None
            )

            try:
                field = FieldHandler().get_field(field_id)
            except FieldDoesNotExist as exc:
                raise serializers.ValidationError(
                    {"password_field_id": "The field doesn't exist."}
                ) from exc

            if table is None or field.table_id != table.id:
                raise serializers.ValidationError(
                    {
                        "password_field_id": "The field must belong to the table the "
                        "user source reads its users from."
                    }
                )

            values["password_field"] = field

        return super().prepare_values(values, user, instance)

    def deserialize_property(
        self,
        prop_name: str,
        value: Any,
        id_mapping: Dict[str, Dict[int, int]],
        files_zip=None,
        storage=None,
        cache=None,
        **kwargs,
    ) -> Any:
        """
        Points the field reference at the copy the same import created, and drops
        one that wasn't part of it.
        """

        if prop_name == "password_field_id" and "database_fields" in id_mapping:
            return id_mapping["database_fields"].get(value, None)

        return super().deserialize_property(
            prop_name,
            value,
            id_mapping,
            files_zip=files_zip,
            storage=storage,
            cache=cache,
            **kwargs,
        )

    def is_configured(
        self, auth_provider: LocalBaserowPasswordAppAuthProvider
    ) -> bool:
        return auth_provider.password_field_id is not None

    def authenticate(
        self, auth_provider: LocalBaserowPasswordAppAuthProvider, **kwargs
    ) -> UserSourceUser:
        """
        Checks the given password against the hash held for the address.

        :raises UserSourceImproperlyConfigured: When no password field is set.
        :raises UserNotFound: When the address is unknown or the password is wrong.
          The two are reported the same way on purpose, so the response doesn't
          tell an attacker which addresses exist.
        """

        if not self.is_configured(auth_provider):
            raise UserSourceImproperlyConfigured()

        email = kwargs.get("email", "")
        password = kwargs.get("password", "")

        user_source = auth_provider.user_source.specific
        user_source_type = user_source.get_type()

        try:
            row = user_source_type.get_user_row(user_source, email=email)
        except UserNotFound:
            # Still spend the time a real check would, then fail.
            check_password(password, ABSENT_USER_PASSWORD)
            raise

        stored = getattr(row, auth_provider.password_field.db_column, None) or ""

        if not check_password(password, str(stored)):
            raise UserNotFound()

        return user_source_type._row_to_user(user_source, row)
