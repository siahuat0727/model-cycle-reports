"""Select public scenes and remove detail assets no longer referenced by them."""
import json
from pathlib import Path, PurePosixPath
from publisher.catalog import identifier

CONFIG = Path(__file__).resolve().parents[1] / 'publication.json'


def scene_ids():
    config = json.loads(CONFIG.read_text())
    if set(config) != {'scene_ids'} or not isinstance(config['scene_ids'], list):
        raise ValueError('Invalid publication scene configuration')
    ids = [identifier(value) for value in config['scene_ids']]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Publication scenes must be nonempty and unique')
    return set(ids)


def select(run, allowed):
    scenes = [scene for scene in run['scenes'] if scene['scene_id'] in allowed]
    return dict(run, scenes=scenes) if scenes else None


def prune_details(destination, entries):
    referenced = set()
    for entry in entries:
        for scene in entry['scenes']:
            for relative in scene.get('details', {}).values():
                path = PurePosixPath(relative)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'runs' or path.suffix != '.html':
                    raise ValueError('Invalid published detail path')
                referenced.add(path.as_posix())
    root = destination / 'runs'
    if not root.exists():
        return
    for path in root.rglob('*'):
        if path.is_file() and path.relative_to(destination).as_posix() not in referenced:
            path.unlink()
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
