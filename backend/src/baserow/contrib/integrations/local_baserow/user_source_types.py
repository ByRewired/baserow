from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from django.contrib.auth.models import AbstractUser
from django.core.cache import cache
from django.db.models import QuerySet

from rest_framework import serializers
from rest_framework.exceptions import ValidationError as DRFValidationError

from baserow.contrib.database.fields.exceptions import FieldDoesNotExist
from baserow.contrib.database.fields.handler import FieldHandler
from baserow.contrib.database.fields.models import Field, SingleSelectField
from baserow.contrib.database.search.handler import SearchHandler
from baserow.contrib.database.table.exceptions import TableDoesNotExist
from baserow.contrib.database.table.handler import TableHandler
from baserow.contrib.database.table.models import GeneratedTableModel, Table
from baserow.contrib.integrations.local_baserow.integration_types import (
    LocalBaserowIntegrationType,
)
from baserow.contrib.integrations.local_baserow.models import LocalBaserowUserSource
from baserow.core.user.exceptions import UserNotFound
from baserow.core.user_sources.exceptions import UserSourceImproperlyConfigured
from baserow.core.user_sources.registries import UserSourceCount, UserSourceType
from baserow.core.user_sources.types import UserSourceDict
from baserow.core.user_sources.user_source_user import UserSourceUser

# How long a counted number of users stays valid. It is deliberately longer than
# the interval of the counting task, so a user source keeps a usable count even
# when one counting round is missed.
USER_COUNT_CACHE_TTL_SECONDS = 60 * 60 * 24 * 2

# The fields of the user table that the user source points at.
USER_SOURCE_FIELD_NAMES = ["email_field", "name_field", "role_field"]


