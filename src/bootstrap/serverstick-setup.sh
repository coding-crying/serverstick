#!/usr/bin/env bash
# serverstick-setup — First-boot hardware scan and service selector
#
# Runs after bootstrap completes. Detects hardware, recommends services,
# lets the user pick what to install. Two interfaces:
#   1. Terminal menu (whiptail/dialog) — works over SSH
#   2. Web wizard — served at http://serverstick.local:8080/setup
#
# Hardware tiers:
#   potato  — <2GB RAM, 1 CPU core  → recommends PrivateBin, PairDrop only
#   decent  — 2-8GB RAM, 2+ cores   → recommends all stateless services
#   beast   — 8GB+ RAM, 4+ cores    → recommends all services + AI stuff

set -euo pipefail

SS_DIR="/etc/serverstick"
SS_VAR="/var/lib/serverstick"
SS_LOG="/var/log/serverstick"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[serverstick]${NC} $*"; }
warn() { echo -e "${YELLOW}[serverstick]${NC} WARNING: $*" >&2; }
err()  { echo -e "${RED}[serverstick]${NC} ERROR: $*" >&2; }

# ─── Hardware Detection ───────────────────────────────────────────────────────

detect_hardware() {
    local ram_mb cpu_cores cpu_model gpu_info disk_gb arch

    # RAM in MB
    ram_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 1024)

    # CPU cores
    cpu_cores=$(nproc 2>/dev/null || echo 1)

    # CPU model (first line)
    cpu_model=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo "Unknown")

    # GPU detection
    gpu_info="none"
    if command -v lspci &>/dev/null; then
        if lspci 2>/dev/null | grep -qiE 'vga|3d|display'; then
            gpu_info=$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | head -1 | cut -d: -f3 | xargs || echo "detected")
        fi
    fi

    # Disk space (root partition, GB)
    disk_gb=$(df -BG / 2>/dev/null | awk 'NR==2 {print $2}' | tr -d 'G' || echo 20)

    # Architecture
    arch=$(dpkg --print-architecture 2>/dev/null || uname -m)

    # Hardware tier
    local tier
    if [[ "$ram_mb" -lt 2048 ]]; then
        tier="potato"
    elif [[ "$ram_mb" -lt 8192 ]]; then
        tier="decent"
    else
        tier="beast"
    fi

    # Output as JSON for the web wizard
    cat <<EOF
{
  "ram_mb": $ram_mb,
  "cpu_cores": $cpu_cores,
  "cpu_model": "$cpu_model",
  "gpu": "$gpu_info",
  "disk_gb": $disk_gb,
  "arch": "$arch",
  "tier": "$tier"
}
EOF
}

# ─── Service Registry ────────────────────────────────────────────────────────

# Each service: name, display_name, description, min_ram_mb, ports, image
# min_ram_mb is the recommended minimum RAM for this service to be useful
SERVICES_JSON='[
  {"id":"homepage","name":"Homepage","desc":"Dashboard — all your services at a glance","min_ram":128,"port":3002,"default":true},
  {"id":"stirling-pdf","name":"Stirling PDF","desc":"PDF tools — merge, split, convert, compress","min_ram":256,"port":8440,"default":true},
  {"id":"privatebin","name":"PrivateBin","desc":"Encrypted pastebin — share text securely","min_ram":64,"port":8084,"default":true},
  {"id":"pairdrop","name":"PairDrop","desc":"AirDrop for web — share files between devices","min_ram":128,"port":3000,"default":true},
  {"id":"uptime-kuma","name":"Uptime Kuma","desc":"Status monitoring — track your services","min_ram":128,"port":3001,"default":true},
  {"id":"dozzle","name":"Dozzle","desc":"Container logs — real-time Docker log viewer","min_ram":64,"port":8888,"default":true},
  {"id":"rembg","name":"Background Removal","desc":"AI background removal — privacy-first image tools","min_ram":512,"port":7000,"default":false},
  {"id":"watchtower","name":"Watchtower","desc":"Auto-update monitor — keeps containers current","min_ram":32,"port":0,"default":true}
]'

get_recommendations() {
    local tier="$1"
    local ram_mb="$2"

    echo "$SERVICES_JSON" | python3 -c "
import json, sys
services = json.loads(sys.argv[1])
tier = sys.argv[2]
ram = int(sys.argv[3])

for s in services:
    # Always recommend watchtower and homepage
    if s['id'] in ('homepage', 'watchtower'):
        s['recommended'] = True
        continue
    # Skip AI services on potato
    if tier == 'potato' and s['min_ram'] > 128:
        s['recommended'] = False
        continue
    # Recommend if RAM allows
    s['recommended'] = ram >= s['min_ram']

print(json.dumps(services))
" "$SERVICES_JSON" "$tier" "$ram_mb"
}

