# Production deployment checklist

- [ ] The hostname resolves publicly to the intended VPS and ports 80 and 443 reach Nginx.
- [ ] The installer reports a valid certificate and healthy API. Confirm `curl --fail https://HOST/api/health` and test `sudo certbot renew --dry-run`.
- [ ] The dashboard requires the generated administrator credentials. Store the password securely and restrict the project’s `.env` and backup directories.
- [ ] Create a Meta app using Instagram Login. Configure its redirect and obtain any required access review before enabling non-test accounts.
- [ ] Authorize test source and destination accounts, verify media import, preview and dry run, then make one controlled live post to a test destination.
- [ ] Verify the resulting post and its history entry. Set publishing frequency and storage quotas appropriate for the VPS and Meta account.
- [ ] Test a controlled `docker compose restart api` and confirm persisted account, queue, and schedule state.
- [ ] Run a backup and practice restoring it in a separate environment. Store encrypted off-host copies of the database backup and key material.
- [ ] When restoring an older backup, account for every post created after the snapshot before resuming. A stale publishing history cannot deduplicate posts it never recorded. Capture any needed live history before restoring, compare with Instagram, and skip already published queue entries. Repair unavailable media using the original source or files.
- [ ] Monitor host free space, application activity, Meta API version lifecycle, and certificate renewal.

