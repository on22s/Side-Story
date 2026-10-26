"""Shared bounded receipt validation for export cleanup transactions.

Parsing validates recorded data; platform-specific admission must still bind
it to the actual directory, owner lock, and marker before deleting anything.
"""
import json
import re

from export_staging_directory import StageDirectoryChanged


def receipt_owner_identity(receipt, parent):
    """Use the inode locked at admission, including for legacy staging markers.

    Older retirement receipts can fall back to their original marker binding.
    A receipt with neither binding cannot establish ownership after a crash.
    """
    from export_staging import decode_staging_marker, _matches_parent
    marker = decode_staging_marker(receipt['marker'].encode('utf-8'))
    if (marker is None or not _matches_parent(marker, parent)
            or not receipt['original_name'].startswith(marker['prefix'])):
        raise StageDirectoryChanged('Invalid retirement marker authority')
    marker_owner = marker.get('owner_identity')
    expected = receipt.get('owner_identity', marker_owner)
    if expected is None or (marker_owner is not None and expected != marker_owner):
        raise StageDirectoryChanged('Missing or conflicting retirement owner identity')
    return expected


def decode_record(raw):
    """Validate imported checkpoint shape before any recovery operation."""
    if type(raw) is not bytes or not 0 < len(raw) <= 8192:
        raise StageDirectoryChanged('Invalid retirement receipt size')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate receipt field')
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError('Nonfinite receipt value')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, RecursionError) as error:
        raise StageDirectoryChanged('Invalid retirement receipt JSON') from error
    return value


def decode_receipt(raw):
    value = decode_record(raw)
    fields = {'schema', 'original_name', 'parent_identity', 'stage_identity', 'marker'}
    if (type(value) is not dict or set(value) not in (fields, fields | {'owner_identity'})
            or type(value['schema']) is not int or value['schema'] != 1):
        raise StageDirectoryChanged('Invalid retirement receipt schema')
    name = value['original_name']
    if (type(name) is not str or not 0 < len(name) <= 255 or name in ('.', '..')
            or any(character in name for character in ('/', '\\', '\x00'))):
        raise StageDirectoryChanged('Invalid original staging name')
    for key in ('parent_identity', 'stage_identity', 'owner_identity'):
        if key == 'owner_identity' and key not in value:
            continue
        pair = value[key]
        if (type(pair) is not list or len(pair) != 2
                or any(type(number) is not int or not 0 <= number < 2**128 for number in pair)):
            raise StageDirectoryChanged('Invalid retirement identity')
    marker = value['marker']
    try:
        valid_marker = type(marker) is str and 0 < len(marker.encode('utf-8')) <= 4096
    except UnicodeError:
        valid_marker = False
    if not valid_marker:
        raise StageDirectoryChanged('Invalid retirement marker bytes')
    # Marker content is retained verbatim for later comparison against the
    # admitted stage; this parser does not grant marker/reclaim authority.
    return value


def decode_creation_receipt(raw, *, complete, owner=False):
    from export_staging import PREFIXES
    value = decode_record(raw)
    fields = {'schema', 'kind', 'token', 'parent_identity', 'slot_identity'}
    if complete:
        fields.add('stage_identity')
    if owner:
        fields.add('owner_identity')
    if (type(value) is not dict or set(value) != fields
            or type(value['schema']) is not int or value['schema'] != 1
            or type(value['kind']) is not str or value['kind'] not in PREFIXES
            or type(value['token']) is not str
            or re.fullmatch('[0-9a-f]{32}', value['token']) is None):
        raise StageDirectoryChanged('Invalid creation receipt schema')
    for key in ('parent_identity', 'slot_identity', 'stage_identity', 'owner_identity'):
        if key not in value:
            continue
        pair = value[key]
        if (type(pair) is not list or len(pair) != 2
                or any(type(number) is not int or not 0 <= number < 2**128 for number in pair)):
            raise StageDirectoryChanged('Invalid creation identity')
    return value
