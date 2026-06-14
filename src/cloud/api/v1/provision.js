// ServerStick Cloud API — Device Provisioning
// Creates a Pangolin site, generates provisioning key + blueprint,
// and returns everything the device needs to connect.
//
// POST /v1/provision
// Body: { device_id, device_name, starter_key, services[] }
// Returns: { site_id, newt_id, newt_secret, resources[] }

const PANGOLIN_API = 'https://api.pangolin.net/v1';

// Service catalog — maps service name to Pangolin resource config
const SERVICE_CATALOG = {
  dash:   { subdomain: 'dash',   port: 8080, name: 'Dashboard' },
  home:   { subdomain: 'home',   port: 3002, name: 'Homepage' },
  pdf:    { subdomain: 'pdf',    port: 8440, name: 'Stirling PDF' },
  bin:    { subdomain: 'bin',    port: 8084, name: 'PrivateBin' },
  drop:   { subdomain: 'drop',   port: 3000, name: 'PairDrop' },
  kuma:   { subdomain: 'kuma',   port: 3001, name: 'Uptime Kuma' },
  rembg:  { subdomain: 'rembg',  port: 7000, name: 'rembg' },
  logs:   { subdomain: 'logs',   port: 8888, name: 'Dozzle' },
  api:    { subdomain: 'api',    port: 8080, name: 'Discovery API' },
};

export default async function handler(req, res) {
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'method not allowed' });
  }

  const { device_id, device_name, starter_key, services } = req.body || {};

  // Validate required fields
  if (!device_id) {
    return res.status(400).json({ error: 'device_id required' });
  }
  if (!device_name) {
    return res.status(400).json({ error: 'device_name required' });
  }

  // Validate device name (Pangolin subdomain-safe)
  const cleanName = device_name.toLowerCase().replace(/[^a-z0-9-]/g, '');
  if (cleanName !== device_name || cleanName.length < 2 || cleanName.length > 20) {
    return res.status(400).json({ 
      error: 'device_name must be 2-20 chars, lowercase alphanumeric + hyphens' 
    });
  }

  // Validate services
  const requestedServices = services || ['dash', 'home', 'pdf'];
  const validServices = requestedServices.filter(s => SERVICE_CATALOG[s]);
  if (validServices.length === 0) {
    return res.status(400).json({ error: 'at least one valid service required' });
  }

  // Get Pangolin API key from env
  const pangolinKey = process.env.PANGOLIN_API_KEY;
  const orgId = process.env.PANGOLIN_ORG_ID || 'org_oz3r7e5oiug17wj';
  const domainId = process.env.PANGOLIN_DOMAIN_ID || 'xf75k3jyq73czxm';

  if (!pangolinKey) {
    return res.status(500).json({ error: 'Pangolin API key not configured' });
  }

  try {
    // Step 1: Create a Pangolin site for this device
    const siteRes = await fetch(`${PANGOLIN_API}/org/${orgId}/site`, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${pangolinKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: cleanName,
        type: 'newt',
      }),
    });

    if (!siteRes.ok) {
      const err = await siteRes.text();
      console.error('Failed to create site:', err);
      return res.status(502).json({ error: 'Failed to create site', details: err });
    }

    const site = await siteRes.json();
    const siteId = site.data?.siteId || site.data?.id;

    // Step 2: Create resources for each service (sub-sub-domain pattern)
    const resources = [];
    for (const svc of validServices) {
      const catalog = SERVICE_CATALOG[svc];
      const subdomain = `${catalog.subdomain}.${cleanName}`;

      // Create HTTP resource
      const resourceRes = await fetch(`${PANGOLIN_API}/org/${orgId}/resource`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${pangolinKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: catalog.name,
          subdomain: subdomain,
          domainId: domainId,
          http: true,
          protocol: 'tcp',
        }),
      });

      if (!resourceRes.ok) {
        console.error(`Failed to create resource ${subdomain}:`, await resourceRes.text());
        continue;
      }

      const resource = await resourceRes.json();
      const resourceId = resource.data?.resourceId;

      // Create target pointing to the site
      await fetch(`${PANGOLIN_API}/resource/${resourceId}/target`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${pangolinKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          siteId: siteId,
          ip: '127.0.0.1',
          port: catalog.port,
          method: 'http',
        }),
      });

      resources.push({
        service: svc,
        subdomain: `${subdomain}.serverstick.com`,
        resourceId,
        port: catalog.port,
      });
    }

    // Step 3: Generate Newt credentials
    // Note: Pangolin provisioning keys are created via dashboard.
    // This is a placeholder that returns site info for now.
    // In production, we'd create a provisioning key via the API
    // and pass it to the device.
    const newtId = site.data?.newtId || '';
    const newtSecret = site.data?.newtSecret || '';

    return res.status(200).json({
      status: 'provisioned',
      device_name: cleanName,
      site_id: siteId,
      newt_id: newtId,
      newt_secret: newtSecret,
      domain: `${cleanName}.serverstick.com`,
      resources,
      tunnel_endpoint: 'gerbil.pangolin.net:50120',
    });

  } catch (err) {
    console.error('Provisioning error:', err);
    return res.status(500).json({ error: 'provisioning failed', details: err.message });
  }
}