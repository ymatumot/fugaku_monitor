# Fugaku Resource Monitor

Two small scripts that track a Fugaku project's compute (node-hour) and disk
usage, render the breakdown as pie charts, and upload the images to Dropbox
so they're easy to check without logging into the login node.

- **`node_hours.py`** — node-hour usage per fiscal-year period (前期/後期/全期間),
  broken down per tracked user and per subgroup. Cheap to query — meant to
  run **daily**.
- **`disk_usage.py`** — disk usage per volume, same per-user/per-subgroup
  breakdown. `accountd` is slow, so this is meant to run **weekly**.

Both read the list of tracked users from an `accounts.xlsx` file kept in
Dropbox (not hardcoded), and both upload their chart as a PNG to Dropbox and
delete the local copy — nothing but the two `.py` files and
`resource_common.py` needs to live in this repo.

See `CLAUDE.md` for implementation details (function-by-function notes,
known limitations). This file just covers getting it running.

## Requirements

- A Fugaku account with `pjstatj`, `accountj`, and `accountd` on `PATH`.
- Python 3 with:
  ```bash
  pip install pandas matplotlib dropbox openpyxl
  ```
- A Dropbox account and a Dropbox app (see below) to receive the uploaded
  charts and host `accounts.xlsx`.

## Setup

### 1. Create a Dropbox app

1. Go to the [Dropbox App Console](https://www.dropbox.com/developers/apps)
   and create a new app.
2. Choose **Scoped access**.
3. Choose an access type:
   - **App folder** — simplest. The app gets its own dedicated folder
     (`Apps/<your app name>` in your Dropbox); it can't see anything else.
   - **Full Dropbox** — needed if you want charts/`accounts.xlsx` to live in
     an existing folder, e.g. one shared with you by someone else.
4. Under the **Permissions** tab, enable:
   - `files.content.write`
   - `files.content.read`
5. Under **Settings**, note the **App key** and **App secret**.

### 2. Get a refresh token

A refresh token lets the scripts get short-lived access tokens on their own,
so cron runs keep working indefinitely without you re-authorizing by hand.

1. Open this URL in a browser (substitute your App key):
   ```
   https://www.dropbox.com/oauth2/authorize?client_id=<APP_KEY>&response_type=code&token_access_type=offline
   ```
2. Approve access, and copy the authorization code shown.
3. Run the helper script in this repo:
   ```bash
   python3 get_dropbox_refresh_token.py
   ```
   It prompts for your App key, App secret, and the authorization code (via
   `getpass`, so nothing is echoed to the terminal or shell history), then
   prints a `refresh_token`.

### 3. Store credentials in an env file

Create `~/.config/fugaku_monitor.env` and lock it down:

```bash
touch ~/.config/fugaku_monitor.env
chmod 600 ~/.config/fugaku_monitor.env
```

Add:

```bash
export DROPBOX_APP_KEY=<your app key>
export DROPBOX_APP_SECRET=<your app secret>
export DROPBOX_REFRESH_TOKEN=<the refresh token from step 2>
export DROPBOX_FOLDER=          # see below
```

`DROPBOX_FOLDER` controls where files are read from/written to:

- Leave it empty (or unset) for **App folder** access — uploads go to the
  app's own folder root.
- Set it to a real path (e.g. `/SharedFolderName`) for **Full Dropbox**
  access — this can be a folder someone else shared with you and gave you
  edit access to.

Never commit this file or its values — it's already covered by
`.gitignore`-style hygiene; keep secrets out of source control.

### 4. Create `accounts.xlsx`

Make a spreadsheet with a header row and one row per tracked user:

| uid     | name          | group |
|---------|---------------|-------|
| u12345  | A. Someone    | teamA |
| u23456  | B. Someone    | teamA |
| u34567  | C. Someone    | teamB |

- `uid` — the Fugaku user ID (as it appears in `pjstatj`/`accountj` output).
- `name` — display name used in chart legends.
- `group` — a subgroup label for the per-subgroup breakdown pies (use the
  same value for everyone if you don't need subgrouping).

Upload it as `accounts.xlsx` to the Dropbox location `DROPBOX_FOLDER` points
at (the app folder root, or your chosen shared folder). It's re-downloaded
fresh on every run, so you can add, remove, or move users any time without
touching the scripts.

### 5. Set the Fugaku group ID

Each script hardcodes the real Fugaku group ID (`GID`) it queries via
`accountj`/`accountd`, near the top of the file:

```python
GID = 'hp123456'
```

Edit this in both `node_hours.py` and `disk_usage.py` to your project's
group ID.

### 6. Run it

```bash
python3 node_hours.py
python3 disk_usage.py
```

Each prints a per-user usage summary, saves a PNG next to the script, uploads
it to Dropbox, then deletes the local copy.

### 7. Schedule with cron

First find the absolute path to the `python3` that has the packages from
step 1 installed (cron runs with a minimal `PATH`, so a bare `python3` in a
crontab often resolves to the wrong interpreter, or none):

```bash
which python3
```

Then use that path in the crontab (`crontab -e`), substituting it for
`/path/to/python3` below:

```cron
0 6 * * * . $HOME/.config/fugaku_monitor.env && /path/to/python3 $HOME/scripts/node_hours.py >> $HOME/scripts/node_hours_cron.log 2>&1
30 6 * * 1 . $HOME/.config/fugaku_monitor.env && /path/to/python3 $HOME/scripts/disk_usage.py >> $HOME/scripts/disk_usage_cron.log 2>&1
```

Adjust the schedule (day/time) as needed; the example runs `node_hours.py`
daily at 6:00 and `disk_usage.py` weekly on Mondays at 6:30 so they don't
overlap.

## Troubleshooting

- **`dropbox.exceptions.AuthError` / "refresh token is malformed"** — the
  refresh token is invalid or was issued for a different app. Redo the
  "Get a refresh token" step above.
- **`ValidationError: unexpected use of the catch-all tag 'other'`** on
  download — misleading error; the real cause (visible only in Dropbox's raw
  HTTP response) is usually a missing `files.content.read` scope on the app.
  Add it in the App Console and re-authorize (get a new refresh token).
- **Changed the app's access type or folder** — this always invalidates the
  existing refresh token; get a new one.
- **後期 (kouki) shows 0 before October** — expected; that period hasn't
  started yet for the current fiscal year.
