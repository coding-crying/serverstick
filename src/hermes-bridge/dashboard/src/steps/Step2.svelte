<script>
  import { api } from '../lib/api.js';

  let { onnext, onback, subdomain = '' } = $props();

  let selectedOption = $state(null); // 'endpoint' | 'local' | 'mine'
  let endpointMode = $state('preset'); // 'preset' | 'custom'
  let apiKey = $state('');
  let customBaseUrl = $state('');
  let customApiKey = $state('');
  let customModel = $state('');
  let selectedPresetProvider = $state('openrouter');
  let selectedModel = $state('');
  let localScanRunning = $state(false);
  let localScanError = $state('');
  let localModels = $state([]);
  let mineCheckRunning = $state(false);
  let mineCheckError = $state('');
  let mineCheckResult = $state(null); // null | {viable, estimated_xmr_per_month, ...}
  let wallet = $state('');
  let submitting = $state(false);
  let submitError = $state('');

  const presetProviders = [
    { id: 'openrouter', name: 'OpenRouter', placeholder: 'sk-or-...' },
    { id: 'openai', name: 'OpenAI', placeholder: 'sk-...' },
    { id: 'anthropic', name: 'Anthropic', placeholder: 'sk-ant-...' },
    { id: 'google', name: 'Google AI', placeholder: 'AIza...' },
  ];

  const popularModels = [
    'deepseek-v4-pro',
    'gpt-4.1',
    'claude-opus-4-8',
    'gemini-2.5-pro',
    'llama-4-maverick',
    'qwen3-235b',
  ];

  function selectOption(option) {
    selectedOption = option;
    submitError = '';
  }

  async function runLocalScan() {
    localScanRunning = true;
    localScanError = '';
    try {
      const result = await api.hardwareScan();
      localModels = result.models || [];
    } catch (err) {
      localScanError = err.message || 'Hardware scan failed';
    } finally {
      localScanRunning = false;
    }
  }

  async function runMineCheck() {
    mineCheckRunning = true;
    mineCheckError = '';
    try {
      mineCheckResult = await api.mineCheck();
    } catch (err) {
      mineCheckError = err.message || 'Mining check failed';
    } finally {
      mineCheckRunning = false;
    }
  }

  async function handleContinue() {
    if (!selectedOption || submitting) return;
    submitting = true;
    submitError = '';
    try {
      let payload;
      if (selectedOption === 'endpoint') {
        if (endpointMode === 'preset') {
          if (!apiKey.trim()) throw new Error('API key is required');
          if (!selectedModel) throw new Error('Pick a model');
          payload = {
            tier: 'endpoint',
            provider: selectedPresetProvider,
            api_key: apiKey,
            model: selectedModel,
          };
        } else {
          if (!customApiKey.trim()) throw new Error('API key is required');
          if (!customModel.trim()) throw new Error('Model name is required');
          payload = {
            tier: 'endpoint',
            provider: 'custom',
            api_key: customApiKey,
            base_url: customBaseUrl,
            model: customModel,
          };
        }
      } else if (selectedOption === 'local') {
        if (!selectedModel) throw new Error('Pick a model from the scan');
        payload = { tier: 'local', model: selectedModel };
      } else if (selectedOption === 'mine') {
        if (!wallet.trim()) throw new Error('XMR wallet address is required');
        payload = { tier: 'mine', wallet: wallet };
      }
      const result = await api.onboardBrain(payload);
      onnext({ ...payload, job_id: result.job_id });
    } catch (err) {
      submitError = err.message || 'Failed to configure brain';
    } finally {
      submitting = false;
    }
  }
</script>

