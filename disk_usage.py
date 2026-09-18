import datetime
import os
import csv
import subprocess

import resource_common as common
import matplotlib.pyplot as plt

today = datetime.date.today()

dropbox_folder = os.environ.get('DROPBOX_FOLDER', '')  # '' = the app's own dedicated Dropbox folder (App folder access)
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'disk_usage_'+today.strftime('%Y%m%d')+'.png',
)

GID = 'hp240019'  # the only Fugaku group tracked so far; accounts.csv's
                  # "group" column is a subgroup label, not this id --
                  # per-gid tracking from accounts.csv is a future addition

dbx = common.get_dropbox_client()
uids, names, groups, uid_group = common.load_accounts(dbx, dropbox_folder)
users = dict(zip(uids,names))
color_map = common.build_color_map(uids, users, other_label='未反映')
group_color_map = common.build_group_color_map(groups, other_label='未反映')


def get_group_disk_usage(gid):
    # {volume: {'limit': GiB, 'usage': GiB}} -- only volumes with a group quota
    output = subprocess.check_output(['accountd','-g',gid,'-c'], text=True)
    result = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'GROUP':
            result[row[2]] = {'limit': float(row[3]), 'usage': float(row[4])}
    return result


def get_user_disk_usage(gid):
    # {(volume, uid): GiB}
    output = subprocess.check_output(['accountd','-g',gid,'-m','-c'], text=True)
    result = {}
    for row in csv.reader(output.splitlines()):
        if row and row[0] == 'USER':
            result[(row[1],row[2])] = float(row[4])
    return result


volumes_info = get_group_disk_usage(GID)
user_disk = get_user_disk_usage(GID)
volumes = list(volumes_info.keys())

if not volumes:
   fig, ax = plt.subplots(1, 1, figsize=(6, 5))
   ax.text(0.5, 0.5, '対象ボリュームなし', ha='center', va='center', transform=ax.transAxes)
   ax.axis('off')
else:
   ncols = len(volumes)
   fig, axes = plt.subplots(2, ncols, figsize=(6*ncols, 10))
   if ncols == 1:
      axes = axes.reshape(2, 1)  # plt.subplots returns a 1-D array when ncols==1

   for v, volume in enumerate(volumes):
      user_values = [(users[uid], user_disk.get((volume,uid),0.0)) for uid in uids]
      tracked_total = sum(val for _, val in user_values)
      vol_usage = volumes_info[volume]['usage']
      others = max(vol_usage-tracked_total, 0.0)
      limit = volumes_info[volume]['limit']
      unused = max(limit-vol_usage, 0.0)
      title = volume+'\n使用 {:,.0f} / 割当 {:,.0f} GiB'.format(vol_usage, limit)
      top, other_total = common.top_n_or_other(user_values, others)
      values = [val for _, val in top]+[other_total, unused]
      pie_labels = [l for l, _ in top]+['未反映','未使用']
      common.pie_or_placeholder(axes[0, v], values, pie_labels, title, color_map)

      subgroup_totals = {}
      for uid in uids:
         subgroup_totals.setdefault(uid_group[uid], 0.0)
         subgroup_totals[uid_group[uid]] += user_disk.get((volume,uid),0.0)
      subgroup_values = list(subgroup_totals.items())
      subgroup_title = volume+' (グループ別)\n使用 {:,.0f} / 割当 {:,.0f} GiB'.format(vol_usage, limit)
      sub_top, sub_other_total = common.top_n_or_other(subgroup_values, others)
      sub_values = [v for _, v in sub_top]+[sub_other_total, unused]
      sub_pie_labels = [l for l, _ in sub_top]+['未反映','未使用']
      common.pie_or_placeholder(axes[1, v], sub_values, sub_pie_labels, subgroup_title, group_color_map)

fig.suptitle(GID+' disk usage as of '+today.strftime('%Y-%m-%d')+' (by volume; top row per-user, bottom row per-group)')
fig.tight_layout()
fig.savefig(image_path)
plt.close(fig)
print('saved graph: '+image_path)

common.upload_to_dropbox(dbx, image_path, dropbox_folder)
os.remove(image_path)
