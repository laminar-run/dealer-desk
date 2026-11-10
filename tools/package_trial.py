"""Package immutable native trial sources with byte-reproducible ZIP metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def package(checkout, revision, output):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args])
    commit = git('rev-parse', '--verify', revision + '^{commit}').decode().strip()
    names = git('ls-tree', '-r', '--name-only', commit).decode().splitlines()
    files = {}
    for name in names:
        path = Path(name)
        if (name in ('dealerdesk_trial.py', 'main.py', 'tfa.py', 'requirements-trial.txt', 'db/schema.sql') or
                (path.parts[0] in ('ui', 'db', 'chaos', 'models') and path.suffix == '.py') or
                name in ('docs/harness.md', 'docs/local-chaos-api.md')):
            files[name] = git('show', commit + ':' + name)
    if not {'dealerdesk_trial.py', 'main.py', 'db/schema.sql'} <= files.keys():
        raise ValueError('revision lacks required native trial files')
    native_names = [name for name in files if name in ('dealerdesk_trial.py', 'main.py', 'tfa.py', 'db/schema.sql') or
                    (Path(name).parts[0] in ('ui', 'db', 'chaos', 'models') and name.endswith('.py'))]
    native_build = hashlib.sha256(b''.join(name.encode() + b'\0' + files[name] for name in sorted(native_names))).hexdigest()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    files['release.json'] = json.dumps({'commit': commit, 'files': manifest}, sort_keys=True).encode()
    with output.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(files.items()):
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
    return {'commit': commit, 'archive': str(output.resolve()),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'files': len(files),
            'nativeBuildSha256': native_build}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', required=True, type=Path)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.checkout.resolve(), args.ref, args.output)))


if __name__ == '__main__':
    main()
