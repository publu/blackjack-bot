"""Sequential real-card game runner. Never retries motion after an uncertain result."""
import threading
import time

class RobotPlay:
    def __init__(self, table, reader):
        self.table, self.reader = table, reader
        self.thread = None
        self.cancel = threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            raise ValueError('The robot is already playing this hand')
        self.cancel.clear()
        self.table.robot_running = True
        self.table.robot_message = 'Preparing the next card'
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def pause(self):
        self.cancel.set()

    def update(self, message):
        with self.table.lock:
            self.table.robot_message = message
            self.table.revision += 1

    def run(self):
        t = self.table
        try:
            while not self.cancel.is_set():
                with t.lock:
                    if not t.queue:
                        return
                    if t.task_unknown:
                        raise ValueError('The last motion response was lost. The arm operator must reconcile it before continuing.')
                    if not t.task:
                        self.update('Dealing to ' + t.queue[0])
                        t.vision_before = self.reader.capture()
                        if self.cancel.is_set():
                            return
                        t.action({'action': 'robot_deal', 'revision': t.revision})
                deadline = time.monotonic() + 240
                while not self.cancel.is_set():
                    with t.lock:
                        t.action({'action': 'refresh_task', 'revision': t.revision})
                        task = dict(t.task)
                    if task.get('status') in ('done', 'complete'):
                        break
                    if task.get('status') in ('failed', 'stopped', 'cancelled'):
                        raise ValueError('Deal ' + task['status'] + '. Inspect the physical card before continuing; it will not be redealt automatically.')
                    if time.monotonic() > deadline:
                        with t.lock:
                            t.action({'action': 'stop', 'revision': t.revision})
                        raise ValueError('Deal timed out; an owned stop was requested. Inspect the arms.')
                    self.cancel.wait(1)
                if self.cancel.is_set():
                    return
                self.update('Reading the dealt card with the camera')
                task['_vision_before'] = t.vision_before
                observed = self.reader.read(task)
                if observed.get('verified') is not True:
                    raise ValueError('Camera could not verify the card; no score was changed')
                with t.lock:
                    if self.cancel.is_set():
                        return
                    if not t.task or t.task['id'] != task['id']:
                        raise ValueError('Deal changed while reading the camera')
                    t.add_card(observed['rank'], observed['suit'])
                    t.last_observation = observed
                    t.revision += 1
                    self.update('Read ' + observed['rank'] + ' ' + observed['suit'])
        except Exception as exc:
            self.update('Paused: ' + str(exc))
        finally:
            with t.lock:
                t.robot_running = False
                t.revision += 1
