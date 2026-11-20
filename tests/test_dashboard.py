"""Offline safety smoke tests: python -m unittest discover -s tests -v

Creates a TEMPORARY SQLite database, never touches data/critbot.db.
No Discord credentials, network access or live server required.
"""
import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta

_TEMP=tempfile.TemporaryDirectory(prefix='critbot_tests_')
DB=Path(_TEMP.name)/'test.db'
DB.touch()
os.environ.update({
 'CRITBOT_DB':str(DB),'CRITBOT_OWNER_DISCORD_ID':'111111111111111111',
 'CRITBOT_GUILD_ID':'222222222222222222','DISCORD_CLIENT_ID':'333333333333333333',
 'DISCORD_CLIENT_SECRET':'test-only','DISCORD_REDIRECT_URI':'http://127.0.0.1:5000/auth/discord/callback',
 'CRITBOT_DASHBOARD_SECRET':'only-for-unit-tests-secret-is-long-enough-1234','CRITBOT_ALLOW_HTTP_LOCAL':'1',
})
from critbot.dashboard import app,init_db
from critbot.security import current_access,expand_permissions
init_db();app.config.update(TESTING=True)

class OperationsTests(unittest.TestCase):
 def client_for(self,uid):
  client=app.test_client()
  with client.session_transaction() as s:
   s['discord_id']=uid;s['display_name']='Test';s['csrf']='unit-test-csrf'
  return client
 def post(self,client,url,data):
  return client.post(url,data=dict(_csrf='unit-test-csrf',**data),follow_redirects=False)
 @classmethod
 def setUpClass(cls):
  with sqlite3.connect(DB) as db:
   db.execute('INSERT INTO dashboard_access(discord_id,display_name,permissions) VALUES(?,?,?)',('444444444444444444','Reader',json.dumps(['events','conduct','treasury','suggestions'])))
   db.execute('INSERT INTO dashboard_access(discord_id,display_name,permissions) VALUES(?,?,?)',('555555555555555555','Event host',json.dumps(['events','events_create'])))
   db.execute('INSERT INTO auto_channel_directory(channel_id,name) VALUES (?,?)',('666666666666666666','events'))
 def test_owner_pages(self):
  c=self.client_for('111111111111111111')
  for page in ['/command','/events','/conduct','/treasury','/suggestions','/access','/']:
   with self.subTest(page=page):self.assertEqual(c.get(page).status_code,200)
 def test_readonly_officer(self):
  c=self.client_for('444444444444444444')
  for url in ['/events','/conduct','/treasury','/suggestions','/command']:
   with self.subTest(url=url):self.assertEqual(c.get(url).status_code,200)
  for url in ['/events/new','/access','/stats','/guild/seasons','/events/1/edit']:
   with self.subTest(url=url):self.assertEqual(c.get(url).status_code,403)
  for url,form in [('/conduct/new',{'subject':'Test','category':'Other','priority':'normal','summary':'test'}),('/treasury/record',{'direction':'deposit','gold':'50','purpose':'Test'}),('/events/1/action',{'operation':'delete'})]:
   with self.subTest(url=url):self.assertEqual(self.post(c,url,form).status_code,403)
 def test_conduct_notes_and_followup(self):
  c=self.client_for('111111111111111111')
  self.assertEqual(self.post(c,'/conduct/new',{'subject':'Chat disagreement','category':'Conflict','priority':'normal','summary':'Officer reached out','next_step':'Follow up'}).status_code,302)
  with sqlite3.connect(DB) as db:case_id=db.execute('SELECT MAX(id) FROM conduct_cases').fetchone()[0]
  self.assertEqual(self.post(c,f'/conduct/{case_id}/followup',{'body':'Resolved after discussion','status':'closed','next_step':''}).status_code,302)
  with sqlite3.connect(DB) as db:
   self.assertEqual(db.execute('SELECT status FROM conduct_cases WHERE id=?',(case_id,)).fetchone()[0],'closed')
   self.assertEqual(db.execute('SELECT COUNT(*) FROM conduct_followups WHERE case_id=?',(case_id,)).fetchone()[0],1)
 def test_treasury_manual_ledger(self):
  c=self.client_for('111111111111111111')
  self.assertEqual(self.post(c,'/treasury/record',{'direction':'deposit','gold':'100.50','purpose':'Deposit'}).status_code,302)
  self.assertEqual(self.post(c,'/treasury/record',{'direction':'expense','gold':'10.25','purpose':'Raid consumables'}).status_code,302)
  with sqlite3.connect(DB) as db:
   ledger=db.execute("SELECT SUM(CASE WHEN direction='deposit' THEN amount_copper ELSE -amount_copper END) FROM treasury_ledger").fetchone()[0]
   self.assertEqual(ledger,902500)
 def test_event_create_without_delete_permission(self):
  c=self.client_for('555555555555555555')
  self.assertEqual(c.get('/events/new').status_code,200)
  r=self.post(c,'/events/new',{'title':'Raid night','description':'Test','location':'Orgrimmar','starts_at':'2026-11-20T19:00','channel_id':'666666666666666666','kind':'general'})
  self.assertEqual(r.status_code,302)
  with sqlite3.connect(DB) as db:eid=db.execute('SELECT MAX(id) FROM guild_events').fetchone()[0]
  self.assertIsNotNone(eid)
  self.assertEqual(c.get(f'/events/{eid}').status_code,200)
  self.assertEqual(c.get(f'/events/{eid}/edit').status_code,403)
  self.assertEqual(self.post(c,f'/events/{eid}/action',{'operation':'delete'}).status_code,403)
 def test_owner_only_can_appoint_popes(self):
  c=self.client_for('111111111111111111')
  r=self.post(c,'/access/save',{'discord_id':'777777777777777777','display_name':'Pope','level':'pope'})
  self.assertEqual(r.status_code,302)
  pope=self.client_for('777777777777777777')
  self.assertEqual(self.post(pope,'/access/save',{'discord_id':'888888888888888888','display_name':'Another Pope','level':'pope'}).status_code,403)
  self.assertEqual(self.post(pope,'/access/save',{'discord_id':'888888888888888888','display_name':'Officer','level':'officer','permissions':'events'}).status_code,302)
 def test_no_accidental_permission_escalation(self):
  self.assertEqual(expand_permissions(['events','conduct']),('events','conduct'))
  self.assertNotIn('events_delete',expand_permissions(['events_create']))
  with app.test_request_context('/events'):
   from flask import session
   session['discord_id']='444444444444444444'
   self.assertNotIn('events_manage',current_access()['permissions'])
 def test_suggestion_triage_keeps_discord_fields(self):
  c=self.client_for('111111111111111111')
  with sqlite3.connect(DB) as db:
   cols={r[1] for r in db.execute('PRAGMA table_info(guild_suggestions)')}
   # Insert only required columns, independent of Discord runtime.
   cols_req=[r for r in db.execute('PRAGMA table_info(guild_suggestions)') if r[3] and r[4] is None and r[1]!='id']
   vals={'title':'Test proposal','body':'Try a guild movie night','author_id':'111111111111111111','author_name':'Tester','guild_id':'222222222222222222','channel_id':'666666666666666666','status':'submitted'}
   insert=[r[1] for r in cols_req]
   for name in insert:vals.setdefault(name,'')
   db.execute('INSERT INTO guild_suggestions ('+','.join(insert)+') VALUES ('+','.join('?'*len(insert))+')',[vals[n] for n in insert])
   sid=db.execute('SELECT MAX(id) FROM guild_suggestions').fetchone()[0]
  r=self.post(c,f'/suggestions/{sid}',{'status':'planned','staff_note':'We can schedule it','category':'Events','priority':'high','assigned_to':'Officer','internal_note':'Verify attendance'})
  self.assertEqual(r.status_code,302)
  with sqlite3.connect(DB) as db:
   row=db.execute('SELECT status,staff_note,category,priority,assigned_to,internal_note,revision FROM guild_suggestions WHERE id=?',(sid,)).fetchone()
   self.assertEqual(tuple(row[:6]),('planned','We can schedule it','Events','high','Officer','Verify attendance'))
   self.assertGreaterEqual(row[6],1)
  reader=self.client_for('444444444444444444')
  self.assertEqual(self.post(reader,f'/suggestions/{sid}',{'status':'closed','staff_note':'No','category':'Events','priority':'high'}).status_code,403)
 def test_csrf(self):
  c=self.client_for('111111111111111111')
  r=c.post('/treasury/record',data={'direction':'deposit','gold':'10','purpose':'Try'})
  self.assertEqual(r.status_code,403)

if __name__=='__main__':unittest.main()