# ─── Terminal UI (whiptail) ───────────────────────────────────────────────────

show_terminal_menu() {
    local hw_json tier ram_mb
    hw_json=$(detect_hardware)
    tier=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['tier'])")
    ram_mb=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['ram_mb'])")

    local recommendations
    recommendations=$(get_recommendations "$tier" "$ram_mb")

    # Build whiptail checklist items
    local checklist_args=()
    local service_ids=()

    while IFS= read -r line; do
        local sid sname sdesc srec
        sid=$(echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['id'])")
        sname=$(echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['name'])")
        sdesc=$(echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['desc'])")
        srec=$(echo "$line" | python3 -c "import json,sys; d=json.load(sys.stdin); print('ON' if d['recommended'] else 'OFF')")

        checklist_args+=("$sname" "$sdesc" "$srec")
        service_ids+=("$sid")
    done < <(echo "$recommendations" | python3 -c "import json,sys; [print(json.dumps(s)) for s in json.load(sys.stdin)]")

    log "Hardware: $(echo "$hw_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"cpu_model\"]}, {d[\"ram_mb\"]}MB RAM, {d[\"disk_gb\"]}GB disk, tier: {d[\"tier\"]}')")"

    # Show hardware info
    if ! command -v whiptail &>/dev/null; then
        log "whiptail not available — installing default services for ${tier} tier"
        DEFAULT_SERVICES=$(echo "$recommendations" | python3 -c "
import json, sys
services = json.load(sys.stdin)
selected = [s['id'] for s in services if s['recommended']]
print(' '.join(selected))
")
        echo "$DEFAULT_SERVICES" > "${SS_DIR}/selected-services"
        return 0
    fi

    # Service selection
    local selected
    selected=$(whiptail --title "ServerStick Service Selection" \
        --backtitle "Hardware: ${tier} tier (${ram_mb}MB RAM)" \
        --checklist "Choose services to install. Recommended services are pre-selected based on your hardware." \
        20 78 10 \
        "${checklist_args[@]}" \
        3>&1 1>&2 2>&3) || true

    if [[ -z "$selected" ]]; then
        log "No services selected — installing recommended defaults"
        selected=$(echo "$recommendations" | python3 -c "
import json, sys
services = json.load(sys.stdin)
selected = [s['id'] for s in services if s['recommended']]
print(' '.join(selected))
")
    fi

    # Save selection
    echo "$selected" | tr -d '"' | sed 's/  */\n/g' > "${SS_DIR}/selected-services"
    log "Selected services: $(cat "${SS_DIR}/selected-services" | tr '\n' ' ')"
}

# ─── Web Wizard ──────────────────────────────────────────────────────────────

generate_setup_page() {
    local hw_json recommendations
    hw_json=$(detect_hardware)
    local tier ram_mb cpu_model cpu_cores disk_gb gpu
    tier=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['tier'])")
    ram_mb=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['ram_mb'])")
    cpu_model=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['cpu_model'])")
    cpu_cores=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['cpu_cores'])")
    disk_gb=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['disk_gb'])")
    gpu=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['gpu'])")

    recommendations=$(get_recommendations "$tier" "$ram_mb")

    # Tier emoji
    local tier_icon tier_label
    case "$tier" in
        potato) tier_icon="🥔"; tier_label="Lightweight" ;;
        decent) tier_icon="💻"; tier_label="Standard" ;;
        beast) tier_icon="🚀"; tier_label="Powerhouse" ;;
    esac

    # Generate service cards HTML
    local services_html=""
    while IFS= read -r line; do
        local sid sname sdesc smin_ram sport srec
        sid=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
        sname=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")
        sdesc=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['desc'])")
        smin_ram=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['min_ram'])")
        sport=$(echo "$line" | python3 -c "import json,sys; print(json.load(sys.stdin)['port'])")
        srec=$(echo "$line" | python3 -c "import json,sys; print('true' if json.load(sys.stdin)['recommended'] else 'false')")

        local checked=""
        [[ "$srec" == "true" ]] && checked="checked"

        services_html+="
        <div class=\"service-card\">
            <label>
                <input type=\"checkbox\" name=\"service\" value=\"${sid}\" ${checked}
                       data-min-ram=\"${smin_ram}\" data-port=\"${sport}\">
                <div class=\"service-info\">
                    <strong>${sname}</strong>
                    <span class=\"service-desc\">${sdesc}</span>
                    ${sport:+<span class=\"port-badge\">:${sport}</span>}
                </div>
            </label>
        </div>"
    done < <(echo "$recommendations" | python3 -c "import json,sys; [print(json.dumps(s)) for s in json.load(sys.stdin)]")

    cat > "${SS_VAR}/setup.html" <<SETUP_EOF
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ServerStick Setup</title>
<style>
  :root { --bg: #0a0a0b; --surface: #141416; --border: #2a2a2e; --text: #e4e4e7; --muted: #71717a; --accent: #22c55e; --accent2: #16a34a; --danger: #ef4444; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, -apple-system, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh; }
  .container { max-width: 640px; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 2rem; font-weight: 700; margin-bottom: 0.25rem; }
  h1 span { color: var(--accent); }
  .tagline { color: var(--muted); margin-bottom: 2rem; }
  .hw-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; }
  .hw-card .tier-badge { display: inline-flex; align-items: center; gap: 0.5rem; background: var(--accent); color: #000; font-weight: 600; padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.85rem; }
  .hw-card .tier-label { font-size: 0.9rem; color: var(--muted); margin-top: 0.5rem; }
  .hw-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.75rem; }
  .hw-stat { background: var(--bg); border-radius: 8px; padding: 0.5rem 0.75rem; }
  .hw-stat .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .hw-stat .value { font-size: 1rem; font-weight: 600; }
  .services { display: flex; flex-direction: column; gap: 0.5rem; }
  .service-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; cursor: pointer; transition: border-color 0.15s; }
  .service-card:hover { border-color: var(--accent); }
  .service-card:has(input:checked) { border-color: var(--accent); background: rgba(34,197,94,0.05); }
  .service-card label { display: flex; align-items: center; gap: 0.75rem; cursor: pointer; }
  .service-card input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--accent); }
  .service-info { display: flex; flex-direction: column; }
  .service-info strong { font-size: 0.95rem; }
  .service-desc { font-size: 0.8rem; color: var(--muted); }
  .port-badge { font-size: 0.7rem; color: var(--muted); font-family: monospace; }
  .actions { display: flex; gap: 0.75rem; margin-top: 1.5rem; }
  .btn { padding: 0.75rem 1.5rem; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; border: none; transition: all 0.15s; }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-primary:hover { background: var(--accent2); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-secondary { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--muted); }
  .status { margin-top: 1rem; padding: 0.75rem; border-radius: 8px; display: none; font-size: 0.9rem; }
  .status.installing { display: block; background: rgba(34,197,94,0.1); border: 1px solid var(--accent); color: var(--accent); }
  .status.error { display: block; background: rgba(239,68,68,0.1); border: 1px solid var(--danger); color: var(--danger); }
  #ram-warning { display: none; margin-top: 0.5rem; font-size: 0.85rem; color: var(--danger); }
  .section-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 0.75rem; }
