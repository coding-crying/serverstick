// ServerStick Cloud API — Device Registration
// A stick pings this endpoint after first boot to register itself.
// No auth required — this is a registration beacon, not a secure endpoint.
//
// POST /v1/register
// Body: { device_id, hardware_info, starter_key_prefix, os_version }
//
// In v0.1 this is a simple beacon. v2 will integrate with Pangolin provisioning
// and assign subdomains (e.g., jack.serverstick.com).

const registrations = new Map();

export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'method not allowed' });
  }

  const { device_id, hardware_info, starter_key_prefix, os_version } = req.body || {};

  if (!device_id) {
    return res.status(400).json({ error: 'device_id required' });
  }

  // Deduplicate — only store latest registration per device
  const existing = registrations.get(device_id);
  const registration = {
    device_id,
    hardware_info: hardware_info || null,
    starter_key_prefix: starter_key_prefix || null,
    os_version: os_version || null,
    first_seen: existing?.first_seen || new Date().toISOString(),
    last_seen: new Date().toISOString(),
    ping_count: (existing?.ping_count || 0) + 1,
  };

  registrations.set(device_id, registration);

  // In v0.1, just acknowledge. v2 returns Pangolin provisioning token.
  return res.status(200).json({
    status: 'registered',
    device_id,
    message: 'Device registered. Tunnel provisioning coming in v2.',
    // v2 will add: tunnel_token, subdomain, pangolin_endpoint
  });
}