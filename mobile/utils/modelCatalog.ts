import { File, Paths } from 'expo-file-system';

export type CatalogProvider = 'agy' | 'codex' | 'claude' | 'kimi';

export interface CatalogCapabilities {
  effort: string[];
  speed: string[];
  thinking: boolean;
  thinking_required: boolean;
}

export interface CatalogModel {
  id: string;
  label: string;
  description: string;
  provider: CatalogProvider;
  cli_model?: string;
  badge: string;
  usage_bucket: 'gemini' | 'claude' | 'gpt';
  enabled: boolean;
  capabilities: CatalogCapabilities;
}

export interface ModelCatalog {
  schema_version: 1;
  catalog_version: string;
  default_model: string;
  models: CatalogModel[];
}

const CATALOG_CACHE_FILE = 'kookai-model-catalog-v1.json';

export function isModelCatalog(value: unknown): value is ModelCatalog {
  if (!value || typeof value !== 'object') return false;
  const catalog = value as Partial<ModelCatalog>;
  if (
    catalog.schema_version !== 1
    || typeof catalog.catalog_version !== 'string'
    || typeof catalog.default_model !== 'string'
    || !Array.isArray(catalog.models)
    || catalog.models.length === 0
  ) {
    return false;
  }

  return catalog.models.every((model) => (
    model
    && typeof model.id === 'string'
    && typeof model.label === 'string'
    && typeof model.description === 'string'
    && ['agy', 'codex', 'claude', 'kimi'].includes(model.provider)
    && ['gemini', 'claude', 'gpt'].includes(model.usage_bucket)
    && typeof model.enabled === 'boolean'
    && model.capabilities
    && Array.isArray(model.capabilities.effort)
    && Array.isArray(model.capabilities.speed)
    && typeof model.capabilities.thinking === 'boolean'
    && typeof model.capabilities.thinking_required === 'boolean'
  ));
}

export async function readCachedModelCatalog(): Promise<ModelCatalog | null> {
  try {
    const cacheFile = new File(Paths.document, CATALOG_CACHE_FILE);
    if (!cacheFile.exists) return null;
    const parsed = JSON.parse(await cacheFile.text());
    return isModelCatalog(parsed) ? parsed : null;
  } catch (error) {
    console.warn('Could not read cached model catalog:', error);
    return null;
  }
}

export async function writeCachedModelCatalog(catalog: ModelCatalog): Promise<void> {
  if (!isModelCatalog(catalog)) return;
  try {
    const cacheFile = new File(Paths.document, CATALOG_CACHE_FILE);
    if (!cacheFile.exists) {
      cacheFile.create({ intermediates: true });
    }
    cacheFile.write(JSON.stringify(catalog));
  } catch (error) {
    console.warn('Could not cache model catalog:', error);
  }
}
