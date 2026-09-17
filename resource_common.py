import os
import csv
import hashlib
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.family'] = ['DejaVu Sans', 'Droid Sans Japanese']
import matplotlib.pyplot as plt
plt.style.use('ggplot')
import dropbox

# code shared between node_hours.py (daily) and disk_usage.py (weekly) --
# Dropbox access, accounts.csv loading, pie-chart colors/drawing. Import this
# module before pyplot elsewhere in a script so the Agg backend/font/ggplot
# style are set up first.

TOP_N = 5

_cycle = plt.rcParams['axes.prop_cycle'].by_key()['color']
_OTHER_COLOR = _cycle[-1]
_USER_COLORS = _cycle[:-1]


def get_dropbox_client():
    return dropbox.Dropbox(
        oauth2_refresh_token=os.environ['DROPBOX_REFRESH_TOKEN'],
        app_key=os.environ['DROPBOX_APP_KEY'],
        app_secret=os.environ['DROPBOX_APP_SECRET'],
    )


def load_accounts(dbx, folder):
    # accounts.csv rows: uid,name,group -- one row per tracked user, with a
    # header row naming the columns. Downloaded fresh from Dropbox on every
    # run (no local copy is kept) so accounts can be added/removed without
    # touching either script. "group" is a subgroup label for reporting
    # (currently a placeholder "PIC" for everyone) -- it is NOT the Fugaku
    # accountj/accountd group id, which each script hardcodes separately
    # until per-gid tracking is reintroduced.
    remote_path = folder+'/accounts.csv'
    _, res = dbx.files_download(remote_path)

    uids, names, groups = [], [], []
    uid_group = {}
    for row in csv.DictReader(res.content.decode('utf-8').splitlines()):
        if not row:
            continue
        uid, name, group = row['uid'].strip(), row['name'].strip(), row['group'].strip()
        uids.append(uid)
        names.append(name)
        uid_group[uid] = group
        if group not in groups:
            groups.append(group)
    return uids, names, groups, uid_group


def upload_to_dropbox(dbx, local_path, folder):
    dest_path = folder+'/'+os.path.basename(local_path)
    with open(local_path, 'rb') as f:
        dbx.files_upload(f.read(), dest_path, mode=dropbox.files.WriteMode.overwrite)
    print('uploaded to Dropbox: '+dest_path)


def _assign_distinct_colors(keys, pool):
    # each key's preferred slot is a hash of the key (stable across runs and
    # independent of accounts.csv's row order); if that slot is already taken
    # by another key, linear-probe forward to the next free one so two
    # different keys are never handed the same color -- as long as there are
    # at most len(pool) keys. Keys are processed in sorted order so the
    # outcome depends only on the *set* of keys present, not on file order.
    # (Only when keys outnumber the pool does a slot ever get reused, since
    # every slot is then already taken.)
    assigned = {}
    taken = set()
    for key in sorted(keys):
        idx = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(pool)
        for _ in range(len(pool)):
            if pool[idx] not in taken:
                break
            idx = (idx + 1) % len(pool)
        assigned[key] = pool[idx]
        taken.add(pool[idx])
    return assigned


def build_color_map(uids, users, other_label='その他'):
    # a user's color is derived from a hash of their uid (see
    # _assign_distinct_colors), not their position in accounts.csv, so it
    # stays the same across runs even as users are added/removed/reordered
    # in the file -- and two different tracked users are never handed the
    # same color. other_label (その他, or disk_usage.py's 未反映) is pulled
    # out of the per-user pool (reserved cycle color) so it can never collide
    # with a user's color; 未使用 is always gray.
    assigned = _assign_distinct_colors(uids, _USER_COLORS)
    color_map = {users[uid]: assigned[uid] for uid in uids}
    color_map[other_label] = _OTHER_COLOR
    color_map['未使用'] = 'gray'
    return color_map


# per-group (bottom-row) pies use a deliberately different color scale from
# per-user (top-row) pies -- a monochrome blue ramp rather than the ggplot
# multi-hue cycle -- so a group's color is never mistaken for a user's, even
# when both happen to be blueish. Steps are pulled from a validated
# light->dark categorical ramp (see the dataviz skill's palette reference),
# spread out for maximum mutual contrast rather than taken as consecutive
# steps.
_GROUP_COLORS = ['#b7d3f6', '#6da7ec', '#2a78d6', '#184f95', '#0d366b']
_GROUP_OTHER_COLOR = '#4a3aa7'  # violet accent -- distinct from the blue ramp


def build_group_color_map(groups, other_label='その他'):
    # same fixed-across-runs, collision-free hashing scheme as
    # build_color_map (see _assign_distinct_colors), keyed on the group label
    # itself since groups (accounts.csv's "group" column) have no separate
    # uid; 未使用 stays the same gray as the per-user pies (it's a shared,
    # non-identity "nothing here" meaning, not a group identity).
    assigned = _assign_distinct_colors(groups, _GROUP_COLORS)
    color_map = dict(assigned)
    color_map[other_label] = _GROUP_OTHER_COLOR
    color_map['未使用'] = 'gray'
    return color_map


def top_n_or_other(pairs, other_value, n=TOP_N):
    # pairs: list of (label, value) for tracked users in this pie. Keeps the
    # top n by value under their own name and folds the rest (plus
    # other_value, the already-computed rest-of-group total) into a single
    # total -- so a pie never shows more than n+2 slices (top n + その他 +
    # 未使用) no matter how many users accounts.csv ends up tracking.
    pairs_sorted = sorted(pairs, key=lambda x: x[1], reverse=True)
    top = pairs_sorted[:n]
    rest = pairs_sorted[n:]
    other_total = other_value + sum(v for _, v in rest)
    return top, other_total


def pie_or_placeholder(ax, values, pie_labels, title, color_map):
    pairs = [(v,l) for v,l in zip(values, pie_labels) if v > 0]
    ax.set_title(title)
    if not pairs:
        ax.text(0.5, 0.5, '利用なし', ha='center', va='center', transform=ax.transAxes)
        ax.axis('off')
        return
    vs = [p[0] for p in pairs]
    ls = [p[1] for p in pairs]
    total = sum(vs)
    def autopct(pct):
        if pct < 1.0:
            return ''
        return '{:.1f}%\n({:,.0f})'.format(pct, pct/100.0*total)
    colors = [color_map[l] for l in ls]
    wedges, _, _ = ax.pie(vs, autopct=autopct, pctdistance=0.75, colors=colors,
                           startangle=90, counterclock=False)
    ax.legend(wedges, ls, loc='center left', bbox_to_anchor=(1.0, 0.5), fontsize='small')
