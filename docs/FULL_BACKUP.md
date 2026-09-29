# Full local backup and restore

Close the desktop app before restoring. Use the new full backup command for all
SQLite data, including knowledge articles, bookmarks, private notes, household,
inventory, waypoints, incidents, and application events:

```bash
fieldforge --database fieldforge.db backup-full private-backup.zip
fieldforge --database restored.db restore-full private-backup.zip
```

Restoring into an existing database requires `--replace` and replaces **all** its
data. Test restoration to a different path first. The backup is an unencrypted
SQLite snapshot in a ZIP file with a SHA-256 integrity manifest; anyone with the
file can read its private contents. Store it securely. The checksum detects file
damage, not authenticity against an attacker able to rewrite the archive.

Snapshot export uses SQLite's online backup API, so a concurrent write cannot
leave a half-written snapshot. Restore validates the checksum, SQLite integrity,
and required FieldForge tables before replacing the target. A restore refuses
targets with SQLite journal sidecars; close all FieldForge processes before
restoring, especially if another process may hold the database open. The format
currently has a 1 GiB uncompressed database limit.

The older `backup` and `restore` JSON commands remain compatible and still cover
only members, inventory, and waypoints. Use `backup-full` for complete local data.