<div class="step-content">
  <h1>Now your server needs a brain</h1>
  <p class="subtitle">So you don't need to use yours.</p>

  <div class="options-grid">

    <!-- ====== Option 1: Add an endpoint ====== -->
    <div
      class="option-card endpoint-card"
      class:selected={selectedOption === 'endpoint'}
      role="button"
      tabindex="0"
      onclick={() => selectOption('endpoint')}
      onkeydown={(e) => e.key === 'Enter' && selectOption('endpoint')}
    >
      <div class="option-header">
        <span class="option-icon">⚡</span>
        <div>
          <h2>Add an endpoint</h2>
          <p class="option-tagline">Connect to any AI provider</p>
        </div>
      </div>

      {#if selectedOption === 'endpoint'}
        <div class="option-body">
          <div class="mode-toggle">
            <button class="mode-btn" class:active={endpointMode === 'preset'} onclick={() => endpointMode = 'preset'}>Providers</button>
            <button class="mode-btn" class:active={endpointMode === 'custom'} onclick={() => endpointMode = 'custom'}>Custom</button>
          </div>

          {#if endpointMode === 'preset'}
            <div class="field">
              <span class="field-label">Provider</span>
              <div class="provider-chips">
                {#each presetProviders as provider}
                  <button
                    class="provider-chip"
                    class:active={selectedPresetProvider === provider.id}
                    onclick={() => { selectedPresetProvider = provider.id; apiKey = ''; }}
                  >
                    {provider.name}
                  </button>
                {/each}
              </div>
            </div>

            <div class="field">
              <span class="field-label">API Key</span>
              <input
                type="password"
                bind:value={apiKey}
                placeholder={presetProviders.find(p => p.id === selectedPresetProvider)?.placeholder || 'sk-...'}
                class="text-input"
              />
            </div>

            <div class="field">
              <span class="field-label">Model</span>
              <select bind:value={selectedModel} class="select-input">
                <option value="" disabled selected>Select a model</option>
                {#each popularModels as model}
                  <option value={model}>{model}</option>
                {/each}
              </select>
            </div>
          {:else}
            <div class="field">
              <span class="field-label">Base URL</span>
              <input
                type="url"
                bind:value={customBaseUrl}
                placeholder="https://api.example.com/v1"
                class="text-input"
              />
            </div>

            <div class="field">
              <span class="field-label">API Key</span>
              <input
                type="password"
                bind:value={customApiKey}
                placeholder="sk-..."
                class="text-input"
              />
            </div>

            <div class="field">
              <span class="field-label">Model</span>
              <input
                type="text"
                bind:value={customModel}
                placeholder="e.g. gpt-4o-mini, claude-sonnet-4-5"
                class="text-input"
              />
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- ====== Option 2: Run locally ====== -->
    <div
      class="option-card local-card"
      class:selected={selectedOption === 'local'}
      role="button"
      tabindex="0"
      onclick={() => selectOption('local')}
      onkeydown={(e) => e.key === 'Enter' && selectOption('local')}
    >
      <div class="option-header">
        <span class="option-icon">🧠</span>
        <div>
          <h2>Run the brain on my machine</h2>
          <p class="option-tagline">No API keys, no cloud, fully private</p>
        </div>
      </div>

      {#if selectedOption === 'local'}
        <div class="option-body">
          {#if !localScanRunning && localModels.length === 0}
            <p class="body-text">
              We'll scan your hardware to find which models can run locally. This uses <span class="code-word">llmfit</span> to check your CPU, GPU, and available RAM.
            </p>
            {#if localScanError}
              <p class="error-msg">⚠ {localScanError}</p>
            {/if}
            <button class="scan-btn" onclick={runLocalScan}>
              Scan my hardware
            </button>
          {:else if localScanRunning}
            <div class="scan-status">
              <div class="spinner"></div>
              <span>Scanning hardware with llmfit...</span>
            </div>
          {:else if localModels.length > 0}
            <p class="body-text">Found {localModels.length} models that fit your hardware:</p>
            <div class="model-list">
              {#each localModels as model}
                <label class="model-item">
                  <input type="radio" name="local-model" value={model.id} bind:group={selectedModel} />
                  <div class="model-info">
                    <span class="model-name">{model.name}</span>
                    <span class="model-meta">{model.size} · {model.ram} RAM</span>
                  </div>
                </label>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- ====== Option 3: Mine for credit ====== -->
    <div
      class="option-card mine-card"
      class:selected={selectedOption === 'mine'}
      role="button"
      tabindex="0"
      onclick={() => selectOption('mine')}
      onkeydown={(e) => e.key === 'Enter' && selectOption('mine')}
    >
      <div class="option-header">
        <span class="option-icon">⛏️</span>
        <div>
          <h2>Use my hardware to pay for credit</h2>
          <p class="option-tagline">Mine Monero → earn nanoGPT API credit</p>
        </div>
      </div>

      {#if selectedOption === 'mine'}
        <div class="option-body">
          {#if !mineCheckRunning && mineCheckResult === null}
            <p class="body-text">
              We'll check if your machine has spare capacity to run a Monero miner in the background. The earned credit pays for AI models on nanoGPT — no wallet or credit card needed.
            </p>
            {#if mineCheckError}
              <p class="error-msg">⚠ {mineCheckError}</p>
            {/if}
            <button class="scan-btn" onclick={runMineCheck}>
              Check if mining is viable
            </button>
          {:else if mineCheckRunning}
            <div class="scan-status">
              <div class="spinner"></div>
              <span>Checking hardware compatibility...</span>
            </div>
          {:else if mineCheckResult}
            {#if mineCheckResult.viable}
              <div class="mine-result available">
                <span class="result-icon">✅</span>
                <div>
                  <p class="result-title">Your hardware can mine</p>
                  <p class="result-detail">
                    Estimated ~{mineCheckResult.estimated_xmr_per_month} XMR/month
                    · ~${mineCheckResult.estimated_usd_per_month} nanoGPT credit
                  </p>
                </div>
              </div>
              <div class="field">
                <span class="field-label">XMR Wallet Address</span>
                <input
                  type="text"
                  bind:value={wallet}
                  placeholder="4..."
                  class="text-input"
                />
              </div>
            {:else}
              <div class="mine-result unavailable">
                <span class="result-icon">❌</span>
                <div>
                  <p class="result-title">Not enough spare capacity</p>
                  <p class="result-detail">Need at least 2 GB free RAM and 4 CPU cores</p>
                </div>
              </div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>

  </div>

  <div class="onboarding-footer">
    <button class="btn-back" onclick={onback}>← Back</button>
    {#if submitError}
      <span class="error-msg">⚠ {submitError}</span>
    {/if}
    <button class="btn-next" disabled={!selectedOption || submitting} onclick={handleContinue}>
      {submitting ? 'Setting up…' : 'Continue →'}
    </button>
  </div>
</div>

<style>
  .step-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 48px;
    max-width: 600px;
    width: 100%;
  }

  .subtitle {
    color: var(--text-dim);
    font-size: 15px;
    margin-top: 10px;
    text-align: center;
  }

  .options-grid {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-top: 32px;
  }

  /* === Option cards === */
  .option-card {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 24px;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.25s, box-shadow 0.25s, background 0.2s;
  }

  .option-card:hover {
    background: var(--bg-card-hover);
    border-color: #2a2a3e;
  }

  .option-card:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .option-card.selected {
    border-color: var(--border-active);
    box-shadow: 0 0 30px var(--accent-glow);
  }

  .endpoint-card.selected {
    border-color: #8b5cf6;
    box-shadow: 0 0 30px rgba(139, 92, 246, 0.2);
  }

  .local-card.selected {
    border-color: #34d399;
    box-shadow: 0 0 30px rgba(52, 211, 153, 0.15);
  }

  .mine-card.selected {
    border-color: #f59e0b;
    box-shadow: 0 0 30px rgba(245, 158, 11, 0.15);
  }

  .option-header {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .option-icon {
    font-size: 28px;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-input);
    border-radius: 10px;
    flex-shrink: 0;
  }

  .option-header h2 {
    font-size: 17px;
    font-weight: 600;
    line-height: 1.3;
  }

  .option-tagline {
    color: var(--text-dim);
    font-size: 13px;
    margin-top: 2px;
  }

  /* === Expanded option body === */
  .option-body {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
    animation: expandIn 0.2s ease-out;
  }

  @keyframes expandIn {
    from { opacity: 0; transform: translateY(-6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .body-text {
    font-size: 14px;
    color: var(--text-dim);
    line-height: 1.6;
  }

  .code-word {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--accent-strong);
    background: var(--accent-glow);
    padding: 1px 6px;
    border-radius: 4px;
  }

  /* Mode toggle */
  .mode-toggle {
    display: flex;
    background: var(--bg-input);
    border-radius: 8px;
    padding: 3px;
    margin-bottom: 18px;
  }

  .mode-btn {
    flex: 1;
    background: none;
    color: var(--text-dim);
    font-size: 13px;
    font-weight: 500;
    padding: 7px 14px;
    border-radius: 6px;
    transition: background 0.2s, color 0.2s;
  }

  .mode-btn.active {
    background: var(--bg-card);
    color: var(--text-heading);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  }

  /* Fields */
  .field {
    margin-bottom: 14px;
  }

  .field-label {
    display: block;
    font-size: 12px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 500;
    margin-bottom: 6px;
  }

  .text-input {
    width: 100%;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-heading);
    font-size: 14px;
    padding: 10px 14px;
    transition: border-color 0.2s;
  }

  .text-input:focus {
    border-color: var(--border-active);
  }

  .text-input::placeholder {
    color: var(--text-dim);
    opacity: 0.6;
  }

  /* Provider chips */
  .provider-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .provider-chip {
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--text);
    font-size: 13px;
    padding: 6px 14px;
    border-radius: 100px;
    transition: border-color 0.2s, background 0.2s, color 0.2s;
  }

  .provider-chip.active {
    background: var(--accent-glow);
    border-color: var(--accent);
    color: var(--accent-strong);
  }

  .provider-chip:hover {
    border-color: #3a3a50;
  }

  /* Select input */
  .select-input {
    width: 100%;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-heading);
    font-size: 14px;
    padding: 10px 14px;
    appearance: none;
    cursor: pointer;
    transition: border-color 0.2s;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%236b6b80' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 14px center;
  }

  .select-input:focus {
    border-color: var(--border-active);
  }

  .select-input option {
    background: var(--bg-card);
    color: var(--text-heading);
  }

  /* Scan button */
  .scan-btn {
    margin-top: 14px;
    width: 100%;
    background: var(--bg-input);
    color: var(--accent-strong);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    font-size: 14px;
    font-weight: 500;
    transition: border-color 0.2s, background 0.2s;
  }

  .scan-btn:hover {
    border-color: var(--accent);
    background: rgba(124, 111, 240, 0.06);
  }

  /* Scan status / spinner */
  .scan-status {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 0;
    color: var(--text-dim);
    font-size: 14px;
  }

  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* Model list */
  .model-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 12px;
  }

  .model-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: border-color 0.2s;
  }

  .model-item:hover {
    border-color: #3a3a50;
  }

  .model-item:has(input:checked) {
    border-color: var(--green);
    background: rgba(52, 211, 153, 0.05);
  }

  .model-item input[type="radio"] {
    accent-color: var(--green);
    width: 16px;
    height: 16px;
    margin: 0;
  }

  .model-info {
    display: flex;
    flex-direction: column;
  }

  .model-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-heading);
  }

  .model-meta {
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 2px;
  }

  /* Mine result */
  .mine-result {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 16px;
    border-radius: 10px;
    margin-top: 12px;
  }

  .mine-result.available {
    background: rgba(52, 211, 153, 0.06);
    border: 1px solid rgba(52, 211, 153, 0.2);
  }

  .result-icon {
    font-size: 22px;
  }

  .result-title {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-heading);
  }

  .result-detail {
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 2px;
  }

  /* Toggle row */
  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 14px;
    padding: 10px 14px;
    background: var(--bg-input);
    border-radius: 8px;
    font-size: 14px;
    color: var(--text);
    cursor: pointer;
  }

  .toggle {
    width: 40px;
    height: 22px;
    accent-color: #f59e0b;
  }

  /* Footer */
  .onboarding-footer {
    display: flex;
    gap: 12px;
    justify-content: center;
    padding: 24px 0;
    margin-top: auto;
  }

  .btn-back {
    background: var(--bg-card);
    color: var(--text-dim);
    font-size: 14px;
    padding: 10px 24px;
    border-radius: 10px;
    border: 1px solid var(--border);
    transition: border-color 0.2s, color 0.2s;
  }

  .btn-back:hover {
    border-color: #3a3a50;
    color: var(--text);
  }

  .btn-next {
    background: var(--accent);
    color: #fff;
    font-size: 15px;
    font-weight: 600;
    padding: 10px 48px;
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
    margin: 0 16px;
    flex: 1;
  }

  .mine-result.unavailable {
    color: #ef4444;
  }
</style>
