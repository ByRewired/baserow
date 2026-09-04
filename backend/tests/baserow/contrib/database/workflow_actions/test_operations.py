from baserow.contrib.database.workflow_actions.object_scopes import (
    DatabaseWorkflowActionObjectScopeType,
)
from baserow.contrib.database.workflow_actions.operations import (
    DispatchDatabaseWorkflowActionOperationType,
)
from baserow.core.registries import object_scope_type_registry, operation_type_registry


def test_the_dispatch_operation_is_registered():
    operation = operation_type_registry.get(
        DispatchDatabaseWorkflowActionOperationType.type
    )

    assert operation.context_scope_name == "database_workflow_action"


def test_the_object_scope_is_registered():
    scope = object_scope_type_registry.get("database_workflow_action")

    assert isinstance(scope, DatabaseWorkflowActionObjectScopeType)
