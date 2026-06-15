<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '../lib/api.js';

  const githubIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>`;

  let { subdomain = 'myserver', brain = null } = $props();

  // ─── State ───────────────────────────────────────────────────────
  let services = $state([]);
  let recipes = $state([]);
  let hw = $state({ cpu: { usage: 0, cores: 0 }, ram: { used: 0, total: 0, unit: 'GB' }, disk: { used: 0, total: 0, unit: 'GB' }, temp: null, uptime: '–' });
  let credit = $state({ used: 0, total: 10, currency: '$', provider: 'nanoGPT', period: 'this month' });
  let hermesLogs = $state([]);
  let showAddModal = $state(false);
  let addSearch = $state('');
  let chatInput = $state('');
  let chatMessages = $state([
    { role: 'assistant', text: "Hey! 👋 I'm Hermes, your server assistant. I can help you install apps, check on services, fix issues, or just answer questions. What's up?" }
  ]);
  let chatTyping = $state(false);
  let chatSocket = null;
  let installingRecipe = $state(null);
  let installError = $state('');
  let backendOffline = $state(false);

  // ─── Derived ─────────────────────────────────────────────────────
  let filteredRecipes = $derived(
    addSearch
      ? recipes.filter(r => r.name.toLowerCase().includes(addSearch.toLowerCase()) || r.description.toLowerCase().includes(addSearch.toLowerCase()))
      : recipes
  );
  let recommended = $derived(
    recipes
      .filter(r => r.ram && r.source === 'github')
      .slice(0, 4)
      .map(r => ({ ...r, ram: r.ram || '~200 MB', description: r.description + ' · ' + r.ram }))
  );
  let creditPercent = $derived(Math.max(0, Math.min(100, Math.round((credit.used / credit.total) * 100))));
  let ramPercent = $derived(Math.max(0, Math.min(100, Math.round((hw.ram.used / hw.ram.total) * 100))));
  let diskPercent = $derived(Math.max(0, Math.min(100, Math.round((hw.disk.used / hw.disk.total) * 100))));
  let spareRam = $derived(Math.max(0, +(hw.ram.total - hw.ram.used).toFixed(1)));

  // ─── Data loading ────────────────────────────────────────────────
  async function loadAll() {
    try {
      const [svc, rec, hardware, cred, logs] = await Promise.all([
        api.listServices(),
        api.listRecipes(),
        api.getHardware(),
        api.getCredit(),
        api.getHermesLogs(),
      ]);
      services = svc.services || [];
      recipes = rec.recipes || [];
      hw = hardware;
      credit = cred;
      hermesLogs = logs.logs || [];
      backendOffline = false;
    } catch (err) {
      console.error('load failed:', err);
      backendOffline = true;
    }
  }

  let pollInterval;
  onMount(() => {
    loadAll();
    pollInterval = setInterval(loadAll, 10000);
  });
  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
    if (chatSocket) chatSocket.close();
  });

  // ─── Actions ─────────────────────────────────────────────────────
  function openService(service) {
    window.open('https://' + service.url, '_blank');
  }

  async function toggleService(service) {
    const action = service.status === 'running' ? 'stop' : 'start';
    // Optimistic update
    const prev = service.status;
    service.status = action === 'start' ? 'starting' : 'stopping';
    try {
      await api.serviceAction(service.id, action);
      // Will be refreshed by next poll
    } catch (err) {
      service.status = prev;
      alert(`Failed to ${action} ${service.name}: ${err.message}`);
    }
  }

  function statusClass(status) {
    if (status === 'running' || status === 'starting') return 'status-running';
    if (status === 'error' || status === 'stopping') return 'status-error';
    return 'status-stopped';
  }

  async function installRecipe(recipe) {
    installingRecipe = recipe.id;
    installError = '';
    try {
      await api.installRecipe(recipe.id, recipe.github);
      showAddModal = false;
      // Refresh services after a moment
      setTimeout(loadAll, 5000);
    } catch (err) {
      installError = err.message || 'Install failed';
    } finally {
      installingRecipe = null;
    }
  }

  // ─── Chat (WebSocket) ────────────────────────────────────────────
  function openChatSocket() {
    if (chatSocket && chatSocket.readyState <= 1) return chatSocket;
    const ws = api.openChatSocket();
    ws.onopen = () => { backendOffline = false; };
    ws.onclose = () => {
      // Auto-reconnect after 3s
      setTimeout(() => { if (chatSocket === ws) openChatSocket(); }, 3000);
    };
    ws.onerror = () => { backendOffline = true; };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.error) {
          chatMessages = [...chatMessages, { role: 'assistant', text: `⚠ ${data.error === 'offline' ? "Hermes is offline. Start it from a terminal: nemohermes serverstick start" : data.error}` }];
          chatTyping = false;
        } else if (data.content) {
          // Streaming chunk
          const last = chatMessages[chatMessages.length - 1];
          if (last && last.role === 'assistant' && last.streaming) {
            chatMessages = [...chatMessages.slice(0, -1), { ...last, text: last.text + data.content }];
          } else {
            chatMessages = [...chatMessages, { role: 'assistant', text: data.content, streaming: true }];
          }
        } else if (data.done) {
          const last = chatMessages[chatMessages.length - 1];
          if (last && last.streaming) {
            chatMessages = [...chatMessages.slice(0, -1), { ...last, streaming: false }];
          }
          chatTyping = false;
        }
      } catch (e) {
        // Non-JSON chunk = raw text token
        const last = chatMessages[chatMessages.length - 1];
        if (last && last.role === 'assistant' && last.streaming) {
          chatMessages = [...chatMessages.slice(0, -1), { ...last, text: last.text + event.data }];
        } else {
          chatMessages = [...chatMessages, { role: 'assistant', text: event.data, streaming: true }];
        }
      }
    };
    chatSocket = ws;
    return ws;
  }

  function sendMessage() {
    if (!chatInput.trim()) return;
    const msg = chatInput;
    chatMessages = [...chatMessages, { role: 'user', text: msg }];
    chatInput = '';
    chatTyping = true;

    // Open socket lazily
    const ws = openChatSocket();
    const send = () => ws.send(JSON.stringify({ message: msg }));
    if (ws.readyState === 1) {
      send();
    } else {
      ws.addEventListener('open', send, { once: true });
    }
  }
</script>

<div class="dashboard">
  <!-- Sidebar -->
  <nav class="sidebar">
    <div class="sidebar-brand">
      <span class="brand-icon">🖥️</span>
      <span class="brand-text">ServerStick</span>
    </div>

    <div class="sidebar-nav">
      <button class="nav-item active">
        <span class="nav-icon">📊</span>
        <span>Dashboard</span>
      </button>
      <button class="nav-item">
        <span class="nav-icon">🤖</span>
        <span>Hermes</span>
      </button>
      <button class="nav-item">
        <span class="nav-icon">📁</span>
        <span>Files</span>
      </button>
      <button class="nav-item">
        <span class="nav-icon">⚙️</span>
        <span>Settings</span>
      </button>
    </div>

    <div class="sidebar-stats">
      <div class="mini-stat">
        <span class="mini-label">CPU</span>
        <div class="mini-bar"><div class="mini-fill cpu" style="width: {hw.cpu.usage}%"></div></div>
        <span class="mini-val">{hw.cpu.usage}%</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">RAM</span>
        <div class="mini-bar"><div class="mini-fill ram" style="width: {ramPercent}%"></div></div>
        <span class="mini-val">{ramPercent}%</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Disk</span>
        <div class="mini-bar"><div class="mini-fill disk" style="width: {diskPercent}%"></div></div>
        <span class="mini-val">{diskPercent}%</span>
      </div>
      <div class="mini-stat">
        <span class="mini-label">Temp</span>
        <div class="mini-bar"><div class="mini-fill temp" style="width: {Math.min(hw.temp, 100)}%"></div></div>
        <span class="mini-val">{hw.temp}°</span>
      </div>
    </div>

    <div class="sidebar-credit">
      <span class="credit-label">API Credit · {credit.provider}</span>
      <div class="credit-bar"><div class="credit-fill" style="width: {creditPercent}%"></div></div>
      <span class="credit-val">{credit.currency}{credit.used} / {credit.currency}{credit.total}</span>
    </div>

    <div class="sidebar-footer">
      <div class="server-status">
        <span class="status-dot online"></span>
        <span class="status-text">{hw.uptime}</span>
      </div>
    </div>
  </nav>

  <!-- Main content: two columns -->
  <main class="main">
    <!-- Left: services + logs -->
    <div class="col-services">
      <header class="page-header">
        <h1>Dashboard</h1>
        <button class="btn-sm" onclick={() => showAddModal = true}>+ Add Service</button>
      </header>

      <!-- My services -->
      <section class="services-section">
        <h2 class="section-title">My Services</h2>
        <div class="service-grid">
          {#each services as service (service.id)}
            <div class="svc-tile {statusClass(service.status)}">
              <div class="svc-icon">{service.icon}</div>
              <div class="svc-info">
                <span class="svc-name">{service.name}</span>
                <span class="svc-desc">{service.description}</span>
              </div>
              {#if service.source === 'github'}
                <a href="https://github.com/{service.github}" target="_blank" rel="noreferrer" class="svc-gh" title="View on GitHub">{@html githubIcon}</a>
              {/if}
              <div class="svc-hover">
                <button class="svc-btn" onclick={() => openService(service)}>Open</button>
                <button class="svc-btn secondary" onclick={() => toggleService(service)}>
                  {service.status === 'running' ? 'Stop' : 'Start'}
                </button>
              </div>
            </div>
          {/each}
        </div>
      </section>

      <!-- Divider -->
      <div class="section-divider">
        <span class="divider-label">Suggested for you · {spareRam} {hw.ram.unit} RAM free</span>
      </div>

      <!-- Recommended -->
      <section class="services-section">
        <div class="service-grid">
          {#each recommended as rec (rec.id)}
            <div class="svc-tile rec-tile">
              <div class="svc-icon">{rec.icon}</div>
              <div class="svc-info">
                <span class="svc-name">{rec.name}</span>
                <span class="svc-desc">{rec.description} · {rec.ram}</span>
              </div>
              {#if rec.source === 'github'}
                <a href="https://github.com/{rec.github}" target="_blank" rel="noreferrer" class="svc-gh" title="View on GitHub">{@html githubIcon}</a>
              {/if}
              <button class="btn-install" onclick={() => installRecipe(rec)} disabled={installingRecipe === rec.id}>
                {installingRecipe === rec.id ? 'Installing…' : 'Install'}
              </button>
            </div>
          {/each}
        </div>
      </section>

      <!-- Hermes activity log -->
      <section class="log-section">
        <div class="log-header">
          <h2 class="section-title">🤖 Hermes Activity</h2>
          <span class="log-badge">Live</span>
        </div>
        <div class="hermes-log">
          {#each hermesLogs as log}
            <div class="log-line">
              <span class="log-time">{log.time}</span>
              <span class="log-type {log.type}">{log.type === 'action' ? '⚡' : log.type === 'error' ? '✕' : '›'}</span>
              <span class="log-msg {log.type}">{log.msg}</span>
            </div>
          {/each}
        </div>
      </section>
    </div>

    <!-- Right: chat panel -->
    <div class="col-chat">
      <div class="chat-panel">
        <div class="chat-header">
          <div class="chat-header-left">
            <span class="chat-avatar">🤖</span>
            <div>
              <span class="chat-title">Hermes</span>
              <span class="chat-subtitle">Your server assistant</span>
            </div>
          </div>
          <span class="chat-online" class:offline={backendOffline}>
            <span class="status-dot" class:online={!backendOffline} class:offline-dot={backendOffline}></span>
            {backendOffline ? 'Hermes offline' : 'Online'}
          </span>
        </div>

        <div class="chat-messages">
          {#each chatMessages as msg}
            <div class="chat-msg {msg.role}">
              {#if msg.role === 'assistant'}
                <span class="msg-avatar">🤖</span>
              {/if}
              <div class="msg-bubble {msg.role}">
                {msg.text}
              </div>
            </div>
          {/each}
          {#if chatTyping}
            <div class="chat-msg assistant">
              <span class="msg-avatar">🤖</span>
              <div class="msg-bubble assistant typing">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </div>
            </div>
          {/if}
        </div>

        <div class="chat-suggestions">
          <button class="suggestion-chip" onclick={() => { chatInput = 'What services should I install?'; }}>What should I install?</button>
          <button class="suggestion-chip" onclick={() => { chatInput = 'Is everything running okay?'; }}>Health check</button>
          <button class="suggestion-chip" onclick={() => { chatInput = 'How much RAM do I have free?'; }}>Free RAM?</button>
        </div>

        <form class="chat-input-row" onsubmit={(e) => { e.preventDefault(); sendMessage(); }}>
          <input
            type="text"
            bind:value={chatInput}
            placeholder="Ask Hermes anything..."
            class="chat-input"
          />
          <button type="submit" class="chat-send" disabled={!chatInput.trim()}>↑</button>
        </form>
      </div>
    </div>
  </main>
</div>

<!-- Add service modal -->
{#if showAddModal}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="modal-overlay" onclick={() => showAddModal = false} role="dialog" aria-modal="true" tabindex="-1">
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h2>Add a service</h2>
        <button class="modal-close" onclick={() => showAddModal = false}>✕</button>
      </div>
      <div class="modal-search">
        <input type="text" bind:value={addSearch} placeholder="Search services..." class="search-input" />
      </div>
      <div class="recipe-grid">
        {#each filteredRecipes as recipe (recipe.id)}
          <button class="recipe-card" onclick={() => installRecipe(recipe)} disabled={installingRecipe === recipe.id}>
            <span class="recipe-icon">{recipe.icon}</span>
            <div class="recipe-info">
              <span class="recipe-name">{recipe.name}</span>
              <span class="recipe-desc">{recipe.description}</span>
            </div>
            {#if recipe.source === 'github'}
              <span class="recipe-gh" title="View on GitHub">{@html githubIcon}</span>
            {/if}
            {#if installingRecipe === recipe.id}
              <span class="installing-spinner">…</span>
            {/if}
          </button>
        {/each}
      </div>
      {#if installError}
        <p class="install-error">⚠ {installError}</p>
      {/if}
      {#if filteredRecipes.length === 0}
        <div class="no-results">
          <p>No services match "{addSearch}"</p>
          <p class="no-results-hint">More recipes coming soon via Hermes</p>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .dashboard {
    display: flex;
    min-height: 100vh;
    background: var(--bg);
  }

  /* === Sidebar === */
  .sidebar {
    width: 220px;
    background: var(--bg-card);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }

  .sidebar-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 20px 18px;
    border-bottom: 1px solid var(--border);
  }

  .brand-icon { font-size: 22px; }

  .brand-text {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-heading);
  }

  .sidebar-nav {
    padding: 10px 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    background: none;
    color: var(--text-dim);
    font-size: 14px;
    padding: 10px 14px;
    border-radius: 8px;
    text-align: left;
    transition: background 0.15s, color 0.15s;
  }

  .nav-item:hover {
    background: var(--bg-card-hover);
    color: var(--text);
  }

  .nav-item.active {
    background: var(--accent-glow);
    color: var(--accent-strong);
  }

  .nav-icon {
    font-size: 16px;
    width: 22px;
    text-align: center;
  }

  .sidebar-stats {
    padding: 14px 16px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .mini-stat {
    display: grid;
    grid-template-columns: 34px 1fr 32px;
    align-items: center;
    gap: 6px;
  }

  .mini-label {
    font-size: 11px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.3px;
    font-weight: 500;
  }

  .mini-bar {
    height: 3px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }

  .mini-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.6s ease;
  }

  .mini-fill.cpu { background: var(--accent); }
  .mini-fill.ram { background: #8b5cf6; }
  .mini-fill.disk { background: #60a5fa; }
  .mini-fill.temp { background: var(--green); }

  .mini-val {
    font-size: 11px;
    color: var(--text-dim);
    font-family: var(--mono);
    text-align: right;
  }

  .sidebar-credit {
    padding: 12px 16px;
    border-top: 1px solid var(--border);
  }

  .credit-label {
    display: block;
    font-size: 11px;
    color: var(--text-dim);
    margin-bottom: 6px;
  }

  .credit-bar {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 4px;
  }

  .credit-fill {
    height: 100%;
    border-radius: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent-strong));
    box-shadow: 0 0 6px var(--accent-glow);
    transition: width 0.6s ease;
  }

  .credit-val {
    font-size: 11px;
    color: var(--text-dim);
    font-family: var(--mono);
  }

  .sidebar-footer {
    margin-top: auto;
    padding: 14px 18px;
    border-top: 1px solid var(--border);
  }

  .server-status {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }

  .status-dot.online {
    background: var(--green);
    box-shadow: 0 0 6px var(--green-glow);
  }

  .status-text {
    font-size: 12px;
    color: var(--text-dim);
  }

  /* === Main area: two columns === */
  .main {
    flex: 1;
    display: flex;
    min-width: 0;
  }

  .col-services {
    flex: 1;
    overflow-y: auto;
    padding: 0 28px 32px;
    min-width: 0;
  }

  .col-chat {
    width: 380px;
    flex-shrink: 0;
    border-left: 1px solid var(--border);
  }

  /* === Page header === */
  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 0;
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 10;
  }

  .page-header h1 {
    font-size: 22px;
    font-weight: 600;
  }

  .btn-sm {
    background: var(--accent);
    color: #fff;
    font-size: 13px;
    font-weight: 500;
    padding: 7px 18px;
    border-radius: 8px;
    transition: background 0.15s;
  }

  .btn-sm:hover { background: #8b7ff5; }

  /* === Services grid === */
  .services-section {
    margin-bottom: 8px;
  }

  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-heading);
    margin-bottom: 14px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  .service-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
  }

  .svc-tile {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 22px 14px 16px;
    background: var(--bg-card);
    border: 2px solid var(--border);
    border-radius: 14px;
    cursor: pointer;
    transition: border-color 0.25s, background 0.2s, box-shadow 0.25s;
  }

  .svc-tile.status-running {
    border-color: var(--green);
    box-shadow: 0 0 16px var(--green-glow);
  }

  .svc-tile.status-stopped {
    border-color: var(--border);
    opacity: 0.5;
  }

  .svc-tile.status-error {
    border-color: #ef4444;
    box-shadow: 0 0 16px rgba(239, 68, 68, 0.2);
  }

  .svc-tile:hover { background: var(--bg-card-hover); }
  .svc-tile.status-stopped:hover { opacity: 0.7; }

  .svc-icon { font-size: 36px; margin-bottom: 10px; }
  .svc-info { text-align: center; }

  .svc-name {
    display: block;
    font-size: 14px;
    font-weight: 600;
    color: var(--text-heading);
  }

  .svc-desc {
    display: block;
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 3px;
  }

  .svc-gh {
    position: absolute;
    top: 8px;
    right: 8px;
    display: flex;
    align-items: center;
    color: var(--text-dim);
    opacity: 0;
    transition: opacity 0.15s, color 0.15s;
    padding: 3px;
  }

  .svc-tile:hover .svc-gh { opacity: 1; }
  .svc-gh:hover { color: var(--text-heading); }

  .svc-hover {
    display: flex;
    gap: 6px;
    margin-top: 12px;
    opacity: 0;
    transition: opacity 0.15s;
  }

  .svc-tile:hover .svc-hover { opacity: 1; }

  .svc-btn {
    background: var(--accent);
    color: #fff;
    font-size: 11px;
    font-weight: 500;
    padding: 4px 14px;
    border-radius: 6px;
    transition: background 0.15s;
  }

  .svc-btn:hover { background: #8b7ff5; }

  .svc-btn.secondary {
    background: var(--bg-input);
    color: var(--text-dim);
    border: 1px solid var(--border);
  }

  .svc-btn.secondary:hover {
    border-color: #3a3a50;
    color: var(--text);
  }

  /* Recommended tiles */
  .rec-tile {
    border: 2px dashed var(--border) !important;
    box-shadow: none !important;
    opacity: 1 !important;
  }

  .rec-tile:hover {
    border-color: var(--accent) !important;
    background: var(--accent-glow) !important;
    box-shadow: 0 0 16px var(--accent-glow) !important;
  }

  .btn-install {
    margin-top: 10px;
    background: var(--accent);
    color: #fff;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 18px;
    border-radius: 6px;
    opacity: 0;
    transition: background 0.15s, opacity 0.15s;
  }

  .rec-tile:hover .btn-install { opacity: 1; }
  .btn-install:hover { background: #8b7ff5; }

  /* Section divider */
  .section-divider {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 20px 0;
  }

  .section-divider::before,
  .section-divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .divider-label {
    font-size: 12px;
    color: var(--text-dim);
    white-space: nowrap;
    font-weight: 500;
  }

  /* === Hermes activity log === */
  .log-section {
    margin-top: 20px;
  }

  .log-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }

  .log-header .section-title { margin-bottom: 0; }

  .log-badge {
    font-size: 10px;
    color: var(--green);
    background: var(--green-glow);
    padding: 2px 8px;
    border-radius: 100px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .hermes-log {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.75;
    max-height: 200px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .log-line {
    display: flex;
    gap: 8px;
  }

  .log-time { color: var(--text-dim); opacity: 0.4; flex-shrink: 0; }

  .log-type { width: 14px; text-align: center; flex-shrink: 0; }
  .log-type.action { color: var(--accent-strong); }
  .log-type.error { color: #ef4444; }
  .log-type.info { color: var(--text-dim); }

  .log-msg { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .log-msg.error { color: #f87171; }
  .log-msg.action { color: var(--accent-strong); }

  /* === Chat panel === */
  .chat-panel {
    display: flex;
    flex-direction: column;
    height: 100vh;
    background: var(--bg-card);
  }

  .chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 18px;
    border-bottom: 1px solid var(--border);
  }

  .chat-header-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .chat-avatar {
    font-size: 26px;
  }

  .chat-title {
    display: block;
    font-size: 15px;
    font-weight: 600;
    color: var(--text-heading);
  }

  .chat-subtitle {
    display: block;
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 1px;
  }

  .chat-online {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--green);
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 18px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .chat-msg {
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }

  .chat-msg.user {
    flex-direction: row-reverse;
  }

  .msg-avatar {
    font-size: 20px;
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .msg-bubble {
    max-width: 80%;
    font-size: 13px;
    line-height: 1.55;
    padding: 10px 14px;
    border-radius: 14px;
  }

  .msg-bubble.user {
    background: var(--accent);
    color: #fff;
    border-bottom-right-radius: 4px;
  }

  .msg-bubble.assistant {
    background: var(--bg-input);
    color: var(--text);
    border-bottom-left-radius: 4px;
  }

  /* Typing indicator */
  .msg-bubble.typing {
    display: flex;
    gap: 4px;
    padding: 12px 16px;
    align-items: center;
  }

  .dot {
    width: 6px;
    height: 6px;
    background: var(--text-dim);
    border-radius: 50%;
    animation: dotPulse 1.4s ease-in-out infinite;
  }

  .dot:nth-child(2) { animation-delay: 0.2s; }
  .dot:nth-child(3) { animation-delay: 0.4s; }

  @keyframes dotPulse {
    0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1); }
  }

  /* Suggestion chips */
  .chat-suggestions {
    display: flex;
    gap: 6px;
    padding: 0 16px 8px;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .suggestion-chip {
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 12px;
    padding: 5px 12px;
    border-radius: 100px;
    white-space: nowrap;
    transition: border-color 0.15s, color 0.15s, background 0.15s;
  }

  .suggestion-chip:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
    background: var(--accent-glow);
  }

  /* Chat input */
  .chat-input-row {
    display: flex;
    gap: 8px;
    padding: 12px 16px;
    border-top: 1px solid var(--border);
  }

  .chat-input {
    flex: 1;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-heading);
    font-size: 13px;
    padding: 10px 14px;
    transition: border-color 0.2s;
  }

  .chat-input:focus { border-color: var(--border-active); }
  .chat-input::placeholder { color: var(--text-dim); opacity: 0.5; }

  .chat-send {
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--accent);
    color: #fff;
    font-size: 16px;
    font-weight: 600;
    border-radius: 10px;
    transition: background 0.15s, opacity 0.15s;
  }

  .chat-send:hover { background: #8b7ff5; }
  .chat-send:disabled { opacity: 0.35; cursor: not-allowed; }

  /* === Modal === */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
    animation: fadeIn 0.15s ease-out;
  }

  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

  .modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 18px;
    width: 580px;
    max-width: 95vw;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
    animation: slideUp 0.2s ease-out;
  }

  @keyframes slideUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 24px;
    border-bottom: 1px solid var(--border);
  }

  .modal-header h2 { font-size: 18px; }

  .modal-close {
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    color: var(--text-dim);
    font-size: 18px;
    border-radius: 6px;
    transition: background 0.15s, color 0.15s;
  }

  .modal-close:hover {
    background: var(--bg-card-hover);
    color: var(--text);
  }

  .modal-search {
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
  }

  .search-input {
    width: 100%;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-heading);
    font-size: 14px;
    padding: 10px 14px;
    transition: border-color 0.2s;
  }

  .search-input:focus { border-color: var(--border-active); }
  .search-input::placeholder { color: var(--text-dim); opacity: 0.5; }

  .recipe-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    padding: 20px 24px;
    overflow-y: auto;
    flex: 1;
  }

  .recipe-card {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    text-align: left;
    transition: border-color 0.2s, background 0.2s;
  }

  .recipe-card:hover {
    border-color: var(--accent);
    background: var(--accent-glow);
  }

  .recipe-icon { font-size: 24px; flex-shrink: 0; }

  .recipe-info { flex: 1; min-width: 0; }

  .recipe-name {
    display: block;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-heading);
  }

  .recipe-desc {
    display: block;
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .recipe-gh {
    display: flex;
    color: var(--text-dim);
    flex-shrink: 0;
    transition: color 0.15s;
  }

  .recipe-card:hover .recipe-gh { color: var(--text); }

  .no-results {
    padding: 32px 24px;
    text-align: center;
    color: var(--text-dim);
    font-size: 14px;
  }

  .no-results-hint {
    font-size: 12px;
    margin-top: 6px;
    opacity: 0.6;
  }

  .install-error {
    color: #ef4444;
    font-size: 13px;
    padding: 8px 20px;
    margin: 0;
  }

  .chat-online.offline {
    color: #f59e0b;
  }

  .status-dot.offline-dot {
    background: #f59e0b;
    box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
  }

  .installing-spinner {
    color: var(--accent);
    font-weight: bold;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
