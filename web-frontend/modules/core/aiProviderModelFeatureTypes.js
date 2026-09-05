import { Registerable } from '@baserow/modules/core/registry'

export function getEnabledModelsForAIProviderFeature(
  workspace,
  featureType,
  featureFilteringEnabled = true
) {
  if (!featureFilteringEnabled) {
    return workspace?.generative_ai_models_enabled ?? {}
  }
  return (
    workspace?.ai_features?.[featureType]?.models ??
    workspace?.generative_ai_models_enabled ??
    {}
  )
}

export class AIProviderModelFeatureType extends Registerable {
  getName() {
    throw new Error(
      'Must be implemented by the AI provider model feature type.'
    )
  }

  getDescription() {
    return ''
  }

  /**
   * Whether this feature can fall back to a model configured through an
   * environment variable when nothing is selected in the database.
   */
  supportsLegacyModel() {
    return false
  }

  /**
   * The environment-variable model this feature falls back to, empty when none
   * is configured.
   */
  getLegacyModel() {
    return ''
  }
}

export class AIFieldsAIProviderModelFeatureType extends AIProviderModelFeatureType {
  static getType() {
    return 'ai_fields'
  }

  getOrder() {
    return 10
  }

  getName() {
    return this.app.$i18n.t('aiProviderModelFeature.aiFields')
  }

  getDescription() {
    return this.app.$i18n.t('aiProviderModelFeature.aiFieldsDescription')
  }
}

export class KumaAIProviderModelFeatureType extends AIProviderModelFeatureType {
  static getType() {
    return 'kuma'
  }

  getOrder() {
    return 20
  }

  getName() {
    return this.app.$i18n.t('aiProviderModelFeature.kuma')
  }

  getDescription() {
    return this.app.$i18n.t('aiProviderModelFeature.kumaDescription')
  }

  supportsLegacyModel() {
    return true
  }

  getLegacyModel() {
    // The assistant reads this model from the environment of the process it runs
    // in, so the option can only be offered when this process was given it too.
    return this.app.$config?.public?.baserowEnterpriseAssistantLlmModel || ''
  }
}
