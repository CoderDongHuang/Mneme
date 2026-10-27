"""Restrict both retrieval channels before ranking, including exact local search."""


class DocumentScope:
    def __init__(self, collection, document_ids: list[str]):
        self.collection = collection
        self.where = {"document_id": {"$in": list(dict.fromkeys(document_ids))}}

    def count(self):
        return len(self.collection.get(where=self.where, include=[]).get("ids", []))

    def get(self, **kwargs):
        kwargs["where"] = {"$and": [self.where, kwargs["where"]]} if kwargs.get("where") else self.where
        return self.collection.get(**kwargs)

    def query(self, **kwargs):
        kwargs["where"] = self.where
        return self.collection.query(**kwargs)
