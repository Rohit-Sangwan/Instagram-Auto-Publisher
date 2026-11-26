# MASTER DEVELOPMENT PROMPT

## Project: Instagram Auto Publisher

Act as a senior full-stack developer, software architect, DevOps engineer and automation specialist.

Build a complete, production-ready, self-hosted Instagram-to-Instagram media automation platform that runs continuously on my Linux VPS.

The application must be fully functional, not a prototype. Implement the frontend, backend, database, automation engine, API integrations, security, testing and deployment.

## 1. Project objective

Create an automated system where I can:

- Add Instagram source accounts using usernames or profile URLs.
- Connect authorized Instagram source accounts.
- Automatically discover existing and newly uploaded media.
- Download accessible Reels, videos, images and carousels.
- Automatically publish them to my connected Instagram accounts.
- Preserve original video quality, audio and cover images whenever supported.
- Manage the entire system through a private admin dashboard.
- Run everything automatically, 24/7.

Use official API-supported access and authorized media sources.

Do not integrate Telegram, AI-generated captions, hashtags, voice generation or unnecessary paid services.

## 2. Technology stack

Use the following technologies:

- Frontend: React, TypeScript, Tailwind CSS and shadcn/ui.
- Backend: Python with FastAPI.
- Database: SQLite with WAL mode.
- ORM: SQLAlchemy.
- Database migrations: Alembic.
- Scheduler: APScheduler.
- Media processing: FFmpeg and FFprobe.
- Image processing: Pillow.
- HTTP client: HTTPX.
- Authentication: Secure session-based authentication.
- Reverse proxy: Nginx.
- Deployment: Docker Compose.
- API: Official Instagram Platform API.

Keep CPU and memory consumption as low as possible.

## 3. Admin dashboard

Create a modern, premium, responsive dashboard with dark and light modes.

The dashboard should include:

- Connected Instagram accounts.
- Configured source profiles.
- Total discovered media.
- Downloaded media.
- Pending uploads.
- Successfully published media.
- Failed uploads.
- Remaining API publishing quota.
- VPS CPU usage.
- VPS RAM usage.
- Storage consumption.
- Automation service status.
- Real-time activity logs.

Use clean cards, charts, tables, status indicators and responsive navigation.

## 4. Instagram account management

Implement secure Instagram OAuth integration.

Features:

- Connect multiple Instagram professional accounts.
- Display profile picture, username and account ID.
- Check account connection status.
- Automatically refresh access tokens where supported.
- Detect expired or revoked tokens.
- Encrypt tokens before database storage.
- Allow account reconnection and removal.
- Verify required API permissions.
- Support multiple destination accounts.

Use the current supported Meta API version and permissions. Do not hardcode deprecated API versions or endpoints.

## 5. Source profile management

Allow me to add source profiles using:

- Instagram username.
- Instagram profile URL.
- Connected authorized source account.

For every source, provide:

- Enable or disable automation.
- Destination account selection.
- Media type selection.
- Source synchronization interval.
- Import existing media.
- Import only newly published media.
- Oldest-first or newest-first ordering.
- Maximum initial import count.
- Last synchronization status.
- Manual synchronization button.

Validate that the source is accessible through an authorized API integration.

If a profile is not accessible, display the reason and provide an authorized manual media-import option.

## 6. Automatic media discovery

Create a background synchronization engine that:

- Regularly checks configured source accounts.
- Handles API pagination.
- Discovers new media.
- Retrieves media IDs, timestamps, URLs and available thumbnails.
- Identifies Reels, videos, images and carousels.
- Stores discovered media in the database.
- Automatically creates download jobs.
- Skips previously discovered media.
- Handles unavailable or deleted media gracefully.

Make synchronization intervals configurable.

## 7. Automatic download engine

Implement a reliable media download service.

Requirements:

- Stream downloads instead of loading entire files into memory.
- Preserve original file quality.
- Download original cover images where available.
- Download carousel items in their original order.
- Validate file integrity.
- Verify MIME types.
- Support configurable file size limits.
- Retry interrupted downloads safely.
- Use temporary storage directories.
- Track download progress.
- Handle expired media URLs.
- Prevent duplicate downloads.

