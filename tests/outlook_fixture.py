"""Fictional Outlook rows and the complete command response, backed by real files.

The fixture owns mutable mail rows; each invocation receives a JSON copy of its
request. Ordinary policy cases call it directly. One integration scenario runs
this same fixture in a child process to retain the stdin/file-response boundary.
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import cast

type Record = dict[str, object]


def read(path: Path) -> Record:
    return cast(Record, json.loads(path.read_text(encoding='utf-8')))


def create(root: Path, index: Path, request: Record) -> Record:
    key = cast(str, request['key'])
    record = read(index / (key + '.json'))
    assert record['fingerprint'] == request['fingerprint'] and record['folder'] == request['folder']
    assert record['kind'] == 'pending_outlook', 'A durable mailbox binding must precede Save.'
    result: Record = {
        'kind': 'draft', 'entry_id': 'item-' + key, 'folder': request['folder'],
        'key': key, 'fingerprint': request['fingerprint'], 'content': request['content'],
        'saved': True, 'sent': False, 'submitted': False,
    }
    folder = cast(Record, request['folder'])
    name = hashlib.sha256(cast(str, folder['store_id']).encode()).hexdigest() + '-' + key + '.json'
    (root / 'items' / name).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result


def corrupt(result: Record, mode: str) -> None:
    if result.get('kind') != 'draft':
        return
    content = cast(Record, result['content'])
    match mode:
        case 'short_body':
            content['body'] = cast(str, content['body'])[:7]
        case 'extra_bcc':
            cast(list[object], content['bcc']).append('unexpected@example.invalid')
        case 'wrong_store':
            cast(Record, result['folder'])['store_id'] = 'unrelated-store'
        case 'already_sent':
            result['sent'] = True
        case 'malformed_recipient':
            content['to'] = ['unresolved recipient']
        case _:
            pass


def response(root: Path, index: Path, request: Record) -> tuple[int, Record]:
    control = read(root / 'control.json')
    operation = request['operation']
    with (root / 'calls.jsonl').open('a', encoding='utf-8') as calls:
        row: dict[str, object] = {'operation': operation, 'folder': request.get('folder')}
        calls.write(json.dumps(row) + '\n')
    if operation == 'status':
        result: Record = ({'kind': 'unavailable', 'reason': 'Classic Outlook is not running.'}
                          if control['mode'] == 'unavailable' else
                          {'kind': 'available', 'folder': {'entry_id': control['folder'], 'store_id': control['store']}})
        return 0, result
    (root / 'items').mkdir(exist_ok=True)
    found = tuple(value for path in (root / 'items').glob('*.json')
                  if (value := read(path))['folder'] == request['folder']
                  and (value['entry_id'] == request['entry_id'] if operation == 'read' else value['key'] == request['key']))
    if control['mode'] == 'unavailable':
        result = {'kind': 'unavailable', 'reason': 'The original mailbox is unavailable.'}
    elif len(found) > 1:
        result = {'kind': 'conflict', 'reason': 'Multiple items have this workflow key.'}
    elif found:
        result = found[0]
    elif operation != 'ensure':
        result = {'kind': 'missing'}
    else:
        result = create(root, index, request)
        if control['mode'] == 'lose_ack':
            return 17, {}
    corrupt(result, cast(str, control['mode']))
    return 0, result


def perform(payload: Record) -> tuple[int, str]:
    code, result = response(Path(cast(str, payload['fixture'])), Path(cast(str, payload['index'])),
                            cast(Record, payload['request']))
    if not code:
        Path(cast(str, payload['response'])).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return code, ''


if __name__ == '__main__':
    result, _text = perform(cast(Record, json.load(sys.stdin)))
    raise SystemExit(result)
