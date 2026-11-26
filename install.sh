#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077

if [[ $EUID -ne 0 ]]; then
  exec sudo bash "$PWD/install.sh" "$@"
fi
if [[ ! -r /etc/os-release ]] || ! grep -q '^ID=ubuntu$' /etc/os-release; then
  echo "This installer targets Ubuntu Linux." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  domain=${1:-}
  email=${2:-}
  if [[ -z $domain ]]; then read -rp "VPS hostname with public DNS: " domain; fi
  if [[ -z $email ]]; then read -rp "Let's Encrypt contact email: " email; fi
else
  domain=$(sed -n 's/^DOMAIN=//p' .env)
  email=${2:-}
fi
if [[ ! $domain =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]]; then
  echo "Enter a valid public DNS hostname." >&2
  exit 1
fi
if ! getent ahosts "$domain" >/dev/null; then
  echo "Configure DNS to point $domain to this VPS first." >&2
  exit 1
fi
if (( $(df -Pm . | awk 'NR == 2 {print $4}') < 3000 )); then
  echo "Free at least 3 GB on the installation filesystem." >&2
  exit 1
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  apt-get update
  apt-get install -y docker.io docker-compose-v2
fi
if ! command -v certbot >/dev/null || ! command -v openssl >/dev/null; then
  apt-get update
  apt-get install -y certbot openssl
fi
systemctl enable --now docker
install -d -m 0755 /var/www/instagram-publisher-acme
if [[ ! -s /etc/letsencrypt/live/$domain/fullchain.pem ]]; then
  if [[ -z $email ]]; then read -rp "Let's Encrypt contact email: " email; fi
  certbot certonly --standalone --non-interactive --agree-tos -m "$email" -d "$domain"
fi

created=0
if [[ ! -f .env ]]; then
  workers=1
  ram=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
  if (( $(nproc) >= 4 && ram >= 4000000 )); then workers=2; fi
  password=$(openssl rand -hex 18)
  token_key=$(openssl rand -base64 32 | tr '+/' '-_')
  media_secret=$(openssl rand -hex 32)
  cat > .env <<EOF
DOMAIN=$domain
PUBLIC_URL=https://$domain
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$password
TOKEN_KEY=$token_key
MEDIA_SECRET=$media_secret
META_APP_ID=
META_APP_SECRET=
META_API_VERSION=v27.0
DOWNLOAD_WORKERS=$workers
EOF
  created=1
fi

docker compose up -d --build --wait
certbot reconfigure --cert-name "$domain" --webroot --webroot-path /var/www/instagram-publisher-acme
install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
hook="/etc/letsencrypt/renewal-hooks/deploy/instagram-publisher-$domain"
printf '#!/usr/bin/env bash\ncd %q\ndocker compose exec -T proxy nginx -s reload\n' "$PWD" > "$hook"
chmod 0755 "$hook"
systemctl enable --now certbot.timer
printf 'Dashboard: https://%s\n' "$domain"
if (( created )); then printf 'Initial admin username: admin\nInitial admin password: %s\n' "$password"; fi
