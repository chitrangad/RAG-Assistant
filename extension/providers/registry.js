/**
 * Provider Adapter Registry
 * Loads and provides access to all AI provider adapters.
 */

const PROVIDER_REGISTRY = [];

function registerProvider(provider) {
  PROVIDER_REGISTRY.push(provider);
}

function detectProvider(url) {
  for (const provider of PROVIDER_REGISTRY) {
    if (provider.matches(url)) {
      return provider;
    }
  }
  return null;
}

function getProviderById(id) {
  return PROVIDER_REGISTRY.find(p => p.id === id) || null;
}

function getAllProviders() {
  return PROVIDER_REGISTRY.map(p => ({ id: p.id, name: p.name, urlPattern: p.urlPattern }));
}
