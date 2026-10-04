# Full local backup and restore

## Desktop

The desktop application's **Backups** tab offers three actions:

- **Create full backup** saves all SQLite data, including knowledge articles,
  bookmarks, private notes, household, inventory, waypoints, incidents, and app
  events. The current article note is saved first.
- **Verify backup** validates the archive and displays record counts without
  changing the current database.
- **Restore a copy** creates a separate database at a new path. It refuses existing
  files and the active database or its journal files. The current database remains
  active. To use the copy, close FieldForge and set `FIELDFORGE_DB` to its path before
  launching again.

File operations run in a worker. Normal app close is blocked while an operation
is active. Treat full backups as private: they are unencrypted and include notes.
On Unix systems, exported archives and recovered database files use owner-only
permissions. On Windows, protect the destination folder with appropriate access
permissions.

## Command line

Close all FieldForge processes before restoring **over an existing database**.
Creating a separate copy can be done while the original remains open:

```bash
fieldforge --database fieldforge.db backup-full private-backup.zip
fieldforge backup-inspect private-backup.zip
fieldforge --database restored.db restore-full private-backup.zip
```

Restoring into an existing database requires `--replace` and replaces **all** its
data. Test restoration to a different path first. The backup is an unencrypted
SQLite snapshot in a ZIP file with a SHA-256 integrity manifest; anyone with the
file can read its private contents. Store it securely. The checksum detects file
damage, not authenticity against an attacker able to rewrite the archive.

Snapshot export uses SQLite's online backup API to include committed WAL data
consistently. All SQLite handles close before publication, and checksums are
streamed instead of loading the whole database into memory. Special characters
in database paths are encoded safely for SQLite. A mistyped source path is rejected
without creating an empty database.

Restore checks the checksum, SQLite integrity, supported database schema, required
tables/columns, and foreign-key references before installation. Invalid archive
layouts, duplicate manifest keys, oversized contents, unsupported encryption and
compression, and malformed metadata are rejected. Journal sidecars are checked
both before and after validation. In-place restore still requires all other
processes to be closed: not every open handle or concurrent writer is detectable
on every platform.

The uncompressed database limit is 1 GiB. New-file restoration uses a hard link
to publish the verified staging file without a race that could overwrite another
file. The destination filesystem must support hard links; if it does not, restore
to a supported local filesystem. Existing-file replacement is an atomic rename
after validation. Backup archives themselves can be copied to other media.

The older `backup` and `restore` JSON commands remain compatible and still cover
only members, inventory, and waypoints. Use `backup-full` for complete local data.
