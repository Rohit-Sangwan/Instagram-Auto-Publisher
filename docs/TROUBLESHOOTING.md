# Troubleshooting

| Symptom | Check |
| --- | --- |
| Installer cannot issue a certificate | Verify A/AAAA records, external TCP port 80, and that no other service occupies ports 80 or 443. Use `sudo certbot certificates` to check the certificate name. |
| OAuth redirect mismatch | Match the public HTTPS URL and `/api/instagram/callback` exactly in the Meta app and `.env`. Recreate the API container after env changes. |
| OAuth returned to the dashboard with an error | Confirm Instagram App ID and secret, grant the requested scopes, and verify the account’s professional status and access to the app. Try connecting again to generate a fresh state. |
| Unauthorized source | Connect that account via Instagram Login, or manually import authorized local media files. |
| Account requires reconnecting | Reauthorize with the same Instagram account. Retry failed jobs after reconnecting. |
| A ready item is delayed | Review the pause and dry-run switches, publishing window, IANA time zone, per-account cap, posting interval, and API quota. |
| A media download failed | Read the activity message. A deleted post, unavailable API media URL, unsupported media type, or storage limit can prevent processing. Retry after fixing the condition. |
| Meta cannot fetch a file | Verify that the domain and certificate are reachable externally and that the Nginx `/media/` route accepts HTTPS requests without authentication or VPN. Keep the signed URL private. |
| Uncertain publish | Wait for container reconciliation. Inspect the destination on Instagram before using either confirmation action. |
| Health fails | Run `sudo docker compose ps` and `sudo docker compose logs --tail=100 api`. Check writable persistent storage and required environment values. |
| Certificate changes are not visible | Verify the renewal timer and reload hook, then run `sudo docker compose exec -T proxy nginx -s reload`. |
| Restore returns missing-media errors | Database-only backups cannot restore deleted files. Retry API imports to fetch the originals, or reimport authorized local files. |

