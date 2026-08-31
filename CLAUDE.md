# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This directory contains a single script, `used_resource.py`, for tracking compute
resource usage (node-hours) on the Fugaku supercomputer (Fujitsu FX1000/PJM
environment). It shells out to `pjstatj` (Fujitsu's job accounting CLI) to pull
per-user job statistics for one or more group IDs (`gid`) and computes total
node-hours consumed per user and per group over a date range.

After computing node-hours, the script also renders a per-group bar chart (one
subplot per `gid`, matplotlib, `Agg` backend) to `resource_usage_<YYYYMMDD>.png`
next to the script, and uploads that PNG to the Dropbox folder `/FugakuMonitor`
via the Dropbox API.

## Running the script

```bash
python3 used_resource.py
```

No arguments — the date range, user IDs, group IDs, and user IDs are hardcoded at
the top of the file. Requires `pandas`, `matplotlib`, `dropbox` (`pip install
dropbox`) and a working `pjstatj` on PATH (present at `/usr/local/bin/pjstatj` on
this system).

Intended to be run periodically via cron (scheduling itself is not handled by the
script — add a crontab entry that invokes `python3 used_resource.py`).

### Dropbox upload credentials

The script uploads via a long-lived Dropbox refresh token (short-lived access
tokens expire in hours and would break unattended cron runs). It reads three
environment variables at run time — set them wherever cron's environment is
configured (crontab `VAR=value` lines, or a sourced env file):

- `DROPBOX_APP_KEY`
- `DROPBOX_APP_SECRET`
- `DROPBOX_REFRESH_TOKEN`

These come from a Dropbox app created in the Dropbox App Console (scoped app,
`files.content.write` permission) and an OAuth2 refresh-token flow run once to
obtain `DROPBOX_REFRESH_TOKEN`. Do not hardcode these values in the script.

## How it works

- `term_start`/`term_end` define the accounting period (`YYYYMMDD:YYYYMMDD`);
  `term_end` defaults to today.
- `uids`/`gids`/`names` are parallel lists mapping Fugaku user IDs to group IDs and
  display names (`users = dict(zip(uids, names))`). Currently `gids = ['hp240019']`
  and all `uids` are queried against it — there are no per-group membership
  exceptions right now, but if a group only includes a subset of `uids`, add an
  `if gid == '<gid>': if uid not in (...): continue` block inside the `uid` loop
  (this pattern was used previously for `<gid1>`/`<gid2>`, since replaced by
  `hp240019`).
- For each `(gid, uid)` pair it runs
  `pjstatj -s -u <uid> -g <gid> -t <term> -c > output.csv`, reads the CSV with
  pandas, extracts `ELAPSE_TIM` (elapsed time, parsed as `HH:MM:SS` string slices)
  and `NANUM` (node count), and sums `elapsed_hours * nodes` to get node-hours per
  user, then sums across users for a group total. `ELAPSE_TIM` is cast to `str`
  before slicing so that queued/unrun jobs (empty `ELAPSE_TIM`, which pandas may
  infer as an all-NaN float column after `dropna()`) don't crash the `.str`
  accessor — this happens in practice for jobs with `ST == 'QUE'`.
- `output.csv` is a shared scratch file, overwritten each iteration and deleted
  after each `gid` loop — the script is not safe to run concurrently with itself.

## Editing notes

- To add/remove tracked users or groups, keep `uids`, `gids`, and `names` in sync
  (order-dependent zip), and add/update any per-group membership exception blocks
  (see above) if a group doesn't include every tracked `uid`.
- `labels` selects which `pjstatj -c` CSV columns are read; changing it requires
  matching the downstream column-index parsing of `ELAPSE_TIM` (fixed string
  slices `[0:4]`/`[5:7]`/`[8:10]` assume `HHHH:MM:SS`-style formatting).
