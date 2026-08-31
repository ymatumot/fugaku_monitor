import pandas as pd
import subprocess
import datetime

today = datetime.date.today()
#term_start = '20250401'
term_start = '20251001'
#term_end = '20230930'
term_end = today.strftime('%Y%m%d')
term = term_start+':'+term_end

#uids = ['<uid9>','<uid1>','<uid2>','<uid11>','<uid10>','<uid3>','<uid4>','<uid7>','<uid8>','<uid5>']
#gids = ['<gid1>','<gid2>']
#names = ['<user1>','Matsumoto','<user2>','<user3>','<user10>','<user4>','<user5>','<user6>','<user7>','<user8>']
uids = ['<uid1>','<uid2>','<uid3>','<uid4>','<uid5>','<uid6>']
gids = ['<gid1>','<gid2>']
names = ['Matsumoto','<user2>','<user4>','<user5>','<user8>','<user9>']
users = dict(zip(uids,names))

#labels = ['ELAPSE_TIM','NRNUM']
labels = ['ELAPSE_TIM','NANUM']
for gid in gids:
  node_hour = list()
  for uid in uids:

     if gid=='<gid1>':
        if uid == '<uid4>':
           continue
     if gid=='<gid2>':
        if not(uid == '<uid1>' or uid == '<uid4>'):
           continue
     get_csv = 'pjstatj -s -u '+uid+' -g '+gid+' -t '+term+' -c > '+'output.csv'
     subprocess.call(get_csv,shell=True)

     df = pd.read_csv('output.csv')
     df = df[labels].dropna()

     etime_h = df[labels[0]].str[0:4].astype(float)
     etime_m = df[labels[0]].str[5:7].astype(float)
     etime_s = df[labels[0]].str[8:10].astype(float)
     etime = etime_h+etime_m/60.0+etime_s/3600.0
     node = df[labels[1]]
     node_hour.append((etime*node).sum())
     print(users[uid]+': ',(etime*node).sum(),' (node*hour)')

  subprocess.call('rm output.csv',shell=True)
  print('total used recources of '+gid+' as of '+today.strftime('%y/%m/%d')+': ',sum(node_hour),' (node*hour)')

