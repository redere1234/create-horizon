#!/usr/bin/env python3
"""Isolated original Create 6.0.10 client and local development control bridge.

Only the user's already cached Minecraft/NeoForge/Create files are read. All
copies, compiled bridge classes, worlds, settings and captures live in .local.
No account files are consulted, no installer is run and no EULA is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.local/java-reference'
PRISM = Path.home() / 'Library/Application Support/PrismLauncher'
JAVA = PRISM / 'java/java-runtime-delta/jre.bundle/Contents/Home'
SOURCE = ROOT / 'tools/java/reference_bridge'
NEOFORGE = '21.1.227'
CREATE_SHA256 = 'ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a'


def digest(path, algorithm='sha256'):
    result = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def write_json(path, value, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    if private:
        path.chmod(0o600)


def allowed(library):
    rules = library.get('rules', [])
    if not rules:
        return True
    result = False
    machine = platform.machine().lower()
    for rule in rules:
        operating = rule.get('os', {})
        name = operating.get('name')
        matches = name is None or name == 'osx' or (name == 'osx-arm64' and machine in ('arm64', 'aarch64'))
        if operating.get('arch'):
            matches &= bool(re.fullmatch(operating['arch'], machine))
        if rule.get('features'):
            matches = False
        if matches:
            result = rule['action'] == 'allow'
    name = library.get('name', '')
    # Prism's metadata lists both Mac architectures as "osx". Prefer the
    # actual host's individual native jars, as Prism's resolver does.
    if machine in ('arm64', 'aarch64') and 'natives-macos' in name and 'arm64' not in name:
        return False
    return result


def maven_path(name):
    group, artifact, version, *classifier = name.split(':')
    extension = 'jar'
    if '@' in version:
        version, extension = version.split('@', 1)
    suffix = '-' + '-'.join(classifier) if classifier else ''
    return Path(group.replace('.', '/')) / artifact / version / f'{artifact}-{version}{suffix}.{extension}'


def copy_file(source, destination, expected=None, algorithm='sha1'):
    if not source.is_file():
        raise RuntimeError(f'Required cached file is absent: {source}')
    if expected and digest(source, algorithm) != expected:
        raise RuntimeError(f'Cached file checksum differs: {source}')
    if not destination.is_file() or digest(source) != digest(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def official_asset(url, destination, expected):
    """Fetch only immutable hash-addressed Mojang resource data into .local."""
    if destination.is_file() and digest(destination, 'sha1') == expected:
        return
    if not url.startswith(('https://piston-meta.mojang.com/', 'https://resources.download.minecraft.net/')):
        raise RuntimeError('Unexpected resource host')
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha1(data).hexdigest() != expected:
        raise RuntimeError('Official resource checksum differs')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def prepare(base, prism, java, create_jar, port):
    if platform.system() != 'Darwin':
        raise RuntimeError('This cache adapter currently targets the verified macOS Prism installation')
    version = subprocess.check_output([str(java / 'bin/java'), '-version'], stderr=subprocess.STDOUT, text=True)
    if '21.0.7' not in version:
        raise RuntimeError('Reference requires the verified Java 21.0.7 runtime')
    if digest(create_jar) != CREATE_SHA256:
        raise RuntimeError('The supplied Create JAR differs from the pinned 6.0.10 reference')
    installer = prism / f'libraries/net/neoforged/neoforge/{NEOFORGE}/neoforge-{NEOFORGE}-installer.jar'
    with zipfile.ZipFile(installer) as archive:
        neo = json.loads(archive.read('version.json'))
    vanilla = json.loads((prism / 'meta/net.minecraft/1.21.1.json').read_text())
    lwjgl = json.loads((prism / 'meta/org.lwjgl3/3.3.3.json').read_text())
    libraries = {}
    for library in [*vanilla['libraries'], *lwjgl['libraries'], *neo['libraries']]:
        if not allowed(library):
            continue
        name = library['name']
        # NeoForge's dependency versions override the base game's versions.
        parts = name.split(':')
        key = tuple(parts[:2] + parts[3:])
        libraries[key] = library
    classpath = []
    for library in libraries.values():
        artifact = library.get('downloads', {}).get('artifact', {})
        relative = Path(artifact.get('path') or maven_path(library['name']))
        source = prism / 'libraries' / relative
        destination = base / 'libraries' / relative
        copy_file(source, destination, artifact.get('sha1'))
        classpath.append(str(destination))
    runtime_classpath = list(classpath)
    # FML locates the patched client, universal and split game files through
    # library_directory. They are compile inputs, not bootstrap modules: putting
    # them on the bootstrap classpath creates duplicate named game modules.
    for relative in [
        f'net/neoforged/neoforge/{NEOFORGE}/neoforge-{NEOFORGE}-client.jar',
        f'net/neoforged/neoforge/{NEOFORGE}/neoforge-{NEOFORGE}-universal.jar',
        'net/minecraft/client/1.21.1-20240808.144430/client-1.21.1-20240808.144430-srg.jar',
        'net/minecraft/client/1.21.1-20240808.144430/client-1.21.1-20240808.144430-extra.jar',
    ]:
        destination = base / 'libraries' / relative
        copy_file(prism / 'libraries' / relative, destination)
        if str(destination) not in classpath:
            classpath.append(str(destination))
    asset_index = vanilla['assetIndex']
    index = prism / 'assets/indexes' / (asset_index['id'] + '.json')
    pinned_index = base / 'assets/indexes' / index.name
    if digest(index, 'sha1') == asset_index['sha1']:
        copy_file(index, pinned_index, asset_index['sha1'])
    else:
        official_asset(asset_index['url'], pinned_index, asset_index['sha1'])
    index = pinned_index
    for record in json.loads(index.read_text())['objects'].values():
        name = record['hash']
        relative = Path(name[:2]) / name
        destination = base / 'assets/objects' / relative
        if not destination.is_file():
            source = prism / 'assets/objects' / relative
            if source.is_file():
                copy_file(source, destination, name)
            else:
                official_asset('https://resources.download.minecraft.net/' + relative.as_posix(), destination, name)
    for folder in ['game/mods', 'captures', 'schematics', 'natives', 'home', 'tmp', 'logs']:
        (base / folder).mkdir(parents=True, exist_ok=True)
    pinned = base / 'game/mods/create-1.21.1-6.0.10.jar'
    copy_file(create_jar, pinned, CREATE_SHA256, 'sha256')
    compile_deps = []
    with zipfile.ZipFile(pinned) as archive:
        for entry in json.loads(archive.read('META-INF/jarjar/metadata.json'))['jars']:
            relative = entry['path']
            path = base / 'compile-deps' / Path(relative).name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(relative))
            compile_deps.append(str(path))
    config_path = base / 'bridge-config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {'token': secrets.token_urlsafe(32)}
    config.update({'port': port, 'root': str(base), 'world': 'CreateJavaReference', 'seed': 5})
    write_json(config_path, config, private=True)
    options = base / 'game/options.txt'
    if not options.exists():
        options.write_text('lang:en_us\nrenderDistance:4\nsimulationDistance:4\nguiScale:2\n'
                           'enableVsync:false\nmaxFps:60\npauseOnLostFocus:false\n'
                           'fullscreen:false\ntutorialStep:none\nshowAutosaveIndicator:false\n')
    manifest = {'minecraft': '1.21.1', 'data_version': 3955, 'neoforge': NEOFORGE,
                'java': str(java), 'java_version': '21.0.7', 'create': '6.0.10',
                'create_sha256': CREATE_SHA256, 'classpath': classpath, 'runtime_classpath': runtime_classpath,
                'compile_deps': compile_deps, 'neo_profile': neo,
                'asset_index': asset_index['id'], 'world': config['world']}
    write_json(base / 'manifest.json', manifest)
    return {'prepared': str(base), 'minecraft': '1.21.1', 'neoforge': NEOFORGE,
            'java': '21.0.7', 'create': '6.0.10', 'libraries': len(classpath),
            'assets': len(json.loads(index.read_text())['objects'])}


def build(base):
    manifest = json.loads((base / 'manifest.json').read_text())
    classes = base / 'bridge-classes'
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(exist_ok=True)
    sources = sorted((SOURCE / 'java').rglob('*.java'))
    classpath = [*manifest['classpath'], str(base / 'game/mods/create-1.21.1-6.0.10.jar'), *manifest['compile_deps']]
    command = [str(Path(manifest['java']) / 'bin/javac'), '--release', '21', '-proc:none',
               '-cp', os.pathsep.join(classpath), '-d', str(classes), *map(str, sources)]
    subprocess.run(command, check=True)
    jar = base / 'game/mods/create-reference-bridge.jar'
    with zipfile.ZipFile(jar, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in classes.rglob('*.class'):
            archive.write(path, path.relative_to(classes).as_posix())
        for path in (SOURCE / 'resources').rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(SOURCE / 'resources').as_posix())
    return {'built': str(jar), 'sha256': digest(jar)}


def stage_schematic(base, source):
    if source.suffix != '.nbt' or not source.is_file():
        raise RuntimeError('A staged schematic must be an existing .nbt file')
    checksum = digest(source)
    name = source.stem + '-' + checksum[:12] + '.nbt'
    destination = base / 'schematics' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {'file': name, 'sha256': checksum, 'staged': str(destination)}


def process_alive(base):
    path = base / 'process.json'
    if not path.is_file():
        return False
    pid = json.loads(path.read_text())['pid']
    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
    state = status.stdout.strip()
    # A stopped JVM may still have a process table entry until its caller
    # reaps it. Its world and loopback server are already closed.
    return status.returncode == 0 and bool(state) and not state.startswith('Z')


def launch(base, wait=True, normal_world=False):
    if process_alive(base):
        raise RuntimeError('The isolated Java reference process is already running')
    manifest = json.loads((base / 'manifest.json').read_text())
    java = Path(manifest['java'])
    profile = manifest['neo_profile']
    values = {'library_directory': str(base / 'libraries'), 'classpath_separator': os.pathsep,
              'version_name': profile['id']}
    def expand(value):
        for key, replacement in values.items():
            value = value.replace('${' + key + '}', replacement)
        return value
    command = [str(java / 'bin/java'), '-XstartOnFirstThread', '-Xmx3G',
               '-Djava.io.tmpdir=' + str(base / 'tmp'), '-Duser.home=' + str(base / 'home'),
               '-Dorg.lwjgl.system.SharedLibraryExtractPath=' + str(base / 'natives'),
               '-Djava.library.path=' + str(base / 'natives'),
               '-Dcreate.reference.config=' + str(base / 'bridge-config.json'),
               '-Dcreate.reference.normal_world=' + str(normal_world).lower(),
               *map(expand, profile['arguments']['jvm']), '--add-modules', 'jdk.httpserver',
               '-cp', os.pathsep.join(manifest['runtime_classpath']), profile['mainClass'],
               '--username', 'CreateReference', '--uuid', 'a84d149a9dd64b17a9244ed14bc23bb8',
               '--accessToken', '0', '--userType', 'legacy', '--version', profile['id'],
               '--gameDir', str(base / 'game'), '--assetsDir', str(base / 'assets'),
               '--assetIndex', manifest['asset_index'], '--width', '1280', '--height', '720',
               *profile['arguments']['game']]
    env = os.environ.copy()
    env.update({'HOME': str(base / 'home'), 'XDG_DATA_HOME': str(base / 'home/data'),
                'XDG_CONFIG_HOME': str(base / 'home/config'), 'TMPDIR': str(base / 'tmp'),
                'HORIZON_HOME': str(base / 'home/horizon'),
                'HORIZON_LAUNCHER_HOME': str(base / 'home/horizon-launcher')})
    for variable in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'):
        env.pop(variable, None)
    ready = base / 'ready.json'
    ready.unlink(missing_ok=True)
    with (base / 'logs/client.log').open('ab') as log:
        process = subprocess.Popen(command, cwd=base / 'game', env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    write_json(base / 'process.json', {'pid': process.pid, 'started': time.time(),
                                      'version': profile['id'], 'root': str(base)})
    if wait:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Java client exited; inspect ' + str(base / 'logs/client.log'))
            try:
                status = call(base, 'state', {})
                if status.get('ready'):
                    return status
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(.5)
        raise RuntimeError('Reference readiness timed out; inspect ' + str(base / 'logs/client.log'))
    return {'pid': process.pid, 'root': str(base), 'ready_file': str(ready)}


def call(base, method, body):
    config = json.loads((base / 'bridge-config.json').read_text())
    ready_path = base / 'ready.json'
    if not ready_path.is_file():
        raise RuntimeError('Reference bridge has not announced its endpoint')
    ready = json.loads(ready_path.read_text())
    request = urllib.request.Request(ready['url'] + '/' + method,
        data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['token']})
    try:
        with urllib.request.urlopen(request, timeout=90) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=BASE)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--prism', type=Path, default=PRISM)
    prep.add_argument('--java', type=Path, default=JAVA)
    prep.add_argument('--create-jar', type=Path, default=ROOT / '.local/input-instance/mods/create-1.21.1-6.0.10.jar')
    prep.add_argument('--port', type=int, default=38261)
    sub.add_parser('build')
    stage = sub.add_parser('stage-schematic')
    stage.add_argument('file', type=Path)
    start = sub.add_parser('launch')
    start.add_argument('--no-wait', action='store_true')
    start.add_argument('--normal-world', action='store_true')
    invoke = sub.add_parser('call')
    invoke.add_argument('method')
    invoke.add_argument('body', nargs='?', default='{}', help='JSON object; @file reads a JSON file')
    sub.add_parser('status')
    sub.add_parser('stop')
    args = parser.parse_args()
    base = args.root.resolve()
    try:
        if args.action == 'prepare':
            result = prepare(base, args.prism.resolve(), args.java.resolve(), args.create_jar.resolve(), args.port)
        elif args.action == 'build':
            result = build(base)
        elif args.action == 'stage-schematic':
            result = stage_schematic(base, args.file.resolve())
        elif args.action == 'launch':
            result = launch(base, not args.no_wait, args.normal_world)
        elif args.action == 'call':
            body = Path(args.body[1:]).read_text() if args.body.startswith('@') else args.body
            result = call(base, args.method, json.loads(body))
        elif args.action == 'status':
            result = call(base, 'state', {}) if process_alive(base) else {'running': False}
        else:
            result = call(base, 'quit', {})
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