</style>
</head>
<body>
<div class="container">
  <h1>Server<span>Stick</span></h1>
  <p class="tagline">Choose your privacy stack. Plug in. Take back your data.</p>

  <div class="hw-card">
    <div style="display:flex;align-items:center;justify-content:space-between;">
      <div class="tier-badge">${tier_icon} ${tier_label}</div>
      <span style="color:var(--muted);font-size:0.85rem;">${ram_mb}MB RAM · ${cpu_cores} cores</span>
    </div>
    <div class="hw-grid">
      <div class="hw-stat"><div class="label">CPU</div><div class="value">${cpu_model}</div></div>
      <div class="hw-stat"><div class="label">GPU</div><div class="value">${gpu}</div></div>
      <div class="hw-stat"><div class="label">RAM</div><div class="value">${ram_mb} MB</div></div>
      <div class="hw-stat"><div class="label">Disk</div><div class="value">${disk_gb} GB</div></div>
    </div>
  </div>

  <div class="section-title">Select Services</div>
  <div id="ram-warning">⚠ Low RAM: some services may run slowly</div>
  <form id="setup-form" class="services">
    ${services_html}
  </form>

  <div class="actions">
    <button class="btn btn-primary" id="install-btn" onclick="startInstall()">Install Selected</button>
    <button class="btn btn-secondary" onclick="selectRecommended()">Use Recommendations</button>
  </div>
  <div id="status" class="status"></div>
</div>
<script>
const totalRam = ${ram_mb};
const ramWarning = document.getElementById('ram-warning');

function checkRamBudget() {
  const checkboxes = document.querySelectorAll('input[name="service"]');
  let budget = 0;
  checkboxes.forEach(cb => {
    if (cb.checked) budget += parseInt(cb.dataset.minRam) || 0;
  });
  ramWarning.style.display = budget > totalRam ? 'block' : 'none';
}

document.querySelectorAll('input[name="service"]').forEach(cb => {
  cb.addEventListener('change', checkRamBudget);
});

