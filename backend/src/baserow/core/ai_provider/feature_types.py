from baserow.core.generative_ai.registries import generative_ai_model_type_registry

from .constants import (
    AI_PROVIDER_FEATURE_AI_FIELDS,
    AI_PROVIDER_FEATURE_KUMA,
    AI_PROVIDER_MODEL_CAPABILITY_TEXT,
    AI_PROVIDER_MODEL_CAPABILITY_TOOLS,
)
from .registries import AIProviderModelFeatureType


class AIFieldsAIProviderModelFeatureType(AIProviderModelFeatureType):
    """The AI fields feature, which picks its model per field."""

    type = AI_PROVIDER_FEATURE_AI_FIELDS
    supports_default_model = False
    required_model_capabilities = (AI_PROVIDER_MODEL_CAPABILITY_TEXT,)

    def get_workspace_availability(self, workspace, state=None) -> dict:
        """Return the models a field in this scope may choose.

        The feature itself is never switched off, because a field selects its own
        model instead of following one scoped default. What the scope needs to know
        is therefore which models it is allowed to offer.

        :param workspace: The workspace scope, or None for the instance scope.
        :param state: An already-loaded state for the scope, avoiding a reload.
        :return: ``is_enabled`` plus the eligible ``models`` per provider type.
        """

        return {
            "is_enabled": True,
            "models": generative_ai_model_type_registry.get_enabled_models_per_type(
                workspace=workspace, feature_type=self.type, state=state
            ),
        }


class KumaAIProviderModelFeatureType(AIProviderModelFeatureType):
    """The Kuma assistant, which runs on one model chosen per scope."""

    type = AI_PROVIDER_FEATURE_KUMA
    supports_default_model = True
    # The assistant works through tool calls, so a model that only answers with
    # text cannot serve it even though it passes the baseline probe.
    required_model_capabilities = (
        AI_PROVIDER_MODEL_CAPABILITY_TEXT,
        AI_PROVIDER_MODEL_CAPABILITY_TOOLS,
    )