Never log sensitive download credentials or access tokens.

## 8. Media processing engine

Use FFmpeg, FFprobe and Pillow.

Requirements:

- Analyze downloaded media.
- Verify compatibility with Instagram publishing requirements.
- Preserve original audio.
- Preserve original resolution whenever supported.
- Preserve original aspect ratio whenever supported.
- Avoid unnecessary re-encoding.
- Convert incompatible videos into supported formats.
- Convert incompatible images into supported image formats.
- Preserve original covers where supported.
- Generate a cover from the video when an original cover is unavailable.

Only perform standard compatibility processing. Preserve attribution and do not implement fingerprint manipulation or copyright-detection evasion.

## 9. Duplicate prevention

Implement reliable duplicate prevention using:

- Original Instagram media ID.
- Source permalink.
- SHA-256 file checksum.
- Source-to-destination publishing history.
- Database unique constraints.

Never publish the same media twice to the same destination account unless I explicitly authorize a manual republish.

Duplicate prevention must remain functional after application or VPS restarts.

## 10. Automatic Instagram publishing

Implement official Instagram content publishing functionality for:

- Reels.
- Single images.
- Supported video formats.
- Carousel posts.

The publishing engine must:

1. Select the next eligible item.
2. Check destination account permissions.
3. Check remaining API publishing quota.
4. Validate media compatibility.
5. Create the required media container.
6. Monitor media processing status.
7. Publish after successful processing.
8. Save the published Instagram media ID.
9. Save the published permalink where available.
10. Update the dashboard.
11. Clean up temporary files when appropriate.

Support original Reel covers using officially supported API parameters.

Do not generate captions or hashtags. Leave captions empty by default.

## 11. Intelligent scheduling engine

Build a configurable scheduling system.

Settings must include:

- Automatic publishing ON/OFF.
- Maximum posts per day.
- Minimum interval between posts.
- Publishing start and end times.
- Time zone selection.
- Maximum concurrent downloads.
- Maximum concurrent uploads.
- Source priority.
- Queue priority.
- Manual publish button.
- Pause and resume functionality.

Provide an API-quota-aware publishing mode that checks the actual remaining allowance using the official publishing-limit endpoint.

Respect platform limits and rate-limit responses. Do not use account rotation, proxy rotation or other methods to circumvent restrictions.

Default to a conservative posting frequency. Allow me to adjust it within supported limits.

## 12. Media queue management

Create the following queue categories:

- Discovered.
- Download pending.
- Downloading.
- Downloaded.
- Processing.
- Ready to publish.
- Scheduled.
- Uploading.
- Published.
- Failed.
- Skipped.

Every queue item should display:

- Thumbnail.
- Source account.
- Destination account.
- Media type.
- File size.
- Video duration.
- Progress percentage.
- Scheduled time.
- Current status.
- Error information.

Provide manual retry, cancel, skip, delete, preview and publish controls.

## 13. Error handling and recovery

Implement production-grade fault tolerance.

- Automatic retry with exponential backoff.
- Respect API retry instructions.
- Recover interrupted jobs after VPS reboot.
- Detect expired access tokens.
- Prevent concurrent processing of the same job.
- Handle API downtime.
- Handle network timeouts.
- Handle insufficient disk space.
- Handle unsupported media.
- Reconcile uncertain publishing outcomes before retrying to prevent duplicate posts.
- Pause automation when repeated account authorization failures occur.

Never silently ignore errors.

## 14. Storage management

Implement automatic storage management.

- Configurable maximum storage usage.
- Temporary media storage.
- Delete temporary files after successful publishing and confirmation.
- Preserve failed media temporarily for debugging.
- Automatic cleanup of abandoned files.
- Configurable retention period.
- Storage usage monitoring.
- Low disk space protection.

Keep publishing history even after downloaded media files are deleted.

Provide secure, temporary HTTPS media URLs when required for Meta to fetch media during publishing.

