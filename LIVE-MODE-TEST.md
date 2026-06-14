# ServerStick Live Mode — Spike Test Plan

**Goal:** Verify that the hybrid live-first boot works — a working dashboard comes up
within ~30 seconds of the stick booting, before any disk install.

## What you're testing

- Does the live image boot successfully?
- Does the Pi Agent systemd service start automatically?
- Does the dashboard come up on port 8080?
- How fast does it go from "power on" to "dashboard ready"?

## What's in the ISO

- Debian 12 base + Python 3.11 + FastAPI + uvicorn (system pip install)
- Minimal "live mode" FastAPI agent at `/opt/serverstick/src/agent/live_mode.py`
- Systemd unit at `/etc/systemd/system/serverstick-agent.service` (enabled, will start at boot)
- Live-mode marker at `/etc/serverstick/live-mode`
- This is a **spike** — the real Pi Agent (with Svelte dashboard, Docker services, etc.) replaces this in phase 2

## Test on Proxmox (PVE)

### Step 1: Create a fresh VM

In the PVE web UI (`https://10.0.0.200:8006`):

- Click **Create VM**
- **VM ID:** 102 (next free after 100=pbs, 101=serverstick-test)
- **Name:** `serverstick-live-test`
- **OS:** Do **NOT** select an ISO yet — we'll attach it manually
- **System:** Defaults are fine (q35 BIOS or SeaBIOS; i440fx also works)
- **Disks:** 32GB (won't be written to in live mode, but needed for VM)
- **CPU:** 2 cores, **type: host** (important — default kvm64 hides SSE4.2)
- **Memory:** 2048 MB
- **Network:** Default bridge (vmbr0)

### Step 2: Attach the ServerStick ISO

- In the VM's **Hardware** tab → **CD/DVD Drive** → **Edit**
- Select **Use CD/DVD disc image file (iso)**
- **Storage:** local
- **ISO Image:** `serverstick-live-0.1.iso`
- Click OK

### Step 3: Boot order

- **Options** tab → **Boot Order**
- Move `ide2` (the CD-ROM) to the top
- **Enable** it (checkbox)

### Step 4: Start the VM and watch

- Right-click the VM → **Start** → **Console** (noVNC)
- Watch the boot. You should see:
  - ISOLINUX / GRUB boot menu (1-second timeout, auto-selects first option)
  - Debian kernel boots
  - systemd services start
  - Login prompt appears
- **Time from VM start to login prompt:** record this. This is your "boot to system ready" time.

### Step 5: Get the LAN IP

In the noVNC console:
```bash
ip -4 addr show | grep inet
# or
hostname -I
```

You'll see something like `10.0.0.X` — note the IP.

### Step 6: Test the dashboard

From your laptop (or any machine on the same network):
```
http://10.0.0.X:8080/
```

You should see:
- Green "⚡ LIVE MODE" badge
- System info card (hostname, IP, uptime, OS)
- "What's happening" card explaining this is live mode
- "Raw system info" card

Also test the JSON API:
```
curl http://10.0.0.X:8080/api/status
curl http://10.0.0.X:8080/api/health
```

### Step 7: (Optional) Watch the boot timing in journal

In the VM console:
```bash
journalctl -u serverstick-agent
systemd-analyze
```

The agent should start within 5-10 seconds of `multi-user.target`.

## Success criteria

✅ VM boots to login prompt in under 60 seconds
✅ `http://10.0.0.X:8080/` returns the live mode HTML page
✅ `/api/status` returns JSON with `"mode": "live"`
✅ Systemd unit shows `active (running)` for `serverstick-agent`

## What to do if it doesn't work

**If the boot hangs or shows errors:**
- Take a screenshot of the noVNC console
- Note the last visible message
- We can iterate

**If the dashboard doesn't respond on :8080:**
- In the VM: `systemctl status serverstick-agent`
- Check `journalctl -u serverstick-agent -n 50`
- Check `ss -tlnp | grep 8080`

**If the VM doesn't get an IP:**
- Check the network bridge in PVE
- `ip link show` in the VM to see if interface is up
- Try `dhclient` to manually request a lease

## After the test

Tell me:
1. Boot time (VM start → login prompt)
2. Dashboard accessible? (Y/N)
3. Any errors in the boot log?
4. Was the experience actually smoother than "5-15 min install wait"?

If it works, the next step is replacing the minimal `live_mode.py` with the real Pi Agent.
