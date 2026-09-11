#!/usr/bin/env bash
#
# Brings ByRewired DB up on a fresh Ubuntu server, behind a Cloudflare tunnel.
#
#   curl -fsSL <raw url of this file> -o bootstrap.sh
#   bash bootstrap.sh
#
# Everything it asks for is prompted once, at the start. It is safe to run
# again: the images rebuild, the data volume is left alone.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ByRewired/baserow.git}"
BRANCH="${BRANCH:-byrewired-db}"
CHECKOUT_DIR="${CHECKOUT_DIR:-$HOME/byrewired}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run this as your normal user, not root. It uses sudo where it needs to."

# ── what we need to know ────────────────────────────────────────────────
say "ByRewired DB deployment"

if [ -f "$CHECKOUT_DIR/deploy/byrewired/.env" ]; then
  echo "Found an existing .env, reusing it."
  REUSE_ENV=yes
else
  REUSE_ENV=no
  echo "The public address has to match the Cloudflare tunnel hostname exactly."
  echo "The frontend builds its asset and websocket urls from it, and a"
  echo "mismatch means the site loads but nothing ever updates live."
  echo
  read -rp "Public URL (e.g. https://db.example.com): " PUBLIC_URL
  [ -n "$PUBLIC_URL" ] || die "The public URL is required."
  case "$PUBLIC_URL" in
    https://*) ;;
    *) die "The public URL has to start with https://" ;;
  esac
  PUBLIC_URL="${PUBLIC_URL%/}"

  echo
  echo "Cloudflare dashboard, Zero Trust, Networks, Tunnels, Create a tunnel."
  echo "Choose Cloudflared and copy the token it shows."
  read -rp "Tunnel token: " TUNNEL_TOKEN
  [ -n "$TUNNEL_TOKEN" ] || die "The tunnel token is required."
fi

# ── docker ──────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl git
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  NEEDS_RELOGIN=yes
else
  echo "Docker is already installed."
  NEEDS_RELOGIN=no
fi

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# ── swap, on small machines ─────────────────────────────────────────────
TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
if [ "$TOTAL_MB" -lt 3500 ] && [ ! -f /swapfile ]; then
  say "Only ${TOTAL_MB}MB of memory, adding 4GB of swap"
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# ── the code ────────────────────────────────────────────────────────────
if [ -d "$CHECKOUT_DIR/.git" ]; then
  say "Updating the checkout"
  git -C "$CHECKOUT_DIR" fetch --quiet origin "$BRANCH"
  git -C "$CHECKOUT_DIR" checkout --quiet "$BRANCH"
  git -C "$CHECKOUT_DIR" pull --quiet --ff-only origin "$BRANCH"
else
  say "Cloning"
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$CHECKOUT_DIR"
fi

cd "$CHECKOUT_DIR"

# ── images ──────────────────────────────────────────────────────────────
# The all in one image is assembled from the other two, so they come first.
say "Building the backend image (this is the slow one)"
$DOCKER build -q -f backend/Dockerfile -t byrewired/backend:latest .

say "Building the web frontend image"
$DOCKER build -q -f web-frontend/Dockerfile -t byrewired/web-frontend:latest .

say "Building the all in one image"
$DOCKER build -q -f deploy/all-in-one/Dockerfile \
  --build-arg BACKEND_IMAGE=byrewired/backend:latest \
  --build-arg WEBFRONTEND_IMAGE=byrewired/web-frontend:latest \
  -t byrewired/all-in-one:latest .

# ── configuration ───────────────────────────────────────────────────────
cd deploy/byrewired

if [ "$REUSE_ENV" = no ]; then
  say "Writing .env"
  umask 077
  cat > .env <<EOF
BASEROW_PUBLIC_URL=$PUBLIC_URL
SECRET_KEY=$(openssl rand -hex 32)
BASEROW_JWT_SIGNING_KEY=$(openssl rand -hex 32)
DATABASE_PASSWORD=$(openssl rand -hex 16)
TUNNEL_TOKEN=$TUNNEL_TOKEN
GUNICORN_WORKERS=$([ "$TOTAL_MB" -lt 3500 ] && echo 1 || echo 2)
CELERY_WORKERS=1
EOF
  echo "Keys generated. Keep this file: changing the JWT key signs everyone out."
fi

# ── start ───────────────────────────────────────────────────────────────
say "Starting"
$DOCKER compose up -d

echo
echo "Waiting for the first boot to finish. It runs the migrations and builds"
echo "the search indexes, so a few minutes is normal."

for _ in $(seq 1 60); do
  if $DOCKER compose ps --format '{{.Health}}' 2>/dev/null | grep -q healthy; then
    HEALTHY=yes
    break
  fi
  sleep 10
done

PUBLIC_URL_SHOWN=$(grep '^BASEROW_PUBLIC_URL=' .env | cut -d= -f2-)

if [ "${HEALTHY:-no}" = yes ]; then
  say "Up at $PUBLIC_URL_SHOWN"
else
  say "Still starting. Watch it with: docker compose logs -f byrewired"
fi

cat <<EOF

Two things left, both in the Cloudflare dashboard:

  1. Zero Trust, Networks, Tunnels, your tunnel, Public hostname.
     Point the hostname at  http://byrewired:80

  2. Zero Trust, Access, Applications, Add a self hosted application on the
     same hostname, with a policy for the people who should get in.

     Do not skip this. The tunnel authenticates nobody, so until the policy
     exists anyone who learns the hostname is inside.

Then open $PUBLIC_URL_SHOWN and create the first account straight away. The
first account becomes the administrator.
EOF

if [ "$NEEDS_RELOGIN" = yes ]; then
  echo
  echo "Docker was installed for the first time, so log out and back in to use"
  echo "it without sudo."
fi
