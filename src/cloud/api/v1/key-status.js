// ServerStick Cloud API — Key Status Validation
// Validates a starter key against the provider without exposing the key.
//
// GET /v1/key-status?api_key=sk-...
//
// Returns: validity, model count, key prefix (never the full key)

export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key');
    return res.status(204).end();
  }

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'method not allowed' });
  }

  const apiKey = req.query.api_key
    || req.headers['x-api-key']
    || (req.headers.authorization || '').replace('Bearer ', '');

  const apiBase = req.query.api_base || 'https://api.openai.com/v1';

  if (!apiKey) {
    return res.status(400).json({ error: 'api_key required (query param, X-API-Key header, or Bearer token)' });
  }

  // Key prefix — first 8 chars only, never the full key
  const keyPrefix = apiKey.length > 8 ? `${apiKey.slice(0, 8)}...` : '***';

  try {
    const url = `${apiBase.replace(/\/+$/, '')}/v1/models`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const resp = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'User-Agent': 'ServerStick/0.1'
      },
      signal: controller.signal
    });

    clearTimeout(timeout);

    if (resp.ok) {
      const data = await resp.json();
      const modelCount = data?.data?.length || 0;
      return res.status(200).json({
        valid: true,
        key_prefix: keyPrefix,
        models_available: modelCount,
        api_base: apiBase,
        status: 'active'
      });
    }

    // Key is invalid or expired
    const status = resp.status;
    let message = 'unknown error';
    try { const body = await resp.json(); message = body.error?.message || body.message || JSON.stringify(body); } catch {}

    return res.status(200).json({
      valid: false,
      key_prefix: keyPrefix,
      api_base: apiBase,
      status: status === 401 ? 'invalid' : status === 429 ? 'rate_limited' : 'error',
      error: `${status}: ${message}`
    });

  } catch (err) {
    return res.status(200).json({
      valid: null,
      key_prefix: keyPrefix,
      api_base: apiBase,
      status: 'provider_unreachable',
      error: err.message
    });
  }
}