#!/usr/bin/env bash
# get.sh — ServerStick one-liner installer
#
# This is the entry point served at https://serverstick.com/get.sh
# It downloads the full bootstrap script from the GitHub repo and runs it.
#
# Usage:
#   curl -fsSL https://serverstick.com/get.sh | \
#     SERVERSTICK_STARTER_KEY=sk-ss-xxxxx bash
#
#   # With Pangolin tunnel credentials (enables remote access):
#   curl -fsSL https://serverstick.com/get.sh | \
#     SERVERSTICK_STARTER_KEY=sk-ss-xxxxx \
#     PANGOLIN_NEWT_ID=mriqk2z8tyl84jb \
#     PANGOLIN_SECRET=your-secret \
#     bash
#
# Environment variables:
#   SERVERSTICK_STARTER_KEY  — Preseeded API key. Required.
#   SERVERSTICK_API_BASE     — OpenAI-compatible API base. Default: https://api.openai.com/v1
#   SERVERSTICK_BRANCH       — Git branch for source. Default: main
#   PANGOLIN_NEWT_ID         — Pangolin Newt tunnel ID (optional)
#   PANGOLIN_SECRET          — Pangolin Newt secret (optional)
#   PANGOLIN_ENDPOINT        — Pangolin endpoint. Default: gerbil.pangolin.net:50120

set -euo pipefail

REPO="https://raw.githubusercontent.com/earendil-works/serverstick"
BRANCH="${SERVERSTICK_BRANCH:-main}"
SCRIPT_URL="${REPO}/${BRANCH}/src/bootstrap/get.serverstick.sh"

echo ""
echo -e "\033[0;32m[serverstick]\033[0m Downloading bootstrap script..."
echo -e "\033[0;32m[serverstick]\033[0m Branch: ${BRANCH}"
echo ""

# Download and execute the full bootstrap
exec curl -fsSL "${SCRIPT_URL}" | bash