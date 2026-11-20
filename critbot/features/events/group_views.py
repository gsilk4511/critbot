"""Role/class and single-choice group signup controls."""
import discord
from .store import describe,participants,signup

class OwnedView(discord.ui.View):
    def __init__(self,owner):super().__init__(timeout=180);self.owner=owner
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message('Open your own group signup to use these controls.',ephemeral=True);return False
        return True

class ToonNameModal(discord.ui.Modal, title='Join a guild group'):
    character = discord.ui.TextInput(label='Your character name', min_length=2, max_length=40,
        placeholder='Enter your in-game character name')

    def __init__(self, owner, event, connect, source, choice, class_name):
        super().__init__();self.owner=owner;self.event=event;self.connect=connect
        self.source=source;self.choice=choice;self.class_name=class_name

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message('This signup belongs to another member.',ephemeral=True);return
        try:
            with self.connect() as db:
                signup(db,self.event['id'],interaction.user.id,str(self.character.value).strip(),
                    self.choice,self.class_name,interaction.guild_id,interaction.channel_id,self.source)
            await interaction.response.send_message('✅ Your character is on the roster. The Discord post will refresh shortly.',ephemeral=True)
        except ValueError as error:
            await interaction.response.send_message(str(error),ephemeral=True)


class SignupView(OwnedView):
    def __init__(self,owner,event,connect,source_message):
        super().__init__(owner);self.event=event;self.connect=connect;self.source=source_message
        self.choice=None;self.class_name='';config=event['config']
        self.slots=config['slots']
        if config['require_class']:
            classes=discord.ui.Select(placeholder='1. Choose your class',row=0,
                options=[discord.SelectOption(label=c,value=c) for c in config['classes']][:25])
            self.classes=classes
            async def select_class(interaction):
                self.class_name=classes.values[0]
                self.roles.disabled=False
                for option in classes.options:option.default=option.value==self.class_name
                if event['kind'] in ('dungeon','raid'):
                    from .store import CLASS_ROLES
                    eligible=set(CLASS_ROLES.get(self.class_name,()))
                    allowed=[discord.SelectOption(label=o['name'],value=o['key'],
                        description=f"{o['capacity']} slots" if o['capacity'] else 'No cap')
                        for o in self.slots if o['name'] in eligible]
                    self.roles.options=allowed or [discord.SelectOption(label='No compatible role available',value='none')]
                    self.roles.disabled=not bool(allowed)
                    if not any(o.value==self.choice for o in allowed):self.choice=None
                self.confirm.disabled=not self.choice or not self.class_name
                await interaction.response.edit_message(view=self)
            classes.callback=select_class;self.add_item(classes)
        else:self.classes=None
        options=self._available_options()
        self.roles=discord.ui.Select(placeholder='2. Choose a group role' if self.classes else 'Choose a signup option',
            options=options,row=1 if self.classes else 0,disabled=bool(self.classes))
        async def select_choice(interaction):
            self.choice=self.roles.values[0]
            for option in self.roles.options:option.default=option.value==self.choice
            self.confirm.disabled=not self.choice or (bool(self.classes) and not self.class_name)
            await interaction.response.edit_message(view=self)
        self.roles.callback=select_choice;self.add_item(self.roles)
        self.confirm=discord.ui.Button(label='3. Add your character' if self.classes else 'Confirm signup',
            style=discord.ButtonStyle.success,row=2,disabled=True)
        async def confirm(interaction):
            if self.classes and self.event['kind'] in ('dungeon','raid'):
                from .store import validate_role_class
                slot=next((x for x in self.slots if x['key']==self.choice),None)
                if not slot:
                    await interaction.response.send_message('Choose a role first.',ephemeral=True);return
                try:validate_role_class(self.event['kind'],slot['name'],self.class_name)
                except ValueError as exc:
                    await interaction.response.send_message(str(exc),ephemeral=True);return
            await interaction.response.send_modal(ToonNameModal(owner,event,connect,source_message,self.choice,self.class_name))
        self.confirm.callback=confirm;self.add_item(self.confirm)

    def _available_options(self):
        return [discord.SelectOption(label=o['name'],value=o['key'],
            description=f"{o['capacity']} slots" if o['capacity'] else 'No cap') for o in self.slots]

