# research/dataset_builder.py
import json

class DatasetBuilder:
    def __init__(self):
        self.dataset = []

    def add_finding(self, finding: dict):
        self.dataset.append(finding)

    def to_json(self):
        return json.dumps(self.dataset, indent=2)