function selectRecommended() {
  document.querySelectorAll('input[name="service"]').forEach(cb => {
    // Reset to default recommended state
    cb.checked = cb.dataset.minRam <= totalRam || cb.value === 'homepage' || cb.value === 'watchtower';
  });
  checkRamBudget();
}

async function startInstall() {
  const btn = document.getElementById('install-btn');
  const status = document.getElementById('status');
  const selected = Array.from(document.querySelectorAll('input[name="service"]:checked')).map(cb => cb.value);

  if (selected.length === 0) {
    status.className = 'status error';
    status.textContent = 'Select at least one service.';
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Installing...';
  status.className = 'status installing';
  status.textContent = 'Installing ' + selected.length + ' services...';

  try {
    const res = await fetch('/setup/install', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({services: selected})
    });
    const data = await res.json();
    if (data.ok) {
      status.className = 'status installing';
      status.textContent = '✓ ' + data.message;
    } else {
      throw new Error(data.error || 'Install failed');
    }
  } catch (e) {
    status.className = 'status error';
    status.textContent = '✗ ' + e.message;
    btn.disabled = false;
    btn.textContent = 'Install Selected';
  }
}

checkRamBudget();
</script>
</body>
</html>
SETUP_EOF

    log "Setup page generated at ${SS_VAR}/setup.html"
}

# ─── Apply Service Selection ──────────────────────────────────────────────────

apply_selection() {
    local selected_services
    if [[ -f "${SS_DIR}/selected-services" ]]; then
        selected_services=$(cat "${SS_DIR}/selected-services")
    else
        err "No service selection found. Run setup first."
        return 1
    fi

    log "Applying service selection: ${selected_services}"

    # Read the full compose file and filter to selected services
    local compose_file="${SS_DIR}/docker-compose.yml"
    if [[ ! -f "$compose_file" ]]; then
        # Try source compose first
        if [[ -f "${SS_DIR}/services/docker-compose.yml" ]]; then
            compose_file="${SS_DIR}/services/docker-compose.yml"
        else
            err "docker-compose.yml not found"
            return 1
        fi
    fi

    # Generate a filtered compose file with only selected services
    python3 -c "
import yaml, sys

selected = '''${selected_services}'''.split()
selected_ids = [s.strip() for s in selected if s.strip()]

with open('${compose_file}') as f:
    compose = yaml.safe_load(f)

# Keep only selected services
kept = {}
for svc_id, svc_def in compose.get('services', {}).items():
    if svc_id in selected_ids:
        kept[svc_id] = svc_def

compose['services'] = kept

with open('/etc/serverstick/docker-compose.yml', 'w') as f:
    yaml.dump(compose, f, default_flow_style=False, sort_keys=False)

print(f'Filtered compose: {len(kept)} services kept')
" 2>/dev/null || {
        # Fallback: if python yaml not available, just copy
        cp "$compose_file" "/etc/serverstick/docker-compose.yml"
        warn "Could not filter compose file — installing all services"
    }

    # Restart Docker Compose with selected services only
    cd /etc/serverstick
    docker compose up -d 2>/dev/null || warn "Some services failed to start"

    log "Services installed and running."
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    mkdir -p "${SS_DIR}" "${SS_VAR}" "${SS_LOG}"

    log "╔══════════════════════════════════════╗"
    log "║   ServerStick Service Setup            ║"
    log "║   Choose your privacy stack            ║"
    log "╚══════════════════════════════════════╝"

    # Detect hardware
    local hw_json tier
    hw_json=$(detect_hardware)
    tier=$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['tier'])")

    log "Detected hardware tier: ${tier}"
    log "Hardware: $(echo "$hw_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"cpu_model\"]}, {d[\"ram_mb\"]}MB RAM, {d[\"disk_gb\"]}GB disk')")"

    # Save hardware info for discovery API
    echo "$hw_json" > "${SS_DIR}/hardware.json"

    # Generate web setup page
    generate_setup_page

    # Try terminal menu (works over SSH)
    if [[ -t 0 ]]; then
        show_terminal_menu
    else
        # No terminal — use recommended defaults
        log "No terminal detected. Using recommended defaults for ${tier} hardware."
        get_recommendations "$tier" "$(echo "$hw_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['ram_mb'])")" | \
            python3 -c "import json,sys; services=json.load(sys.stdin); print(' '.join(s['id'] for s in services if s['recommended']))" \
            > "${SS_DIR}/selected-services"
    fi

    # Apply selection
    apply_selection

    log ""
    log "Setup complete! Your services are running."
    log ""
    log "Access your dashboard: http://localhost:3002"
    log "Setup wizard:          http://localhost:8080/setup"
    log ""
    log "Remote access (if tunnel configured):"
    log "  https://home.serverstick.com"
}

main "$@"