class RosterView(OwnedView):
    def __init__(self,owner,event,people):
        super().__init__(owner);self.event=event;self.people=people;self.page=0
        for shift,label in [(-1,'Previous'),(1,'Next')]:
            button=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary)
            async def callback(interaction,shift=shift):
                self.page=max(0,min(self.page+shift,max(0,(len(people)-1)//10)));self.update()
                await interaction.response.edit_message(embed=self.embed(),view=self)
            button.callback=callback;self.add_item(button)
        self.update()
    def update(self):self.children[0].disabled=self.page==0;self.children[1].disabled=(self.page+1)*10>=len(self.people)
    def embed(self):
        slots={s['key']:s['name'] for s in self.event['config']['slots']}
        lines=[f"**{discord.utils.escape_markdown(p['name'])}** — {slots.get(p['choice'],'Unknown')}"+(f" · {p['class_name']}" if p['class_name'] else '') for p in self.people[self.page*10:(self.page+1)*10]]
        card=discord.Embed(title=self.event['title'][:256],description='\n'.join(lines) or 'No signups yet.',color=0xe3bc77)
        card.set_footer(text=f"Group roster • Page {self.page+1}/{max(1,(len(self.people)+9)//10)}");return card

def add_controls(view,connect,event,closed):
    for action,label,style in [('join','Join / change signup',discord.ButtonStyle.success),('leave','Leave group',discord.ButtonStyle.secondary),('roster','View roster',discord.ButtonStyle.secondary)]:
        button=discord.ui.Button(label=label,style=style,custom_id=f"critbot:event:{event['id']}:{action}",disabled=closed and action!='roster')
        async def callback(interaction,action=action):
            if interaction.guild is None or interaction.user.bot:
                await interaction.response.send_message('Groups are for server members.',ephemeral=True);return
            with connect() as db:
                fresh=db.execute('SELECT * FROM guild_events WHERE id=?',(event['id'],)).fetchone()
                if fresh is None or (fresh['guild_id'],fresh['channel_id'],fresh['message_id'])!=(str(interaction.guild_id),str(interaction.channel_id),str(interaction.message.id)):
                    await interaction.response.send_message('This group message is no longer active.',ephemeral=True);return
                data=describe(fresh);people=[p for p in participants(db,event['id']) if p['rsvp']=='going']
            if action=='roster':
                roster=RosterView(interaction.user.id,data,people)
                await interaction.response.send_message(embed=roster.embed(),view=roster,ephemeral=True);return
            if fresh['status']!='posted':await interaction.response.send_message('This group is closed.',ephemeral=True);return
            if action=='join':
                await interaction.response.send_message('Choose one signup option'+(' and your class.' if data['config']['require_class'] else '.'),view=SignupView(interaction.user.id,data,connect,interaction.message.id),ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
                try:
                    with connect() as db:signup(db,event['id'],interaction.user.id,interaction.user.display_name,None,'',interaction.guild_id,interaction.channel_id,interaction.message.id)
                    await interaction.followup.send('You left the group. Your slot is available again.',ephemeral=True)
                except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
        button.callback=callback;view.add_item(button)
    if event['kind']=='dungeon' and event['config'].get('leader_id'):
        manage=discord.ui.Button(label='Manage group',style=discord.ButtonStyle.secondary,custom_id=f"critbot:event:{event['id']}:manage",disabled=closed and event['status'] not in ('full','started'))
        async def manage_group(interaction):
            if str(interaction.user.id)!=str(event['config']['leader_id']):
                await interaction.response.send_message('Only the group leader can manage this listing.',ephemeral=True);return
            with connect() as db:fresh=db.execute('SELECT * FROM guild_events WHERE id=?',(event['id'],)).fetchone()
            source=interaction.message.id
            if fresh is None or fresh['status'] not in ('posted','full','started') or (fresh['guild_id'],fresh['channel_id'],fresh['message_id'])!=(str(interaction.guild_id),str(interaction.channel_id),str(source)):
                await interaction.response.send_message('This listing is no longer open.',ephemeral=True);return
            panel=OwnedView(interaction.user.id)
            for action,label in [('full','Reopen recruitment' if fresh['status']=='full' else 'Mark full'),('started','Run started'),('completed','Close group')]:
                button=discord.ui.Button(label=label,style=discord.ButtonStyle.danger if action=='completed' else discord.ButtonStyle.secondary,disabled=fresh['status']=='started' and action!='completed')
                async def leader_action(private,action=action):
                    await private.response.defer(ephemeral=True)
                    with connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        current=db.execute('SELECT * FROM guild_events WHERE id=?',(event['id'],)).fetchone()
                        allowed=('posted','full','started') if action=='completed' else ('posted','full')
                        if current is None or current['status'] not in allowed or (current['guild_id'],current['channel_id'],current['message_id'])!=(str(private.guild_id),str(private.channel_id),str(source)) or str(private.user.id)!=str(event['config']['leader_id']):
                            await private.followup.send('This action is no longer available.',ephemeral=True);return
                        status=('posted' if current['status']=='full' else 'full') if action=='full' else action
                        db.execute('UPDATE guild_events SET status=?,revision=revision+1 WHERE id=?',(status,event['id']))
                    await private.edit_original_response(content='✅ Group updated. The post will refresh shortly.',view=None)
                button.callback=leader_action;panel.add_item(button)
            await interaction.response.send_message('Manage your dungeon group',view=panel,ephemeral=True)
        manage.callback=manage_group;view.add_item(manage)
