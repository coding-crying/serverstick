<script lang="ts">
  import { onMount } from 'svelte';

  interface Service {
    name: string;
    display: string;
    replaces: string;
    icon: string;
    category: string;
    description: string;
    docker: {
      image: string;
      port: number;
    };
    pangolin?: {
      subdomain: string;
    };
    status?: {
      installed: boolean;
      running: boolean;
      status: string;
    };
  }

  let services: Service[] = $state([]);
  let loading = $state(true);
  let error = $state('');
  let deviceName = $state('');
  let provisioned = $state(false);
  let domain = $state('');
  let tunnelActive = $state(false);

  // Setup wizard state
  let showSetup = $state(false);
  let setupStep = $state(0);
  let selectedServices = $state<string[]>([]);
  let setupError = $state('');
  let setupRunning = $state(false);
  let starterKey = $state('');

  // Service action loading states
  let actionLoading: Record<string, boolean> = $state({});

  onMount(async () => {
    await loadStatus();
  });

  async function loadStatus() {
    loading = true;
    error = '';
    try {
      const [statusRes, servicesRes] = await Promise.all([
        fetch('/api/status'),
        fetch('/api/services')
      ]);
      const statusData = await statusRes.json();
      const servicesData = await servicesRes.json();

      deviceName = statusData.device_name || '';
      provisioned = statusData.provisioned || false;
      domain = statusData.tunnel?.domain || '';
      tunnelActive = statusData.tunnel?.active || false;

      services = Object.values(servicesData).map((s: any) => ({
        ...s,
        status: statusData.services?.[s.name] || { installed: false, running: false, status: 'unknown' }
      }));
    } catch (e) {
      error = 'Could not connect to agent. Is the ServerStick running?';
    }
    loading = false;
  }

  async function toggleService(name: string) {
    const svc = services.find(s => s.name === name);
    if (!svc) return;
    actionLoading[name] = true;
    const action = svc.status?.running ? 'stop' : 'start';
    try {
      const res = await fetch(`/api/services/${name}/${action}`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json();
        console.error(`Failed to ${action} ${name}:`, data.detail || data);
      }
      await loadStatus();
    } catch (e) {
      console.error(`Failed to ${action} ${name}:`, e);
    }
    actionLoading[name] = false;
  }

  async function installService(name: string) {
    actionLoading[name] = true;
    try {
      await fetch(`/api/services/${name}/install`, { method: 'POST' });
      await loadStatus();
    } catch (e) {
      console.error(`Failed to install ${name}:`, e);
    }
    actionLoading[name] = false;
  }

  async function runSetup() {
    setupRunning = true;
    setupError = '';
    try {
      const res = await fetch('/api/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_name: deviceName,
          services: selectedServices,
          starter_key: starterKey || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setupError = data.detail || 'Setup failed';
      } else {
        provisioned = true;
        domain = data.domain || '';
        if (data.tunnel_warning) {
          setupError = data.tunnel_warning;
        }
        setupStep = 2;
        await loadStatus();
      }
    } catch (e) {
      setupError = 'Could not reach agent for setup.';
    }
    setupRunning = false;
  }

  function startSetup() {
    if (!provisioned) {
      showSetup = true;
      setupStep = 0;
      // Try to read starter key from URL params
      const params = new URLSearchParams(window.location.search);
      if (params.get('key')) {
        starterKey = params.get('key')!;
      }
    }
  }

  const categories = [
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'documents', label: 'Documents' },
    { key: 'sharing', label: 'Sharing' },
    { key: 'media', label: 'Media' },
    { key: 'monitoring', label: 'Monitoring' },
    { key: 'system', label: 'System' },
  ];

  function categoryIcon(key: string): string {
    const icons: Record<string, string> = {
      dashboard: '📊', documents: '📄', sharing: '🔄',
      media: '🖼️', monitoring: '📈', system: '⚙️',
    };
    return icons[key] || '📦';
  }
</script>