## 15. Database architecture

Create database tables for:

- admin_users
- instagram_accounts
- source_profiles
- source_destination_mappings
- discovered_media
- media_assets
- download_jobs
- publishing_jobs
- published_media
- publishing_schedules
- automation_settings
- api_usage
- activity_logs
- system_settings

Use proper indexes, foreign keys, unique constraints and database migrations.

Persist all automation state so that no progress is lost after restarts.

## 16. Security requirements

Implement:

- Secure administrator authentication.
- Argon2id password hashing.
- Encrypted Instagram access tokens.
- CSRF protection.
- Login rate limiting.
- Input validation.
- Secure HTTP cookies.
- HTTPS support.
- SSRF protection for media downloads.
- Restricted file access.
- Secure temporary media URLs.
- SQL injection protection.
- Secure OAuth state validation.
- Sensitive information redaction from logs.
- Environment-based secret management.
- Database backup and restore functionality.

Never expose access tokens to the frontend.

Do not implement unofficial login automation, session-cookie extraction, CAPTCHA bypass or private endpoint abuse.

## 17. VPS deployment

Provide complete deployment support for Ubuntu Linux.

Generate:

- Dockerfile.
- docker-compose.yml.
- .env.example.
- Nginx configuration.
- Installation script.
- Update script.
- Backup script.
- Restore script.
- Health-check configuration.
- Persistent database and media volumes.

The application must automatically restart after a crash or server reboot.

Provide installation using a simple command such as:

`bash install.sh`

The installer must check system requirements, configure dependencies, create secure credentials and initialize the application.

Do not assume fixed VPS specifications. Detect available resources and configure suitable concurrency limits.

## 18. Testing

Implement automated tests for:

- Authentication.
- Source configuration.
- Media synchronization.
- Download integrity.
- Duplicate prevention.
- Video compatibility.
- Carousel ordering.
- Instagram API integration using mocked responses.
- Publishing quota management.
- Scheduler behavior.
- Error recovery.
- Token expiration.
- Storage cleanup.
- Restart recovery.
- Security vulnerabilities.

Include a dry-run mode that executes the workflow without publishing live Instagram posts.

## 19. Cost requirements

The system must use free and open-source software wherever possible.

Do not introduce:

- Paid AI APIs.
- Paid automation services.
- Paid databases.
- Paid video processing services.
- Mandatory cloud storage subscriptions.
- Unnecessary external dependencies.

Use my existing VPS resources.

Target additional operating cost: ₹0 per month, excluding VPS charges and any unavoidable third-party service costs.

## 20. Final deliverables

Deliver the following:

- Complete frontend source code.
- Complete backend source code.
- Fully functional admin dashboard.
- Instagram OAuth integration.
- Authorized media discovery engine.
- Automatic download engine.
- Media processing engine.
- Automatic publishing engine.
- Scheduling engine.
- Database migrations.
- Docker deployment configuration.
- Installation and maintenance scripts.
- API documentation.
- Complete README.md.
- Troubleshooting guide.
- Automated tests.
- Production deployment checklist.

## 21. Agent execution instructions

Do not just explain the architecture. Actually develop the complete application.

Start by inspecting the working directory and environment.

Then:

1. Verify current Instagram API capabilities and requirements using official Meta documentation.
2. Create the project architecture and implementation plan.
3. Implement the database and backend.
4. Implement Instagram authentication and media discovery.
5. Implement downloading, processing and publishing.
6. Implement the scheduler and recovery services.
7. Build the admin dashboard.
8. Implement security protections.
9. Generate deployment scripts.
10. Run tests and fix errors.
11. Prepare production documentation.

Do not use fake API responses in production code, unfinished placeholders, nonfunctional buttons or incomplete integrations.

If any Instagram functionality is not officially available, clearly report the limitation and implement a supported alternative instead of pretending it works.

Ask me only for essential credentials, domain configuration or permissions that cannot be obtained automatically.

The final application should allow me to configure authorized source accounts, connect my destination Instagram accounts, enable automation and manage everything through one dashboard.