from copy import deepcopy
from unittest.mock import Mock

import pytest

from scripts.rebuild_embeddings import rebuild, restore


def collection():
    store = Mock(name="collection")
    store.name = "user_1_kb_1"
    store.metadata = {"user_id": "1", "kb_id": "1", "embedding_profile": "old"}
    store.get.return_value = {"ids": ["a", "b"], "documents": ["first", "second"],
                              "metadatas": [{"page": 1}, {"page": 2}], "embeddings": [[1, 0], [0, 1]]}
    return store


def test_provider_outage_preserves_original_and_snapshot(tmp_path):
    store = collection()
    embed = Mock(side_effect=RuntimeError("offline"))
    path = tmp_path / "snapshot.json"
    with pytest.raises(RuntimeError):
        rebuild(store, embed, path)
    store.update.assert_not_called()
    store.modify.assert_not_called()
    assert path.is_file() and path.with_suffix(".json.sha256").is_file()
    with pytest.raises(FileExistsError):
        rebuild(store, embed, path)


def test_partial_write_failure_restores_vectors_and_profile(tmp_path):
    store = collection()
    store.update.side_effect = [RuntimeError("storage disconnected"), None]
    embed = Mock(return_value=[[0.5, 0.5], [0.2, 0.8]])
    embed.profile.return_value = "new"
    with pytest.raises(RuntimeError):
        rebuild(store, embed, tmp_path / "snapshot.json")
    assert store.update.call_args.kwargs["embeddings"] == [[1, 0], [0, 1]]
    store.modify.assert_called_once_with(metadata=store.metadata)


def test_success_preserves_source_ids_metadata_and_reversible_snapshot(tmp_path):
    store = collection()
    old = deepcopy(store.get.return_value)
    embed = Mock(return_value=[[0.5, 0.5], [0.2, 0.8]])
    embed.profile.return_value = "new"
    result = rebuild(store, embed, tmp_path / "snapshot.json")
    assert result["rows"] == 2
    assert store.update.call_args.kwargs["ids"] == old["ids"]
    store.modify.assert_called_once_with(metadata={**store.metadata, "embedding_profile": "new"})
    restore(store, {**old, "metadata": store.metadata})
    assert store.update.call_args.kwargs["metadatas"] == old["metadatas"]