class LocalBaserowUserSourceType(UserSourceType):
    """
    Reads the users of an application from a table of the local Baserow instance.
    """

    type = "local_baserow"
    model_class = LocalBaserowUserSource
    integration_type = LocalBaserowIntegrationType.type

    # Only the table decides how many users this source has. Changing which field
    # holds the email or the name doesn't add or remove rows.
    properties_requiring_user_recount = ["table"]

    allowed_fields = ["table", "email_field", "name_field", "role_field"]
    serializer_field_names = [
        "table_id",
        "email_field_id",
        "name_field_id",
        "role_field_id",
    ]
    serializer_field_overrides = {
        "table_id": serializers.IntegerField(
            required=False,
            allow_null=True,
            help_text="The id of the Baserow table containing the users.",
        ),
        "email_field_id": serializers.IntegerField(
            required=False,
            allow_null=True,
            help_text="The id of the field holding the email address of the user.",
        ),
        "name_field_id": serializers.IntegerField(
            required=False,
            allow_null=True,
            help_text="The id of the field holding the name of the user.",
        ),
        "role_field_id": serializers.IntegerField(
            required=False,
            allow_null=True,
            help_text="The id of the field holding the role of the user.",
        ),
    }

    class SerializedDict(UserSourceDict):
        table_id: int
        email_field_id: int
        name_field_id: int
        role_field_id: int

    def enhance_queryset(self, queryset):
        return queryset.select_related(
            "table",
            "table__database",
            "email_field",
            "name_field",
            "role_field",
        )

    def gen_uid(self, user_source: LocalBaserowUserSource) -> str:
        """
        The uid changes as soon as the source points somewhere else, so the tokens
        that were handed out for the previous configuration stop being accepted.
        """

        return (
            f"{user_source.id}_{user_source.table_id}_"
            f"{user_source.email_field_id}_{user_source.role_field_id}"
        )

    def prepare_values(
        self,
        values: Dict[str, Any],
        user: AbstractUser,
        instance: Optional[LocalBaserowUserSource] = None,
    ) -> Dict[str, Any]:
        """
        Replaces the given table and field ids by their instances and refuses any
        field that doesn't belong to the table the source ends up pointing at.
        """

        if "table_id" in values:
            table_id = values.pop("table_id")
            if table_id is None:
                values["table"] = None
            else:
                try:
                    values["table"] = TableHandler().get_table(table_id)
                except TableDoesNotExist as exc:
                    raise DRFValidationError(
                        detail=f"The table with ID {table_id} does not exist.",
                        code="invalid_table",
                    ) from exc

            # The previously chosen fields belong to the previous table, so they
            # can't be kept unless the same request replaces them.
            if instance is not None and instance.table_id != getattr(
                values["table"], "id", None
            ):
                for field_name in USER_SOURCE_FIELD_NAMES:
                    values.setdefault(field_name, None)

        table = values.get("table", getattr(instance, "table", None))

        for field_name in USER_SOURCE_FIELD_NAMES:
            key = f"{field_name}_id"
            if key not in values:
                continue

            field_id = values.pop(key)
            if field_id is None:
                values[field_name] = None
                continue

            try:
                field = FieldHandler().get_field(field_id)
            except FieldDoesNotExist as exc:
                raise DRFValidationError(
                    detail=f"The field with ID {field_id} does not exist.",
                    code="invalid_field",
                ) from exc

            if table is None or field.table_id != table.id:
                raise DRFValidationError(
                    detail=f"The field with ID {field_id} doesn't belong to the "
                    "selected table.",
                    code="invalid_field",
                )

            values[field_name] = field

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
        Points the table and the field references at the copies that the same
        import created. A reference that wasn't part of the import is dropped: it
        would otherwise reach a table the importing workspace can't see.
        """

        if prop_name == "table_id" and "database_tables" in id_mapping:
            return id_mapping["database_tables"].get(value, None)

        if (
            prop_name in [f"{name}_id" for name in USER_SOURCE_FIELD_NAMES]
            and "database_fields" in id_mapping
        ):
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

    def is_configured(self, user_source: LocalBaserowUserSource) -> bool:
        """
        Whether the source knows enough to hand out users. The role field stays
        optional; without it everyone shares the default role.
        """

        return bool(
            self.get_usable_table(user_source)
            and user_source.email_field_id
            and user_source.name_field_id
        )

    def get_usable_table(
        self, user_source: LocalBaserowUserSource
    ) -> Optional[Table]:
        """
        Returns the table the source reads from, or None when there is none or
        when it has been trashed along with the database that holds it.
        """

        if not user_source.table_id:
            return None

        table = user_source.table
        if table.trashed or table.database.trashed:
            return None

        return table

    def get_user_model(
        self, user_source: LocalBaserowUserSource
    ) -> Optional[GeneratedTableModel]:
        """
        Returns the generated model of the table the users are read from, or None
        when the source isn't pointing at a usable table yet.
        """

        table = self.get_usable_table(user_source)
        if table is None:
            return None

        return table.get_model()

    def _usable_field(
        self, user_source: LocalBaserowUserSource, field_name: str
    ) -> Optional[Field]:
        """
        Returns one of the configured fields, unless it was trashed or no longer
        belongs to the selected table.
        """

        field = getattr(user_source, field_name, None)
        if field is None or field.trashed:
            return None

        if field.table_id != user_source.table_id:
            return None

        return field

    def _read_value(self, row, field: Optional[Field]) -> str:
        """
        Reads one cell as a string. A single select is read through the value of
        the option it points at, everything else through its own value.
        """

        if field is None:
            return ""

        value = getattr(row, field.db_column, None)
        if value is None:
            return ""

        if isinstance(field.specific, SingleSelectField):
            return str(getattr(value, "value", "") or "")

        return str(value)

    def _row_to_user(
        self, user_source: LocalBaserowUserSource, row
    ) -> UserSourceUser:
        role_field = self._usable_field(user_source, "role_field")
        role = self._read_value(row, role_field).strip()

        return UserSourceUser(
            user_source,
            row,
            row.id,
            self._read_value(row, self._usable_field(user_source, "name_field")),
            self._read_value(row, self._usable_field(user_source, "email_field")),
            role or self.get_default_user_role(user_source),
        )

    def get_roles(self, user_source: LocalBaserowUserSource) -> List[str]:
        role_field = self._usable_field(user_source, "role_field")

        if role_field is None:
            return [self.get_default_user_role(user_source)]

        model = self.get_user_model(user_source)
        if model is None:
            return []

        column = role_field.db_column
        if isinstance(role_field.specific, SingleSelectField):
            column = f"{column}__value"

        roles = set()
        for value in model.objects.values_list(column, flat=True).distinct():
            role = str(value).strip() if value is not None else ""
            roles.add(role or self.get_default_user_role(user_source))

        return sorted(roles)

    def get_user_queryset(
        self, user_source: LocalBaserowUserSource
    ) -> Optional[QuerySet]:
        model = self.get_user_model(user_source)
        if model is None:
            return None

        return model.objects.all()

    def list_users(
        self, user_source: LocalBaserowUserSource, count: int = 5, search: str = ""
    ) -> Iterable[UserSourceUser]:
        if not self.is_configured(user_source):
            return []

        queryset = self.get_user_queryset(user_source)

        if search:
            searchable_field_ids = [
                field.id
                for field in [
                    self._usable_field(user_source, "email_field"),
                    self._usable_field(user_source, "name_field"),
                ]
                if field is not None
            ]
            queryset = queryset.search_all_fields(
                search,
                only_search_by_field_ids=searchable_field_ids,
                search_mode=SearchHandler.get_default_search_mode_for_table(
                    user_source.table
                ),
            )

        return [self._row_to_user(user_source, row) for row in queryset[:count]]

    def get_user_row(self, user_source: LocalBaserowUserSource, **kwargs):
        """
        Returns the row backing a user, looked up either by its row id or by the
        email address it holds.

        :raises UserNotFound: When no row matches.
        """

        queryset = self.get_user_queryset(user_source)
        if queryset is None:
            raise UserNotFound()

        if "user_id" in kwargs:
            queryset = queryset.filter(id=kwargs["user_id"])
        elif "email" in kwargs:
            email_field = self._usable_field(user_source, "email_field")
            if email_field is None:
                raise UserNotFound()
            # Email addresses are compared without case, the way every mail
            # server treats them, so a user isn't locked out by their keyboard.
            queryset = queryset.filter(
                **{f"{email_field.db_column}__iexact": kwargs["email"]}
            )
        else:
            raise UserNotFound()

        row = queryset.order_by("id").first()
        if row is None:
            raise UserNotFound()

        return row

    def get_user(
        self, user_source: LocalBaserowUserSource, **kwargs
    ) -> UserSourceUser:
        return self._row_to_user(
            user_source, self.get_user_row(user_source, **kwargs)
        )

    def create_user(
        self, user_source: LocalBaserowUserSource, email: str, name: str
    ) -> UserSourceUser:
        from baserow.contrib.database.rows.handler import RowHandler

        if not self.is_configured(user_source):
            raise UserSourceImproperlyConfigured()

        model = self.get_user_model(user_source)
        values = {}

        email_field = self._usable_field(user_source, "email_field")
        if email_field is not None:
            values[email_field.db_column] = email

        name_field = self._usable_field(user_source, "name_field")
        if name_field is not None:
            values[name_field.db_column] = name

        row = RowHandler().force_create_row(
            user=user_source.integration.specific.authorized_user,
            table=user_source.table,
            values=values,
            model=model,
        )

        return self._row_to_user(user_source, row)

    def authenticate(
        self, user_source: LocalBaserowUserSource, **kwargs
    ) -> UserSourceUser:
        """
        Hands the credentials to the auth provider configured on this source.
        """

        from baserow.core.app_auth_providers.handler import AppAuthProviderHandler

        if not self.is_configured(user_source):
            raise UserSourceImproperlyConfigured()

        for auth_provider in AppAuthProviderHandler.list_app_auth_providers_for_user_source(
            user_source
        ):
            if auth_provider.enabled:
                return auth_provider.get_type().authenticate(auth_provider, **kwargs)

        raise UserSourceImproperlyConfigured()

    def _user_count_cache_key(self, user_source: LocalBaserowUserSource) -> str:
        return f"local_baserow_user_source_{user_source.id}_user_count"

    def _store_user_count(
        self, user_source: LocalBaserowUserSource, count: Optional[int]
    ) -> Optional[UserSourceCount]:
        cache_key = self._user_count_cache_key(user_source)

        if count is None:
            cache.delete(cache_key)
            return None

        user_source_count = UserSourceCount(
            count=count, last_updated=datetime.now()
        )
        cache.set(cache_key, user_source_count, timeout=USER_COUNT_CACHE_TTL_SECONDS)

        return user_source_count

    def update_user_count(
        self,
        user_sources: Optional[QuerySet[LocalBaserowUserSource]] = None,
    ) -> Optional[UserSourceCount]:
        if user_sources is None:
            user_sources = self.model_class.objects.all()

        if isinstance(user_sources, QuerySet):
            user_sources = user_sources.select_related("table", "table__database")

        # Several sources commonly point at the same table, so the rows are only
        # counted once per table.
        count_per_table: Dict[int, int] = {}
        last_count = None

        for user_source in user_sources:
            table = self.get_usable_table(user_source)

            if table is None:
                count = None
            else:
                if table.id not in count_per_table:
                    count_per_table[table.id] = (
                        table.get_model(field_ids=[]).objects.count()
                    )
                count = count_per_table[table.id]

            last_count = self._store_user_count(user_source, count)

        return last_count

    def get_user_count(
        self,
        user_source: LocalBaserowUserSource,
        force_recount: bool = False,
        update_if_uncached: bool = True,
    ) -> Optional[UserSourceCount]:
        if not force_recount:
            cached = cache.get(self._user_count_cache_key(user_source))
            if cached is not None:
                return cached
            if not update_if_uncached:
                return None

        return self.update_user_count(
            self.model_class.objects.filter(pk=user_source.pk)
        )
