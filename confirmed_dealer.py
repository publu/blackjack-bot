"""Connect a verified camera result to a pending game card; never moves arms.

A future authorized controller adapter must call this only for its owned deal.
The current practice server deliberately exposes no motion dispatch endpoint.
"""
class ConfirmedDealer:
    def __init__(self,game):self.game=game;self.observations={};self.tasks={}
    def bind(self,token,owned_task_id):
        if not self.game.pending or self.game.pending[0]['id']!=token:raise ValueError('No matching pending card')
        if not isinstance(owned_task_id,str) or not owned_task_id:raise ValueError('Owned task ID required')
        if token in self.tasks and self.tasks[token]!=owned_task_id:raise ValueError('Cannot replace an unresolved card task')
        self.tasks[token]=owned_task_id

    def accept(self,token,observation):
        g=self.game
        if not g.pending or g.pending[0]['id']!=token:raise ValueError('No matching pending card')
        if observation.get('verified') is not True:
            g.camera_unknown(token,observation.get('evidence') or 'Camera could not verify the card')
            g.revision+=1
            return False
        ident=observation.get('card_id')
        if not isinstance(ident,str) or not ident or not observation.get('task_id'):raise ValueError('Task-linked camera evidence required')
        if self.tasks.get(token)!=observation.get('task_id'):raise ValueError('Camera result belongs to a different or unbound task')
        if ident in self.observations:raise ValueError('This camera observation was already counted')
        g.confirm(token,observation.get('rank'),observation.get('suit'),'camera',observation.get('evidence'))
        self.observations[ident]=token
        g.revision+=1
        return True
