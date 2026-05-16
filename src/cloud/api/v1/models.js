// ServerStick Cloud API — Model Discovery
// Proxies /v1/models to the provider, falls back to cached model list.
//
// GET /v1/models?api_key=sk-...&api_base=https://api.openai.com/v1
// GET /v1/models  (uses default provider)
//
// Fallback chain:
//   1. Proxy the device's key to the provider → return live models
//   2. If provider unreachable → return cached model list (updated every 10 min)
//   3. If no cache → return hardcoded fallback list

export default async function handler(req, res) {
  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key');
    return res.status(204).end();
  }

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'method not allowed' });
  }

  // Extract key from query param, X-API-Key header, or Authorization header
  const apiKey = req.query.api_key
    || req.headers['x-api-key']
    || (req.headers.authorization || '').replace('Bearer ', '');

  const apiBase = req.query.api_base || 'https://api.openai.com/v1';

  // If no key provided, serve cached models immediately
  if (!apiKey) {
    return res.status(200).json({
      object: 'list',
      source: 'cache',
      data: getCachedModels(),
      notice: 'No API key provided; returning cached model list. Pass api_key or X-API-Key header for live results.'
    });
  }

  // Attempt 1: Proxy to provider with the device's key
  try {
    const models = await fetchFromProvider(apiKey, apiBase);
    if (models && models.data && models.data.length > 0) {
      // Update cache in background (non-blocking)
      updateCache(models);
      return res.status(200).json({
        ...models,
        source: 'live'
      });
    }
  } catch (err) {
    console.error(`[models] Provider fetch failed: ${err.message}`);
  }

  // Attempt 2: Return cached models
  const cached = getCachedModels();
  if (cached.length > 0) {
    return res.status(200).json({
      object: 'list',
      source: 'cache',
      data: cached,
      notice: 'Provider unreachable; returning cached model list.'
    });
  }

  // Attempt 3: Hardcoded fallback
  return res.status(200).json({
    object: 'list',
    source: 'fallback',
    data: HARDCODED_FALLBACK,
    notice: 'Provider unreachable and no cache; returning hardcoded fallback list.'
  });
}


// ─── Provider Proxy ────────────────────────────────────────────────────────

async function fetchFromProvider(apiKey, apiBase) {
  const url = `${apiBase.replace(/\/+$/, '')}/v1/models`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);

  try {
    const resp = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'User-Agent': 'ServerStick/0.1'
      },
      signal: controller.signal
    });

    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200)}`);
    }

    return await resp.json();
  } finally {
    clearTimeout(timeout);
  }
}


// ─── Model Cache ────────────────────────────────────────────────────────────
// In-memory cache, refreshed by successful provider queries.
// Survives cold starts by falling back to HARDCODED_FALLBACK.

let cachedModels = null;
let cacheTimestamp = 0;
const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

function getCachedModels() {
  // Return cache if fresh
  if (cachedModels && (Date.now() - cacheTimestamp) < CACHE_TTL) {
    return cachedModels;
  }
  return cachedModels || HARDCODED_FALLBACK;
}

function updateCache(modelsResponse) {
  if (modelsResponse?.data?.length) {
    cachedModels = modelsResponse.data;
    cacheTimestamp = Date.now();
  }
}


// ─── Hardcoded Fallback ────────────────────────────────────────────────────
// The models we know exist. Updated manually or by cache warming.
// This is the last resort — if the provider is down AND we have no cache.

const HARDCODED_FALLBACK = [
  { id: 'gpt-4o', object: 'model', created: 1715369242, owned_by: 'system' },
  { id: 'gpt-4o-mini', object: 'model', created: 1721172741, owned_by: 'system' },
  { id: 'gpt-4-turbo', object: 'model', created: 1706037779, owned_by: 'system' },
  { id: 'gpt-3.5-turbo', object: 'model', created: 1677610602, owned_by: 'system' },
  { id: 'o1', object: 'model', created: 1725648979, owned_by: 'system' },
  { id: 'o1-mini', object: 'model', created: 1725648979, owned_by: 'system' },
  { id: 'o3-mini', object: 'model', created: 1727264579, owned_by: 'system' },
  { id: 'claude-sonnet-4-20250514', object: 'model', created: 1715648000, owned_by: 'anthropic' },
  { id: 'claude-haiku-3-5-20241022', object: 'model', created: 1729554000, owned_by: 'anthropic' },
  { id: 'deepseek-chat', object: 'model', created: 1707800000, owned_by: 'deepseek' },
  { id: 'deepseek-reasoner', object: 'model', created: 1707800000, owned_by: 'deepseek' },
  { id: 'glm-5.1', object: 'model', created: 1717000000, owned_by: 'zhipu' },
];