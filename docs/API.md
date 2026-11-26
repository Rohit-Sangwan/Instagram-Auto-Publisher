# API reference

The application exposes its complete OpenAPI schema at `GET /api/schema` once you sign in. Every administrative route uses the session cookie. Writes require both the same-origin `Origin` header and the `X-CSRF-Token` returned by login or session lookup. Login itself only needs the same-origin header. Dates are Unix epoch seconds unless noted.

| Method and path | Behavior |
| --- | --- |
| `GET /api/health` | Database and scheduler liveness |
| `POST /api/login` | Accepts username and password, sets a session cookie and returns a CSRF token |
| `GET /api/session` | Returns current CSRF token |
| `POST /api/logout` | Revokes the current session |
| `POST /api/instagram/connect?source_only=true` | Creates one-time OAuth state and returns an Instagram authorization URL |
| `GET /api/instagram/callback` | Consumes state, exchanges credentials, and redirects to the dashboard |
| `DELETE /api/accounts/{id}` | Removes local account credentials |
| `POST /api/sources` | Creates an authorized source and destination mappings |
| `PUT /api/sources/{id}` | Updates the source configuration |
| `POST /api/sources/{id}/sync` | Schedules a source check |
| `POST /api/import` | Imports multipart files with `account_id`, `authorized`, optional `permalink`, and one or more `files` fields in order |
| `GET /api/dashboard?offset=0&limit=50` | Returns account/source information, paginated queue, metrics, settings, and recent activity |
| `POST /api/queue/{id}` | Applies a queue action, optionally with `priority` or a confirmed `instagram_id` |
| `GET /api/preview/{id}` | Serves an authenticated media preview |
| `PUT /api/settings` | Updates automation, resource limits and publishing schedule |
| `GET /media/{filename}?until=…&sig=…` | Serves a short-lived, signed media URL to Meta. Also supports HEAD and byte ranges. |

Queue actions include `retry`, `publish`, `skip`, `cancel`, `delete`, `priority`, `republish`, `confirm_published`, and `confirm_not_published`. Manual confirmation is restricted to uncertain jobs. Delete hides a terminal job while retaining its duplicate-prevention tombstone.