<div class="app">
  {#if loading}
    <div class="loading">
      <div class="spinner"></div>
      <p>Loading services...</p>
    </div>
  {:else if error && !services.length}
    <div class="error-box">
      <p>⚠️ {error}</p>
      <button class="btn primary" onclick={loadStatus}>Retry</button>
    </div>
  {:else if showSetup}
    <!-- Setup Wizard -->
    <div class="setup-wizard">
      {#if setupStep === 0}
        <h2>🖥️ Name Your Device</h2>
        <p>Choose a name for your ServerStick. This becomes your subdomain.</p>
        <p class="hint"><strong>{deviceName || 'nick'}</strong>.serverstick.com<br/>
        Services will be at pdf.nick.serverstick.com, home.nick.serverstick.com, etc.</p>
        <input
          type="text"
          bind:value={deviceName}
          placeholder="e.g. nick, office, basement"
          maxlength="20"
          pattern="[a-z0-9-]+"
        />
        <label class="field">
          Starter Key <small>(auto-filled from USB)</small>
          <input
            type="text"
            bind:value={starterKey}
            placeholder="Leave blank if key is embedded"
          />
        </label>
        <div class="wizard-actions">
          <button class="btn primary" onclick={() => setupStep = 1} disabled={!deviceName || deviceName.length < 2}>
            Next →
          </button>
        </div>
      {:else if setupStep === 1}
        <h2>📦 Select Services</h2>
        <p>Choose which services to install. You can add more later.</p>
        <div class="service-grid">
          {#each services.filter(s => s.category !== 'system') as svc}
            <label class="service-card clickable" class:selected={selectedServices.includes(svc.name)}>
              <input
                type="checkbox"
                checked={selectedServices.includes(svc.name)}
                onchange={() => {
                  if (selectedServices.includes(svc.name)) {
                    selectedServices = selectedServices.filter(n => n !== svc.name);
                  } else {
                    selectedServices = [...selectedServices, svc.name];
                  }
                }}
              />
              <span class="icon">{svc.icon}</span>
              <strong>{svc.display}</strong>
              <small>Replaces {svc.replaces}</small>
            </label>
          {/each}
        </div>
        <div class="wizard-actions">
          <button class="btn" onclick={() => setupStep = 0}>← Back</button>
          <button class="btn primary" onclick={runSetup} disabled={selectedServices.length === 0 || setupRunning}>
            {setupRunning ? 'Installing...' : `Install ${selectedServices.length} services`}
          </button>
        </div>
        {#if setupError}
          <p class="error-msg">{setupError}</p>
        {/if}
      {:else if setupStep === 2}
        <h2>🎉 All Set!</h2>
        <p>Your ServerStick is configured and running.</p>
        {#if domain}
          <p>Your dashboard: <a href="https://{domain}" target="_blank" rel="noopener">https://{domain}</a></p>
        {/if}
        {#if setupError}
          <p class="warning-msg">⚠️ {setupError}</p>
        {/if}
        <button class="btn primary" onclick={() => { showSetup = false; loadStatus(); }}>
          Go to Dashboard
        </button>
      {/if}
    </div>
  {:else}
    <!-- Status bar -->
    <div class="status-bar">
      <div class="tunnel-status">
        {#if tunnelActive}
          <span class="badge green">● Tunnel Active</span>
          <span class="domain-link">{domain}</span>
        {:else if provisioned}
          <span class="badge orange">● Local Only</span>
          <span class="domain-link">{domain || deviceName + '.serverstick.com'}</span>
        {:else}
          <span class="badge orange">● Not Configured</span>
          <button class="btn primary" onclick={startSetup}>Setup</button>
        {/if}
      </div>
    </div>

    <!-- Service Grid -->
    {#each categories.filter(c => services.some(s => s.category === c.key)) as cat}
      <section>
        <h2>{categoryIcon(cat.key)} {cat.label}</h2>
        <div class="service-grid">
          {#each services.filter(s => s.category === cat.key) as svc}
            <div class="service-card" class:running={svc.status?.running} class:stopped={svc.status?.installed && !svc.status?.running} class:not-installed={!svc.status?.installed}>
              <div class="service-header">
                <span class="icon">{svc.icon}</span>
                <div>
                  <strong>{svc.display}</strong>
                  {#if svc.pangolin && deviceName}
                    <small class="url">{svc.pangolin.subdomain}.{deviceName}.serverstick.com</small>
                  {:else if svc.docker?.port && svc.status?.running}
                    <small class="url">localhost:{svc.docker.port}</small>
                  {/if}
                </div>
              </div>
              <p>{svc.description}</p>
              <div class="service-footer">
                <span class="badge" class:green={svc.status?.running} class:orange={svc.status?.installed && !svc.status?.running} class:gray={!svc.status?.installed}>
                  {svc.status?.running ? '● Running' : svc.status?.installed ? '● Stopped' : '○ Available'}
                </span>
                <div class="service-actions">
                  {#if !svc.status?.installed}
                    <button class="btn small primary" onclick={() => installService(svc.name)} disabled={actionLoading[svc.name]}>
                      {actionLoading[svc.name] ? '...' : 'Install'}
                    </button>
                  {:else if svc.status?.running}
                    {#if svc.pangolin && deviceName}
                      <a href="https://{svc.pangolin.subdomain}.{deviceName}.serverstick.com" target="_blank" rel="noopener" class="btn small">Open ↗</a>
                    {:else if svc.docker?.port}
                      <a href="http://{deviceName || 'localhost'}:{svc.docker.port}" target="_blank" rel="noopener" class="btn small">Open ↗</a>
                    {/if}
                    <button class="btn small" onclick={() => toggleService(svc.name)} disabled={actionLoading[svc.name]}>
                      {actionLoading[svc.name] ? '...' : 'Stop'}
                    </button>
                  {:else}
                    <button class="btn small" onclick={() => toggleService(svc.name)} disabled={actionLoading[svc.name]}>
                      {actionLoading[svc.name] ? '...' : 'Start'}
                    </button>
                  {/if}
                </div>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/each}
  {/if}
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e1e4e8;
  }

  .app {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 24px 48px;
  }

  .status-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 0;
    border-bottom: 1px solid #21262d;
    margin-bottom: 24px;
  }

  .tunnel-status {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .domain-link {
    color: #58a6ff;
    font-size: 14px;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }

  .badge.green { color: #3fb950; background: rgba(63, 185, 80, 0.1); }
  .badge.orange { color: #d29922; background: rgba(210, 153, 34, 0.1); }
  .badge.gray { color: #8b949e; background: rgba(139, 148, 158, 0.1); }

  h2 {
    font-size: 16px;
    font-weight: 600;
    color: #c9d1d9;
    margin: 24px 0 12px;
  }

  .service-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 12px;
  }

  .service-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 16px;
    transition: border-color 0.2s;
  }

  .service-card.running { border-color: #238636; }
  .service-card.stopped { border-color: #d29922; }
  .service-card.clickable { cursor: pointer; }
  .service-card.clickable:hover { border-color: #58a6ff; }
  .service-card.selected { border-color: #58a6ff; background: rgba(88, 166, 255, 0.05); }

  .service-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .service-header .icon { font-size: 24px; }
  .service-header strong { display: block; font-size: 14px; }
  .service-header .url { color: #58a6ff; font-size: 12px; }

  .service-card p {
    color: #8b949e;
    font-size: 13px;
    margin: 0 0 12px;
    line-height: 1.4;
  }

  .service-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .service-actions {
    display: flex;
    gap: 6px;
  }

  .btn {
    padding: 6px 16px;
    border-radius: 6px;
    border: 1px solid #30363d;
    background: #21262d;
    color: #c9d1d9;
    font-size: 13px;
    cursor: pointer;
    transition: background 0.2s;
  }

  .btn:hover { background: #30363d; }
  .btn.primary { background: #238636; border-color: #238636; color: white; }
  .btn.primary:hover { background: #2ea043; }
  .btn.primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn.small { padding: 4px 10px; font-size: 12px; }
  .btn:disabled { opacity: 0.5; }

  a.btn { text-decoration: none; }

  /* Setup wizard */
  .setup-wizard {
    max-width: 600px;
    margin: 40px auto;
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 32px;
  }

  .setup-wizard h2 { margin: 0 0 16px; font-size: 22px; color: #f0f6fc; }
  .setup-wizard p { color: #8b949e; font-size: 14px; line-height: 1.6; margin-bottom: 16px; }

  .hint { color: #58a6ff !important; font-size: 13px !important; }

  .field { display: block; margin-bottom: 12px; color: #8b949e; font-size: 12px; }
  .field small { color: #6e7681; }

  input[type="text"] {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid #30363d;
    border-radius: 6px;
    background: #0d1117;
    color: #f0f6fc;
    font-size: 16px;
    margin-bottom: 12px;
  }

  input[type="text"]:focus { border-color: #58a6ff; outline: none; }

  .wizard-actions { display: flex; justify-content: space-between; margin-top: 24px; }

  .error-msg { color: #f85149 !important; }
  .warning-msg { color: #d29922 !important; }

  .loading, .error-box {
    text-align: center;
    padding: 48px;
    color: #8b949e;
  }

  .spinner {
    width: 32px;
    height: 32px;
    border: 3px solid #21262d;
    border-top-color: #58a6ff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 16px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  section { margin-bottom: 8px; }
</style>