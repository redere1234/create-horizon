"""Isolated real-client checks: private resources, world, socket and transcript.

No production instance is opened. A restart uses the same private game directory
and a real process exit/start, so persistence tests cannot pass from RAM alone.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from common import ROOT


def wait_loaded(call, positions, attempts=40):
    """Wait for authoritative columns, beyond the client's wait-ready signal.

    A newly teleported camera can be ready before adjacent server columns exist.
    Check every caller-supplied fixture column before any world mutation.
    """
    positions = list(positions)
    for _ in range(attempts):
        replies = [call('command', 'execute if loaded ' + ' '.join(map(str, pos))
                        + ' run say create_fixture_column_loaded') for pos in positions]
        if all(any('create_fixture_column_loaded' in line for line in reply.get('chat', []))
               for reply in replies):
            return
        call('wait', 5)
    raise AssertionError(('Fixture server columns did not load', positions, replies))


class NativeCheckSession:
    def __init__(self, game, resources, ctl, create_jar, *, name='parity', graphics=True, audio=False,
                 size=(1280, 720), world='CreateParity06', username=None):
        if (not isinstance(world, str) or not world or world in ('.', '..')
                or any(c in world for c in '/\\') or not world.isprintable()):
            raise ValueError('The world must be one nonempty folder name, not a path')
        if username is not None and (not isinstance(username, str) or not 1 <= len(username) <= 16
                or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_' for c in username)):
            raise ValueError('An offline username must contain 1..16 ASCII letters, digits or underscores')
        self.world = world
        self.username = username
        self.game = Path(game).resolve()
        self.ctl = Path(ctl).resolve()
        self.graphics = graphics
        self.size = size
        self.scratch = Path(tempfile.mkdtemp(prefix=name + '-', dir=ROOT / '.local'))
        self.resources = self.scratch / 'resources'
        if os.uname().sysname == 'Darwin':
            subprocess.run(['cp', '-cR', str(Path(resources).resolve()), str(self.resources)], check=True)
        else:
            shutil.copytree(resources, self.resources)
        (self.scratch / 'horizon-mods.txt').write_text('mod.create:true\n')
        if create_jar is not None:
            inputs = self.scratch / 'horizon-mods/create-resources'
            inputs.mkdir(parents=True)
            shutil.copy2(create_jar, inputs / 'create.jar')
        self.env = os.environ.copy()
        for key, folder in [('HORIZON_HOME', 'home'), ('HORIZON_LAUNCHER_HOME', 'launcher'),
                            ('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'),
                            ('HORIZON_LAUNCHER_TRASH', 'trash'),
                            ('HORIZON_LAUNCHER_CLIPBOARD', 'clipboard'),
                            ('HORIZON_LAUNCHER_DESKTOP', 'desktop')]:
            self.env[key] = str(self.scratch / folder)
        self.env.update({'HORIZON_NO_AUDIO': '1', 'HORIZON_LAUNCHER_NO_SELF_UPDATE': '1',
                         'CREATE_HORIZON_TRACE': '1', 'CREATE_HORIZON_TRACE_POSES': '1',
                         'CREATE_HORIZON_PARTICLE_TRACE': '1'})
        if audio:
            self.env.pop('HORIZON_NO_AUDIO', None)
        # macOS sockaddr_un allows only 103 path bytes. Long workspace and
        # scenario names must not prevent an otherwise valid client launch.
        self.control_temp = tempfile.TemporaryDirectory(prefix='create-ctl-', dir='/private/tmp')
        self.socket = Path(self.control_temp.name) / 'ctl.sock'
        self.log = self.scratch / 'game.log'
        self.transcript = []
        self.process = None
        self.output = None
        self.starts = 0

    def call(self, *words, timeout=120):
        reply = subprocess.run([str(self.ctl), '--socket', str(self.socket), *map(str, words)],
                               env=self.env, text=True, capture_output=True, timeout=timeout)
        if reply.returncode:
            raise RuntimeError(str(words) + ': ' + reply.stdout + reply.stderr)
        value = json.loads(reply.stdout)
        self.transcript.append({'command': list(map(str, words)), 'reply': value})
        return value

    def start(self):
        if self.process is not None:
            raise RuntimeError('Client is already started')
        self.starts += 1
        self.output = self.log.open('a')
        self.output.write(f'\nNativeCheckSession process start {self.starts}\n')
        self.output.flush()
        command = [str(self.game), '--resources', str(self.resources), '--world', self.world,
                   '--seed', '5', '--creative', '--render-distance', '2',
                   '--control-socket', str(self.socket), '--width', str(self.size[0]), '--height', str(self.size[1])]
        # Args::parse in the pinned client maps --name to player_name. Vanilla's
        # --username is not accepted here. Omitted keeps the old generated name.
        if self.username is not None:
            command += ['--name', self.username]
        command += ['--offscreen'] if self.graphics else ['--headless']
        self.process = subprocess.Popen(command, cwd=self.scratch, env=self.env,
                                        stdout=self.output, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        while True:
            if self.process.poll() is not None:
                raise RuntimeError(self.log.read_text()[-8000:])
            try:
                self.call('state', timeout=5)
                break
            except (RuntimeError, subprocess.TimeoutExpired):
                if time.monotonic() > deadline:
                    raise
                time.sleep(.25)
        self.call('wait-ready', 120, timeout=150)
        return self

    def stop(self):
        process = self.process
        self.process = None
        try:
            if process is not None and process.poll() is None:
                try:
                    self.call('quit', timeout=30)
                    process.wait(timeout=30)
                except (RuntimeError, subprocess.TimeoutExpired):
                    process.terminate()
                    process.wait(timeout=10)
        finally:
            if self.output is not None:
                self.output.close()
                self.output = None
            self.save_transcript()

    def restart(self):
        self.stop()
        return self.start()

    def save_transcript(self):
        (self.scratch / 'transcript.json').write_text(json.dumps(self.transcript, indent=2) + '\n')

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.stop()
            self.control_temp.cleanup()
            raise

    def __exit__(self, *exception):
        try:
            self.stop()
        finally:
            self.control_temp.cleanup()
