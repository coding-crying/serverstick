<script>
  import { api } from '../lib/api.js';

  let subdomain = $state('');
  let wireguardOpen = $state(false);
  let submitting = $state(false);
  let submitError = $state('');

  const exampleServices = [
    { icon: '📸', name: 'photos' },
    { icon: '📁', name: 'files' },
    { icon: '🤖', name: 'hermes' },
    { icon: '📊', name: 'dashboard' },
    { icon: '🎬', name: 'media' },
    { icon: '📝', name: 'notes' },
  ];

  let serverName = $derived(subdomain || 'myserver');

  let { onnext, initialSubdomain = '' } = $props();
  if (initialSubdomain) subdomain = initialSubdomain;

  async function handleContinue() {
    if (!subdomain.trim() || submitting) return;
    submitting = true;
    submitError = '';
    try {
      const result = await api.onboardSubdomain(subdomain.trim().toLowerCase());
      onnext(subdomain.trim().toLowerCase(), result);
    } catch (err) {
      submitError = err.message || 'Failed to register subdomain';
    } finally {
      submitting = false;
    }
  }
</script>

<div class="welcome-content">
  <h1>Welcome to your server</h1>
  <p class="subtitle">To make it useful, you need a way to access it when you're away.</p>

  <!-- Main ServerStick card -->
  <div class="main-card serverstick-card">
    <div class="card-badge">✨ Recommended</div>
    <div class="card-header">
      <span class="card-icon">🌐</span>
      <h2>Register with ServerStick.com</h2>
    </div>

    <div class="domain-setup">
      <span class="domain-label">Your server will live at:</span>
      <div class="domain-field">
        <input
          type="text"
          bind:value={subdomain}
          placeholder="myserver"
          class="subdomain-input"
          maxlength="30"
          autocomplete="off"
        />
        <span class="domain-suffix">.serverstick.com</span>
      </div>

      <div class="service-examples">
        <span class="examples-label">Your services will look like:</span>
        <div class="example-list">
          {#each exampleServices as service}
            <div class="example-item">
              <span class="example-icon">{service.icon}</span>
              <span class="example-name">
                {service.name}.<span class="subdomain-highlight">{serverName}</span>.serverstick.com
              </span>
            </div>
          {/each}
        </div>
      </div>
    </div>
  </div>

  <!-- WireGuard expandable tile -->
  <div class="wireguard-tile" class:open={wireguardOpen}>
    <button class="wireguard-header" onclick={() => wireguardOpen = !wireguardOpen}>
      <span class="card-icon">🔒</span>
      <span>WireGuard Tunnel</span>
      <span class="wireguard-desc" class:hidden={wireguardOpen}>I don't want web addresses</span>
      <span class="expand-arrow" class:rotated={wireguardOpen}>▾</span>
    </button>

    {#if wireguardOpen}
      <div class="wireguard-body">
        <p>
          Connect directly to your server over an encrypted tunnel. Your server stays private — no domain, no DNS, no exposure.
        </p>
        <p>
          You'll get a config file to import into any WireGuard client. Works anywhere, keeps everything local.
        </p>
        <ul>
          <li>No domain registration needed</li>
          <li>Peer-to-peer encrypted tunnel</li>
          <li>Access from phone, laptop, or tablet</li>
          <li>Manual setup required on each device</li>
        </ul>
        <button class="wireguard-select-btn">Set up WireGuard Tunnel →</button>
      </div>
    {/if}
  </div>

  <!-- Own domain link -->
  <div class="advanced-link">
    <button class="own-domain-link">I want to use my own domain (advanced)</button>
  </div>

  <div class="onboarding-footer">
    {#if submitError}
      <p class="error-msg">⚠ {submitError}</p>
    {/if}
    <button class="btn-next" disabled={!subdomain.trim() || submitting} onclick={handleContinue}>
      {submitting ? 'Setting up…' : 'Continue →'}
    </button>
  </div>
</div>

<style>
  .welcome-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 48px;
    max-width: 540px;
    width: 100%;
  }

  .subtitle {
    color: var(--text-dim);
    font-size: 15px;
    margin-top: 10px;
    text-align: center;
  }

  /* === Main ServerStick card === */
  .main-card {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 28px;
    margin-top: 32px;
    position: relative;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
    transition: border-color 0.3s, box-shadow 0.3s;
  }

  .serverstick-card {
    border-color: var(--border-active);
    box-shadow:
      0 4px 24px rgba(0, 0, 0, 0.3),
      0 0 40px var(--accent-glow);
  }

  .serverstick-card:focus-within {
    border-color: var(--accent-strong);
    box-shadow:
      0 4px 24px rgba(0, 0, 0, 0.3),
      0 0 60px var(--accent-glow);
  }

  .card-badge {
    position: absolute;
    top: -12px;
    left: 24px;
    background: var(--accent);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 100px;
    letter-spacing: 0.3px;
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 24px;
    margin-top: 4px;
  }

  .card-icon {
    font-size: 22px;
  }

  /* Domain input */
  .domain-setup {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .domain-label {
    font-size: 13px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-weight: 500;
  }

  .domain-field {
    display: flex;
    align-items: center;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    transition: border-color 0.2s;
  }

  .domain-field:focus-within {
    border-color: var(--border-active);
  }

  .subdomain-input {
    flex: 1;
    background: none;
    border: none;
    color: var(--orange);
    font-size: 18px;
    font-weight: 500;
    padding: 14px 16px;
    min-width: 0;
    caret-color: var(--orange);
  }

  .subdomain-input::placeholder {
    color: rgba(249, 115, 22, 0.35);
  }

  .domain-suffix {
    padding: 14px 16px;
    color: var(--text-dim);
    font-size: 18px;
    font-weight: 400;
    white-space: nowrap;
    background: var(--bg-card);
    border-left: 1px solid var(--border);
  }

  /* Service examples */
  .service-examples {
    margin-top: 4px;
  }

  .examples-label {
    font-size: 13px;
    color: var(--text-dim);
    font-weight: 500;
  }

  .example-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 10px;
    max-height: 132px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .example-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--text);
    padding: 6px 10px;
    background: var(--bg-card);
    border-radius: 6px;
    transition: background 0.2s;
  }

  .example-item:hover {
    background: var(--bg-card-hover);
  }

  .example-icon {
    width: 24px;
    text-align: center;
    font-size: 14px;
  }

  .subdomain-highlight {
    color: var(--orange);
    font-weight: 600;
    padding: 1px 4px;
    background: var(--orange-glow);
    border-radius: 3px;
  }

  /* === WireGuard tile === */
  .wireguard-tile {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-top: 10px;
    transition: border-color 0.3s;
    overflow: hidden;
  }

  .wireguard-tile.open {
    border-color: #3b5998;
  }

  .wireguard-header {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    background: none;
    color: var(--text);
    font-size: 14px;
    padding: 14px 20px;
    transition: background 0.2s;
  }

  .wireguard-header:hover {
    background: var(--bg-card-hover);
  }

  .wireguard-desc {
    color: var(--text-dim);
    font-size: 13px;
    margin-left: 4px;
    flex: 1;
    text-align: left;
    transition: opacity 0.2s;
  }

  .wireguard-desc.hidden {
    opacity: 0;
  }

  .expand-arrow {
    color: var(--text-dim);
    font-size: 12px;
    transition: transform 0.3s;
  }

  .expand-arrow.rotated {
    transform: rotate(180deg);
  }

  .wireguard-body {
    padding: 0 20px 20px;
    border-top: 1px solid var(--border);
    animation: slideDown 0.25s ease-out;
  }

  @keyframes slideDown {
    from { opacity: 0; transform: translateY(-8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .wireguard-body p {
    font-size: 13px;
    color: var(--text-dim);
    margin-top: 14px;
    line-height: 1.6;
  }

  .wireguard-body ul {
    margin: 12px 0 0;
    padding-left: 18px;
  }

  .wireguard-body li {
    font-size: 13px;
    color: var(--text-dim);
    margin-bottom: 4px;
  }

  .wireguard-select-btn {
    margin-top: 16px;
    width: 100%;
    background: var(--bg-input);
    color: var(--wireguard-blue);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    font-size: 14px;
    font-weight: 500;
    transition: border-color 0.2s, background 0.2s;
  }

  .wireguard-select-btn:hover {
    border-color: var(--wireguard-blue);
    background: rgba(96, 165, 250, 0.08);
  }

  /* Advanced link */
  .advanced-link {
    margin-top: 20px;
    text-align: center;
  }

  .own-domain-link {
    font-size: 13px;
    color: var(--text-dim);
    background: none;
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-color: var(--border);
    transition: color 0.2s, text-decoration-color 0.2s;
  }

  .own-domain-link:hover {
    color: var(--text);
    text-decoration-color: var(--text-dim);
  }

  /* Footer */
  .onboarding-footer {
    padding: 24px 0;
    display: flex;
    justify-content: center;
    margin-top: auto;
  }

  .btn-next {
    background: var(--accent);
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 48px;
    border-radius: 10px;
    letter-spacing: 0.3px;
    box-shadow: 0 4px 16px var(--accent-glow);
    transition: background 0.2s, box-shadow 0.2s, opacity 0.2s;
  }

  .btn-next:hover {
    background: #8b7ff5;
    box-shadow: 0 6px 24px var(--accent-glow);
  }

  .btn-next:disabled {
    opacity: 0.35;
    cursor: not-allowed;
    box-shadow: none;
  }

  .btn-next:disabled:hover {
    background: var(--accent);
    box-shadow: none;
  }

  .error-msg {
    color: #ef4444;
    font-size: 13px;
    margin-right: 16px;
  }
</style>
