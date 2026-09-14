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
    # accounts.csv rows: uid,name,gid -- one row per tracked user. Downloaded
    # fresh from Dropbox on every run (no local copy is kept) so accounts can
    # be added/removed without touching either script.
    remote_path = folder+'/accounts.csv'
    _, res = dbx.files_download(remote_path)

    uids, names, gids = [], [], []
    uid_gid = {}
    for row in csv.reader(res.content.decode('utf-8').splitlines()):
        if not row:
            continue
        uid, name, gid = row[0].strip(), row[1].strip(), row[2].strip()
        uids.append(uid)
        names.append(name)
        uid_gid[uid] = gid
        if gid not in gids:
            gids.append(gid)
    return uids, names, gids, uid_gid


def upload_to_dropbox(dbx, local_path, folder):
    dest_path = folder+'/'+os.path.basename(local_path)
    with open(local_path, 'rb') as f:
        dbx.files_upload(f.read(), dest_path, mode=dropbox.files.WriteMode.overwrite)
    print('uploaded to Dropbox: '+dest_path)


def _color_for_uid(uid):
    idx = int(hashlib.md5(uid.encode()).hexdigest(), 16) % len(_USER_COLORS)
    return _USER_COLORS[idx]


def build_color_map(uids, users):
    # a user's color is derived from a hash of their uid, not their position
    # in accounts.csv, so it stays the same across runs even as users are
    # added/removed/reordered in the file. その他 is pulled out of the
    # per-user pool (reserved cycle color) so it can never collide with a
    # user's hash color; 未使用 is always gray.
    color_map = {users[uid]: _color_for_uid(uid) for uid in uids}
    color_map['その他'] = _OTHER_COLOR
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
