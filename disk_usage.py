import datetime
import os
import csv
import subprocess

import resource_common as common
import matplotlib.pyplot as plt

today = datetime.date.today()

dropbox_folder = ''  # app-folder access: uploads go to the app's own dedicated Dropbox folder
image_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'disk_usage_'+today.strftime('%Y%m%d')+'.png',
)

dbx = common.get_dropbox_client()
uids, names, gids, uid_gid = common.load_accounts(dbx, dropbox_folder)
users = dict(zip(uids,names))
color_map = common.build_color_map(uids, users)


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


for gid in gids:
  group_uids = [uid for uid in uids if uid_gid[uid] == gid]
  volumes_info = get_group_disk_usage(gid)
  user_disk = get_user_disk_usage(gid)
  volumes = list(volumes_info.keys())

  ncols = max(len(volumes), 1)
  fig, axes = plt.subplots(1, ncols, figsize=(6*ncols, 5))
  if ncols == 1:
      axes = [axes]  # plt.subplots returns a bare Axes, not an array, when ncols==1

  if not volumes:
     axes[0].text(0.5, 0.5, '対象ボリュームなし', ha='center', va='center', transform=axes[0].transAxes)
     axes[0].axis('off')

  for v, volume in enumerate(volumes):
     user_values = [(users[uid], user_disk.get((volume,uid),0.0)) for uid in group_uids]
     tracked_total = sum(val for _, val in user_values)
     vol_usage = volumes_info[volume]['usage']
     others = max(vol_usage-tracked_total, 0.0)
     limit = volumes_info[volume]['limit']
     unused = max(limit-vol_usage, 0.0)
     title = volume+'\n使用 {:,.0f} / 割当 {:,.0f} GiB'.format(vol_usage, limit)
     top, other_total = common.top_n_or_other(user_values, others)
     values = [val for _, val in top]+[other_total, unused]
     pie_labels = [l for l, _ in top]+['その他','未使用']
     common.pie_or_placeholder(axes[v], values, pie_labels, title, color_map)

  fig.suptitle(gid+' disk usage as of '+today.strftime('%Y-%m-%d')+' (by volume)')
  fig.tight_layout()
  fig.savefig(image_path)
  plt.close(fig)
  print('saved graph: '+image_path)

common.upload_to_dropbox(dbx, image_path, dropbox_folder)
os.remove(image_path)
