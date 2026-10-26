"""Admit nested allocations through the registry owning their parent stage."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import re
import stat

from export_staging_directory import StageDirectoryChanged, identity, stage_directory


@contextmanager
def admit_staging_parent(parent):
    """Hold the parent's owning registry until the nested owner is durable.

    Outer cleanup holds this same registry. A delayed allocator must revalidate
    the parent after acquiring it, before it can create any nested namespace.
    Ordinary export destinations have no staging marker and need no extra lock.
    """
    from export_staging import MARKER, PREFIXES, decode_staging_marker, owner_identity_matches
    from export_staging_retirement import DIRECTORY, PosixRetirement
    parent = Path(parent)
    expected = identity(parent.stat())
    private = (parent.name == 'stage' and parent.parent.parent.name == DIRECTORY
               and re.fullmatch('[0-9a-f]{32}', parent.parent.name) is not None)
    with stage_directory(parent, expected) as authority:
        try:
            raw = authority.read_marker_bytes(4096)
        except FileNotFoundError:
            # render-* is also an ordinary user-selected project name. New
            # sound delivery stages use receipt-bound private paths; only the
            # old hidden staging prefixes provide a missing-marker signal.
            try:
                os.stat('.export-staging.owner.lock', dir_fd=authority.fd,
                        follow_symlinks=False)
                owner_present = True
            except FileNotFoundError:
                owner_present = False
            if (private or owner_present or any(parent.name.startswith(prefix)
                    for prefix in PREFIXES.values() if prefix.startswith('.'))):
                raise StageDirectoryChanged('Parent staging marker is missing')
            yield
            return
        marker = decode_staging_marker(raw)
        anchor = parent.parents[2] if private else parent.parent
        if (marker is None or marker['parent'] != str(anchor)
                or (not private and not parent.name.startswith(PREFIXES[marker['kind']]))):
            raise StageDirectoryChanged('Invalid parent staging authority')
    with PosixRetirement(parent=anchor, wait=True, create=not private) as owner:
        with stage_directory(parent, expected) as authority:
            if authority.read_marker_bytes(4096) != raw or authority.has_recovery_guard():
                raise StageDirectoryChanged('Parent staging authority changed')
            with authority.open_owner_stream() as stream:
                if private:
                    owner.open_slot(parent.parent.name)
                    owner.validate_initialized_creation(authority, stream)
                elif not owner_identity_matches(marker, stream):
                    raise StageDirectoryChanged('Parent staging owner changed')
                yield


class _CleanupBudget:
    def __init__(self):
        self.remaining = 256
        self.depth = 0


_BUDGET = ContextVar('export_nested_cleanup_budget', default=None)


def _retire_empty_unlocked_registry(authority, expected, retirement):
    """Resume interruption between retiring the nested lock and its directory.

    The owning-parent registry excludes allocations. An absent lock grants no
    authority over files or slots: only an exactly empty, pinned private root
    can be removed. A late entry makes rmdir fail without deleting that entry.
    """
    from export_staging_retirement import DIRECTORY, LOCK
    descriptor = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=authority.fd)
    try:
        info = os.fstat(descriptor)
        if (identity(info) != expected or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise StageDirectoryChanged('Unsafe interrupted nested registry')
        try:
            os.stat(LOCK, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            with os.scandir(descriptor) as entries:
                if next(entries, None) is not None:
                    raise StageDirectoryChanged('Unlocked nested registry has retained contents')
            from export_staging_nested_quarantine import retire_registry
            retire_registry(authority, expected, retirement, None)
            return True
        return False
    finally:
        os.close(descriptor)


def retire_nested_registry(authority, retirement=None):
    """Drain only receipt-admitted abandoned slots, preserving live owners.

    Caller retains the registry owning this stage, excluding new nested
    allocations. Nested registry and stage-owner locks are nonblocking. A
    failed drain leaves the registry and its payload available for recovery.
    """
    from export_staging_retirement import DIRECTORY, LOCK, PosixRetirement
    authority.check()
    try:
        info = os.stat(DIRECTORY, dir_fd=authority.fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise StageDirectoryChanged('Unsafe nested export registry')
    if retirement is None:
        raise StageDirectoryChanged('Nested cleanup requires owning registry admission')
    retirement.check()
    if _retire_empty_unlocked_registry(authority, identity(info), retirement):
        return
    budget = _BUDGET.get()
    token = None
    if budget is None:
        budget = _CleanupBudget()
        token = _BUDGET.set(budget)
    budget.depth += 1
    try:
        if budget.depth > 16:
            raise StageDirectoryChanged('Nested export recovery depth exceeded')
        with PosixRetirement(parent=authority.path, create=False) as nested:
            if identity(os.fstat(nested.fd)) != identity(info):
                raise StageDirectoryChanged('Nested export registry changed')
            for name in nested.slot_names():
                if budget.remaining <= 0:
                    raise StageDirectoryChanged('Nested export recovery budget exceeded')
                budget.remaining -= 1
                nested.recover_slot(name)
                # Slot descriptors stay owned by ExitStack until registry exit;
                # the shared work budget bounds the total open descriptors.
                nested.slot = nested.slot_fd = None
            nested.check()
            with os.scandir(nested.fd) as entries:
                if {entry.name for entry in entries} != {LOCK}:
                    raise StageDirectoryChanged('Nested export registry is not empty')
            authority.check()
            from export_staging_nested_quarantine import retire_registry
            retire_registry(authority, identity(info), retirement, nested.lock_stream)
    finally:
        budget.depth -= 1
        if token is not None:
            _BUDGET.reset(token)
