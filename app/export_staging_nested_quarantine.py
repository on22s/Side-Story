"""Bind a nested registry to a private sibling slot before deleting its name."""
from contextlib import contextmanager
import json
import os
import stat

from audio_take_history import _version
from export_staging_directory import StageDirectoryChanged, identity, stage_directory
from export_staging_records import decode_record
from utils import file_lock

RECEIPT = 'nested-registry.json'
PENDING_RECEIPT = RECEIPT + '.pending'
PAYLOAD = 'registry'


def _read_receipt(authority):
    descriptor = os.open(RECEIPT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=authority.fd)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                or not 0 < info.st_size <= 4096):
            raise StageDirectoryChanged('Unsafe nested registry receipt')
        raw = stream.read(4097)
        named = os.stat(RECEIPT, dir_fd=authority.fd, follow_symlinks=False)
        if (len(raw) > 4096 or _version(info) != _version(named)
                or _version(info) != _version(os.fstat(stream.fileno()))):
            raise StageDirectoryChanged('Nested registry receipt changed')
    value = decode_record(raw)
    if (type(value) is not dict
            or set(value) != {'schema', 'quarantine_identity', 'outer_identity',
                             'registry_identity', 'owner_identity'}
            or type(value['schema']) is not int or value['schema'] != 1):
        raise StageDirectoryChanged('Invalid nested registry receipt')
    for field in ('quarantine_identity', 'outer_identity', 'registry_identity', 'owner_identity'):
        pair = value[field]
        if field == 'owner_identity' and pair is None:
            continue
        if (type(pair) is not list or len(pair) != 2
                or any(type(number) is not int or not 0 <= number < 2**128 for number in pair)):
            raise StageDirectoryChanged('Invalid nested registry identity')
    if value['quarantine_identity'] != list(authority.expected):
        raise StageDirectoryChanged('Nested quarantine identity mismatch')
    return value


@contextmanager
def ensure_quarantine_removal(authority, held_stream=None):
    """Validate dedicated payload/owner bindings before generic slot cleanup."""
    from export_staging import MARKER, OWNER_LOCK, decode_staging_marker
    from export_staging_retirement import LOCK
    try:
        marker = decode_staging_marker(authority.read_marker_bytes(4096))
    except FileNotFoundError:
        yield False
        return
    if marker is None or marker['kind'] != 'nested_registry':
        yield False
        return
    try:
        record = _read_receipt(authority)
    except FileNotFoundError:
        # Creation may fail before the receipt or any payload is published.
        with os.scandir(authority.fd) as entries:
            if any(entry.name not in (MARKER, OWNER_LOCK + '.lock', PENDING_RECEIPT)
                   for entry in entries):
                raise StageDirectoryChanged('Unbound nested quarantine payload preserved')
        try:
            pending = os.stat(PENDING_RECEIPT, dir_fd=authority.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if (not stat.S_ISREG(pending.st_mode) or pending.st_nlink != 1
                    or pending.st_uid != os.geteuid() or stat.S_IMODE(pending.st_mode) != 0o600
                    or pending.st_size > 4096):
                raise StageDirectoryChanged('Unsafe pending nested registry receipt')
        yield False
        return
    with os.scandir(authority.fd) as entries:
        if any(entry.name not in (MARKER, OWNER_LOCK + '.lock', RECEIPT, PAYLOAD)
               for entry in entries):
            raise StageDirectoryChanged('Unknown nested quarantine contents preserved')
    try:
        info = os.stat(PAYLOAD, dir_fd=authority.fd, follow_symlinks=False)
    except FileNotFoundError:
        yield True
        return
    if (not stat.S_ISDIR(info.st_mode) or list(identity(info)) != record['registry_identity']
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise StageDirectoryChanged('Moved nested registry mismatch preserved')
    with stage_directory(authority.path / PAYLOAD, tuple(record['registry_identity'])) as payload:
        with os.scandir(payload.fd) as entries:
            first = next(entries, None)
            if next(entries, None) is not None:
                raise StageDirectoryChanged('Retained nested registry payload preserved')
            names = set() if first is None else {first.name}
        if not names:
            yield True
            return
        if names != {LOCK} or record['owner_identity'] is None:
            raise StageDirectoryChanged('Retained nested registry payload preserved')
        descriptor = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=payload.fd)
        with os.fdopen(descriptor, 'r+b') as stream:
            def check_owner(selected):
                opened = os.fstat(selected.fileno())
                named = os.stat(LOCK, dir_fd=payload.fd, follow_symlinks=False)
                if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o600
                        or opened.st_size > 4096
                        or list(identity(opened)) != record['owner_identity']
                        or identity(named) != identity(opened)):
                    raise StageDirectoryChanged('Nested registry owner changed')
            check_owner(stream)
            if held_stream is not None:
                check_owner(held_stream)
                yield True
            else:
                with file_lock(payload.path / 'owner', timeout=0, lock_handle=stream):
                    check_owner(stream)
                    yield True


def retire_registry(authority, registry_identity, retirement, owner_stream):
    """Keep the original lock held while moving to a separately bound slot."""
    from export_staging_retirement import DIRECTORY
    with retirement.additional_slot() as quarantine:
        path, expected, _, owner, stream = quarantine.initialize_creation('nested_registry')
        try:
            with stage_directory(path, expected) as target:
                record = {'schema': 1, 'quarantine_identity': list(expected),
                          'outer_identity': list(authority.expected),
                          'registry_identity': list(registry_identity),
                          'owner_identity': (None if owner_stream is None else
                                             list(identity(os.fstat(owner_stream.fileno()))))}
                raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
                descriptor = os.open(PENDING_RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=target.fd)
                with os.fdopen(descriptor, 'wb') as receipt:
                    if receipt.write(raw) != len(raw):
                        raise OSError('Short nested receipt write')
                    receipt.flush()
                    os.fsync(receipt.fileno())
                os.rename(PENDING_RECEIPT, RECEIPT, src_dir_fd=target.fd, dst_dir_fd=target.fd)
                os.fsync(target.fd)
                authority.check()
                target.check()
                os.rename(DIRECTORY, PAYLOAD, src_dir_fd=authority.fd, dst_dir_fd=target.fd)
                os.fsync(target.fd)
                os.fsync(authority.fd)
                # Cleanup validates the moved object against the receipt. A
                # foreign replacement is retained in its own private slot.
                quarantine.cleanup_initialized_creation(target, stream,
                                                         nested_owner_stream=owner_stream)
        finally:
            owner.__exit__(None, None, None)
        quarantine.discard_empty_slot(quarantine.slot)
