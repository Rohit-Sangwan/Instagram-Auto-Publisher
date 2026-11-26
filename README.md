# Instagram Auto Publisher

A private dashboard and background worker for syncing media from authorized Instagram professional accounts and publishing to connected Instagram destinations. Runs on one Ubuntu VPS with SQLite, FFmpeg, FastAPI, React, Nginx, and Docker Compose. The software stack has no mandatory paid service.

## Ubuntu VPS setup

Use Ubuntu 24.04 LTS or a newer Ubuntu release with Docker Compose v2 and Certbot 2.3+. Point a public DNS hostname at the VPS and allow inbound TCP ports 80 and 443. If your hostname has an AAAA record, configure IPv6 reachability as well. The installer needs sudo access and free ports for its Nginx instance.

Copy this project to the VPS, then run:

```bash
bash install.sh publisher.example.com admin@example.com
```

The installer generates and prints the initial admin password, provisions HTTPS, starts the services, and configures certificate renewal. Save the password and protect the generated `.env`. Store the database backup and a secure copy of the token encryption key separately. The dashboard URL is the hostname you provided.

### Connect Meta

1. In Meta for Developers, configure the Instagram product with Instagram Login. Copy the **Instagram** App ID and secret from that setup into `META_APP_ID` and `META_APP_SECRET` in `.env`.
2. Register `https://publisher.example.com/api/instagram/callback` exactly as the Instagram OAuth redirect URL. Use the actual deployed hostname. Development-mode testing requires an account the app is authorized to access. Complete Meta’s access review and required app settings for accounts outside your app roles.
3. Run `sudo docker compose up -d --wait` so the API reloads the updated environment.
4. Sign in and connect a source using **Accounts → Connect source only**. Connect a different Business or Creator account using **Connect publishing account**. A publishing account can also be selected as a source for another destination.
5. Add the source under **Sources** by username, profile URL, or the authorized account suggestion. Select destinations, media types, and initial import behavior. The initial import limit selects the most recent matching items, and the ordering option determines the order in which those jobs are created.
6. Keep dry run enabled and use **Queue → Publish** to confirm local processing and scheduling. Then disable dry run and retry the item you want to publish. Enable automatic publishing when ready. The default schedule allows up to three posts per account per day with at least two hours between posts.

OAuth uses `instagram_business_basic` and, for destinations, `instagram_business_content_publish`. The project defaults to Graph API v27.0, which is selectable via `META_API_VERSION`. A username or URL resolves an already authorized account. For other profiles, **Queue → Manual import** accepts local files you have permission to repost. Standalone videos are published as Reels. Carousel posts accept up to 20 items, including supported video children. Original source permalinks remain visible in the queue, and captions are left empty. Media quality is limited by what Instagram exposes through its API. [Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) · [Content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) · [Graph API versions](https://developers.facebook.com/docs/graph-api/guides/versioning/)

## Operation

- OAuth tokens are encrypted with `TOKEN_KEY`. Removing an account deletes its local credentials and retains publishing history. Reauthorize in Accounts when the token expires or the granted permissions change.
- Source sync follows API cursors. Individual download attempts reacquire media URLs, validate content, preserve compatible streams, and prepare JPEGs or MP4s. Uploads use signed HTTPS file links that expire after one hour. A missing video cover is generated from a frame.
- A manual publish bypasses the automatic toggle and time-of-day window. The global pause, daily cap, spacing, duplicate checks, and Meta quota still apply. Dry run verifies media and queue processing without creating Instagram containers or consuming publishing quota.
- When a live publish response is lost, the job enters reconciliation. A confirmed published container records a permanent history entry. If Meta confirms the container but supplies no media ID, the history entry retains the source and destination without a resulting post link. An unresolved job can be confirmed manually after inspecting the destination profile. A subsequent publish of a matching item is held while the first outcome is uncertain.
- Published assets are cleaned after no destination still needs them. Retained assets include failed and dry-run jobs until their retention period. Republishing a previously published automatic import may download the source again. A cleaned manual import requires the original files again.
- For a backup use `sudo bash backup.sh`. For updates, refresh the source tree, then run `sudo bash update.sh`. For restore use `sudo bash restore.sh backups/FILE.sqlite3` and follow the reconciliation steps in the deployment checklist. SQLite backups contain account records and encrypted tokens. Keep both the backups and the encryption key private.
- Run one API process per volume. The process holds a file lock while the embedded scheduler runs. SQLite, media and automation state share a persistent Docker volume, and services restart after host reboot.

## Local development

Requirements are Python 3.13, Node.js 24+, npm, FFmpeg and FFprobe on PATH. On Unix shells:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
export PUBLIC_URL=http://localhost:5173
export ADMIN_PASSWORD="$(python -c 'import secrets; print(secrets.token_hex(18))')"
export TOKEN_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export MEDIA_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
printf 'Initial admin password: %s\n' "$ADMIN_PASSWORD"
uvicorn app.main:app --port 8000 --no-access-log
```

In a second terminal:

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
```

Open `http://localhost:5173` and sign in as `admin`. The password is applied when the database is first initialized. PowerShell users can apply the same values via `$env:PUBLIC_URL`, `$env:ADMIN_PASSWORD`, `$env:TOKEN_KEY`, and `$env:MEDIA_SECRET` and use `.venv\Scripts\python.exe`. Local HTTP is for dashboard development. Instagram authorization and live publishing require HTTPS.

Run tests with `python -m pytest -q` and build the frontend with `npm run build --prefix frontend`. Tests use a temporary SQLite database, mock Meta at the HTTP transport boundary, and exercise media conversion with the installed FFmpeg.

See [API reference](docs/API.md), [troubleshooting](docs/TROUBLESHOOTING.md), and [production deployment checklist](docs/DEPLOYMENT.md).

