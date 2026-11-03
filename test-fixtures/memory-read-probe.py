"""Explicit real-E2E probe: fail category reads for one newly created QA user."""
import json

_qa_scope = json.loads((_qa_root / 'scope.json').read_text())


class _QaMemoryCollection:
    def __init__(self, original):
        self._original = original

    def __getattr__(self, name):
        return getattr(self._original, name)

    def get(self, *args, **kwargs):
        conditions = kwargs.get('where', {}).get('$and', [])
        if ((_qa_root / 'fault').exists()
                and {'user_id': _qa_scope['user']} in conditions
                and any('category' in condition for condition in conditions)):
            raise OSError(_qa_scope['canary'])
        return self._original.get(*args, **kwargs)


memory_store._collection = _QaMemoryCollection(memory_store._collection)
