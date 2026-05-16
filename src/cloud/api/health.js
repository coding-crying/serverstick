// ServerStick Cloud API — Health Check

export default function handler(req, res) {
  return res.status(200).json({
    status: 'ok',
    service: 'serverstick-cloud',
    version: '0.1.0',
    endpoints: {
      '/v1/models': 'List available models (proxy + cached fallback)',
      '/v1/key-status': 'Validate API key (never exposes full key)',
      '/v1/register': 'Register a device after first boot',
      '/health': 'This endpoint',
      '/get.sh': 'Bootstrap script (curl | bash)',
    }
  });
}