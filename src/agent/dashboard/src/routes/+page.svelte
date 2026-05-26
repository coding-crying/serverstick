<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

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
    health?: {
      healthy: boolean | null;
      message?: string;
    };
  }

  interface Resources {
    cpu?: { usage_percent: number | null; model?: string; cores?: number };
    ram?: { total_mb: number; used_mb: number; available_mb: number; usage_percent: number } | null;
    disks?: Record<string, { total: string; used: string; available: string; usage_percent: string }>;
    containers?: { Name?: string; CPUPerc?: string; MemUsage?: string; MemPerc?: string }[];
  }

  interface Backup {
    filename: string;
    service: string;
    size_mb: number;
    created: string;
  }

  interface NetworkInfo {
    hostname?: string | null;
    ips?: string[];
    wifi_ssid?: string | null;
    dns?: string[];
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

  // New features state
  let resources = $state<Resources>({});
  let healthData: Record<string, { healthy: boolean | null; message?: string }> = $state({});
  let networkInfo = $state<NetworkInfo>({});
  let backups: Backup[] = $state([]);
  let showLogModal = $state(false);
  let logService = $state('');
  let logContent = $state('');
  let logLoading = $state(false);
  let showSettings = $state(false);
  let updatingAll = $state(false);
  let activeTab = $state('services'); // services | settings

  // WebSocket
  let ws: WebSocket | null = $state(null);
  let resourcesInterval: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    await loadStatus();
    await loadHealth();
    await loadResources();
    await loadNetwork();
    connectWebSocket();

    // Refresh resources every 30s
    resourcesInterval = setInterval(loadResources, 30000);
  });

  onDestroy(() => {
    if (ws) ws.close();
    if (resourcesInterval) clearInterval(resourcesInterval);
  });

  function connectWebSocket() {
    try {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${proto}//${location.host}/ws/status`;
      ws = new WebSocket(wsUrl);
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.services) {
            for (const [name, status] of Object.entries(data.services)) {
              const svc = services.find(s => s.name === name);
              if (svc) svc.status = status as any;
            }
          }
          if (data.tunnel) {
            tunnelActive = data.tunnel.active || false;
          }
        } catch {}
      };
      ws.onerror = () => { ws = null; };
    } catch {}
  }

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

  async function loadHealth() {
    try {
      const res = await fetch('/api/health');
      healthData = await res.json();
    } catch {}
  }

  async function loadResources() {
    try {
      const res = await fetch('/api/resources');
      resources = await res.json();
    } catch {}
  }

  async function loadNetwork() {
    try {
      const res = await fetch('/api/network');
      networkInfo = await res.json();
    } catch {}
  }

  async function loadBackups() {
    try {
      const res = await fetch('/api/backups');
      const data = await res.json();
      backups = data.backups || [];
    } catch {}
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
      await loadHealth();
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
      await loadHealth();
    } catch (e) {
      console.error(`Failed to install ${name}:`, e);
    }
    actionLoading[name] = false;
  }

  async function showLogs(name: string) {
    logService = name;
    logLoading = true;
    showLogModal = true;
    logContent = '';
    try {
      const res = await fetch(`/api/services/${name}/logs?lines=200`);
      const data = await res.json();
      logContent = data.logs || 'No logs available';
    } catch {
      logContent = 'Failed to load logs';
    }
    logLoading = false;
  }

  async function refreshLogs() {
    logLoading = true;
    try {
      const res = await fetch(`/api/services/${logService}/logs?lines=200`);
      const data = await res.json();
      logContent = data.logs || 'No logs available';
    } catch {
      logContent = 'Failed to load logs';
    }
    logLoading = false;
  }

  async function createBackup(name: string) {
    actionLoading[name] = true;
    try {
      const res = await fetch(`/api/backup/${name}`, { method: 'POST' });
      if (res.ok) {
        await loadBackups();
      }
    } catch {}
    actionLoading[name] = false;
  }

  async function restoreBackup(name: string, filename: string) {
    if (!confirm(`Restore ${name} from ${filename}? This will stop the service and replace its data.`)) return;
    actionLoading[name] = true;
    try {
      await fetch(`/api/restore/${name}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_file: filename }),
      });
      await loadStatus();
      await loadBackups();
    } catch {}
    actionLoading[name] = false;
  }

  async function deleteBackup(filename: string) {
    if (!confirm(`Delete backup ${filename}?`)) return;
    try {
      await fetch(`/api/backup/${filename}`, { method: 'DELETE' });
      await loadBackups();
    } catch {}
  }

  async function updateService(name: string) {
    actionLoading[name] = true;
    try {
      await fetch(`/api/services/${name}/update`, { method: 'POST' });
      await loadStatus();
      await loadHealth();
    } catch {}
    actionLoading[name] = false;
  }

  async function updateAllServices() {
    updatingAll = true;
    try {
      await fetch('/api/update-all', { method: 'POST' });
      await loadStatus();
      await loadHealth();
    } catch {}
    updatingAll = false;
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

  function healthIcon(name: string): string {
    const h = healthData[name];
    if (!h || h.healthy === null || h.healthy === undefined) return '';
    return h.healthy ? '💚' : '🔴';
  }

  function formatBytes(mb: number): string {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb} MB`;
  }

  $effect(() => {
    if (showSettings) loadBackups();
  });
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
    <!-- Header with tabs -->
    <div class="header">
      <div class="logo">
        <span class="logo-icon">🔌</span>
        <span class="logo-text">ServerStick</span>
        {#if deviceName}
          <span class="device-label">{deviceName}</span>
        {/if}
      </div>
      <div class="nav-tabs">
        <button class="tab" class:active={activeTab === 'services'} onclick={() => activeTab = 'services'}>
          Services
        </button>
        <button class="tab" class:active={activeTab === 'settings'} onclick={() => activeTab = 'settings'}>
          ⚙️ Settings
        </button>
        {#if !provisioned}
          <button class="btn primary" onclick={startSetup}>Setup</button>
        {/if}
      </div>
    </div>

    <!-- Resource Bar -->
    {#if resources.cpu || resources.ram}
      <div class="resource-bar">
        {#if resources.cpu}
          <div class="resource-item">
            <span class="resource-label">CPU</span>
            <div class="progress-bar">
              <div class="progress-fill" class:warn={(resources.cpu.usage_percent ?? 0) > 80} style="width: {resources.cpu.usage_percent ?? 0}%"></div>
            </div>
            <span class="resource-value">{resources.cpu.usage_percent ?? '?'}%</span>
          </div>
        {/if}
        {#if resources.ram}
          <div class="resource-item">
            <span class="resource-label">RAM</span>
            <div class="progress-bar">
              <div class="progress-fill" class:warn={resources.ram.usage_percent > 80} style="width: {resources.ram.usage_percent}%"></div>
            </div>
            <span class="resource-value">{formatBytes(resources.ram.used_mb)} / {formatBytes(resources.ram.total_mb)}</span>
          </div>
        {/if}
        {#if resources.disks?.root}
          <div class="resource-item">
            <span class="resource-label">Disk</span>
            <div class="progress-bar">
              <div class="progress-fill" class:warn={parseInt(resources.disks.root.usage_percent) > 80} style="width: {resources.disks.root.usage_percent}%"></div>
            </div>
            <span class="resource-value">{resources.disks.root.used} / {resources.disks.root.total}</span>
          </div>
        {/if}
        <div class="resource-item tunnel">
          {#if tunnelActive}
            <span class="badge green">● Tunnel Active</span>
            <span class="domain-link">{domain}</span>
          {:else if provisioned}
            <span class="badge orange">● Local Only</span>
          {:else}
            <span class="badge gray">● Not Configured</span>
          {/if}
        </div>
      </div>
    {/if}

    {#if activeTab === 'services'}
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
                    <strong>{svc.display} {healthIcon(svc.name)}</strong>
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
                      <button class="btn small" onclick={() => showLogs(svc.name)} title="View logs">📋</button>
                      <button class="btn small" onclick={() => toggleService(svc.name)} disabled={actionLoading[svc.name]}>
                        {actionLoading[svc.name] ? '...' : 'Stop'}
                      </button>
                    {:else}
                      <button class="btn small primary" onclick={() => toggleService(svc.name)} disabled={actionLoading[svc.name]}>
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
    {:else if activeTab === 'settings'}
      <!-- Settings Page -->
      <div class="settings-page">
        <!-- Device Info -->
        <section class="settings-section">
          <h3>🖥️ Device</h3>
          <div class="settings-row">
            <span>Name</span>
            <strong>{deviceName || 'Not set'}</strong>
          </div>
          <div class="settings-row">
            <span>Domain</span>
            <strong>{domain || '—'}</strong>
          </div>
          {#if networkInfo.hostname}
            <div class="settings-row">
              <span>Hostname</span>
              <strong>{networkInfo.hostname}</strong>
            </div>
          {/if}
        </section>

        <!-- Network -->
        <section class="settings-section">
          <h3>🌐 Network</h3>
          {#if networkInfo.ips?.length}
            <div class="settings-row">
              <span>IP Addresses</span>
              <strong>{networkInfo.ips.join(', ')}</strong>
            </div>
          {/if}
          <div class="settings-row">
            <span>WiFi</span>
            <strong>{networkInfo.wifi_ssid || 'Not connected'}</strong>
          </div>
          {#if networkInfo.dns?.length}
            <div class="settings-row">
              <span>DNS</span>
              <strong>{networkInfo.dns.join(', ')}</strong>
            </div>
          {/if}
          <div class="settings-row">
            <span>Tunnel</span>
            <div>
              {#if tunnelActive}
                <span class="badge green">Active</span>
              {:else}
                <span class="badge orange">Inactive</span>
                <button class="btn small" onclick={() => fetch('/api/tunnel/connect', { method: 'POST' }).then(() => loadStatus())}>
                  Reconnect
                </button>
              {/if}
            </div>
          </div>
        </section>

        <!-- Updates -->
        <section class="settings-section">
          <h3>🔄 Updates</h3>
          <p class="settings-desc">Pull the latest Docker images for all running services.</p>
          <button class="btn primary" onclick={updateAllServices} disabled={updatingAll}>
            {updatingAll ? 'Updating all services...' : 'Update All Services'}
          </button>
        </section>

        <!-- Backups -->
        <section class="settings-section">
          <h3>💾 Backups</h3>
          <div class="backup-grid">
            {#each services.filter(s => s.status?.installed) as svc}
              <div class="backup-row">
                <span>{svc.icon} {svc.display}</span>
                <div class="backup-actions">
                  <button class="btn small" onclick={() => createBackup(svc.name)} disabled={actionLoading[`backup_${svc.name}`]}>
                    Backup
                  </button>
                </div>
              </div>
            {/each}
          </div>

          {#if backups.length > 0}
            <h4 style="margin-top: 16px;">Existing Backups</h4>
            <div class="backup-list">
              {#each backups as bk}
                <div class="backup-item">
                  <div>
                    <strong>{bk.filename}</strong>
                    <small>{bk.size_mb} MB · {new Date(bk.created).toLocaleString()}</small>
                  </div>
                  <div class="backup-actions">
                    <button class="btn small" onclick={() => restoreBackup(bk.service, bk.filename)}>
                      Restore
                    </button>
                    <button class="btn small danger" onclick={() => deleteBackup(bk.filename)}>
                      ✕
                    </button>
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </section>

        <!-- Container Stats -->
        {#if resources.containers?.length}
          <section class="settings-section">
            <h3>📊 Container Stats</h3>
            <div class="container-stats">
              <table>
                <thead>
                  <tr>
                    <th>Container</th>
                    <th>CPU</th>
                    <th>Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {#each resources.containers as c}
                    <tr>
                      <td>{c.Name || '—'}</td>
                      <td>{c.CPUPerc || '—'}</td>
                      <td>{c.MemUsage || '—'} ({c.MemPerc || '—'})</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </section>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<!-- Log Modal -->
{#if showLogModal}
  <div class="modal-overlay" onclick={() => showLogModal = false}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h3>📋 Logs — {logService}</h3>
        <div class="modal-actions">
          <button class="btn small" onclick={refreshLogs} disabled={logLoading}>
            {logLoading ? '...' : 'Refresh'}
          </button>
          <button class="btn small" onclick={() => showLogModal = false}>✕</button>
        </div>
      </div>
      <pre class="log-viewer">{logLoading ? 'Loading...' : logContent}</pre>
    </div>
  </div>
{/if}

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

  /* Header */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 0;
    border-bottom: 1px solid #21262d;
    margin-bottom: 16px;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .logo-icon { font-size: 24px; }
  .logo-text { font-size: 20px; font-weight: 700; color: #f0f6fc; }
  .device-label {
    padding: 2px 8px;
    background: rgba(88, 166, 255, 0.1);
    border: 1px solid rgba(88, 166, 255, 0.3);
    border-radius: 4px;
    font-size: 12px;
    color: #58a6ff;
    font-weight: 500;
  }

  .nav-tabs {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .tab {
    padding: 6px 16px;
    border-radius: 6px;
    border: 1px solid transparent;
    background: transparent;
    color: #8b949e;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
  }

  .tab:hover { color: #c9d1d9; background: #161b22; }
  .tab.active { color: #f0f6fc; background: #21262d; border-color: #30363d; }

  /* Resource Bar */
  .resource-bar {
    display: flex;
    gap: 16px;
    padding: 12px 16px;
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    margin-bottom: 20px;
    align-items: center;
    flex-wrap: wrap;
  }

  .resource-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }

  .resource-item.tunnel { margin-left: auto; }

  .resource-label {
    color: #8b949e;
    font-weight: 500;
    min-width: 32px;
  }

  .resource-value {
    color: #c9d1d9;
    font-size: 12px;
    min-width: 100px;
  }

  .progress-bar {
    width: 80px;
    height: 6px;
    background: #21262d;
    border-radius: 3px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: #238636;
    border-radius: 3px;
    transition: width 0.3s;
  }

  .progress-fill.warn { background: #d29922; }

  .domain-link {
    color: #58a6ff;
    font-size: 13px;
  }

  /* Badges */
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

  h3 {
    font-size: 15px;
    font-weight: 600;
    color: #f0f6fc;
    margin: 0 0 12px;
  }

  /* Service Grid */
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
  .btn.danger { color: #f85149; }
  .btn.danger:hover { background: rgba(248, 81, 73, 0.1); }
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

  /* Settings Page */
  .settings-page {
    max-width: 800px;
  }

  .settings-section {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
  }

  .settings-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #21262d;
    font-size: 14px;
  }

  .settings-row:last-child { border-bottom: none; }
  .settings-row span { color: #8b949e; }
  .settings-row strong { color: #c9d1d9; }

  .settings-desc {
    color: #8b949e;
    font-size: 13px;
    margin: 0 0 12px;
  }

  /* Backups */
  .backup-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .backup-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: #0d1117;
    border-radius: 6px;
    font-size: 13px;
  }

  .backup-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 300px;
    overflow-y: auto;
  }

  .backup-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: #0d1117;
    border-radius: 6px;
    font-size: 13px;
  }

  .backup-item strong { display: block; color: #c9d1d9; font-size: 12px; }
  .backup-item small { color: #6e7681; font-size: 11px; }
  .backup-actions { display: flex; gap: 4px; }

  /* Container Stats Table */
  .container-stats table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  .container-stats th {
    text-align: left;
    padding: 8px;
    color: #8b949e;
    border-bottom: 1px solid #21262d;
    font-weight: 500;
  }

  .container-stats td {
    padding: 8px;
    color: #c9d1d9;
    border-bottom: 1px solid #161b22;
  }

  /* Log Modal */
  .modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    width: 90%;
    max-width: 800px;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid #21262d;
  }

  .modal-header h3 { margin: 0; font-size: 16px; }
  .modal-actions { display: flex; gap: 6px; }

  .log-viewer {
    padding: 16px;
    margin: 0;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 12px;
    line-height: 1.5;
    color: #c9d1d9;
    background: #0d1117;
    overflow-y: auto;
    flex: 1;
    max-height: 60vh;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
