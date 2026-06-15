<script>
  import Step1 from './steps/Step1.svelte'
  import Step2 from './steps/Step2.svelte'
  import Dashboard from './steps/Dashboard.svelte'

  // 'onboarding-1' | 'onboarding-2' | 'dashboard'
  let view = $state('onboarding-1')
  let subdomain = $state('')
  let brain = $state(null)  // populated after Step2 submit

  function nextStep() {
    if (view === 'onboarding-1') view = 'onboarding-2'
    else if (view === 'onboarding-2') view = 'dashboard'
  }

  function prevStep() {
    if (view === 'onboarding-2') view = 'onboarding-1'
  }

  function onSubdomain(sub) {
    subdomain = sub
    nextStep()
  }

  function onBrain(b) {
    brain = b
    nextStep()
  }
</script>

{#if view === 'dashboard'}
  <Dashboard {subdomain} {brain} />
{:else}
  <div class="onboarding">
    <div class="step-indicator">
      {#each [1, 2, 3, 4] as step}
        <span
          class="step-dot"
          class:active={(view === 'onboarding-1' && step === 1) || (view === 'onboarding-2' && step === 2)}
          class:completed={(view === 'onboarding-2' && step < 2) || (view === 'dashboard' && step < 4)}
        ></span>
      {/each}
    </div>

    <div class="step-content">
      {#if view === 'onboarding-1'}
        <Step1 onnext={onSubdomain} initialSubdomain={subdomain} />
      {:else if view === 'onboarding-2'}
        <Step2 onnext={onBrain} onback={prevStep} subdomain={subdomain} />
      {/if}
    </div>
  </div>
{/if}

<style>
  .onboarding {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    background: var(--bg);
    background-image:
      radial-gradient(ellipse at 50% 0%, rgba(124, 111, 240, 0.08) 0%, transparent 60%),
      radial-gradient(ellipse at 80% 100%, rgba(249, 115, 22, 0.04) 0%, transparent 50%);
  }

  .step-indicator {
    display: flex;
    justify-content: center;
    gap: 8px;
    padding: 32px 0 0;
  }

  .step-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--border);
    transition: background 0.3s, box-shadow 0.3s;
  }

  .step-dot.active {
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent-glow);
  }

  .step-dot.completed {
    background: var(--accent);
    opacity: 0.5;
  }

  .step-content {
    flex: 1;
    display: flex;
    justify-content: center;
    padding: 0 24px;
  }
</style>
