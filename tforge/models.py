import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

REF_PATTERN = re.compile(r"TF-\d+")


def normalize_ref(value: str) -> str:
    ref = value.strip().upper()
    if ref.isdigit():
        ref = f"TF-{ref}"
    if not REF_PATTERN.fullmatch(ref):
        raise ValueError(f"'{value}' is not a ticket ref (expected TF-<number> or just the number)")
    return ref


class Stage(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    CLOSED = "closed"

    @property
    def order(self) -> int:
        return list(Stage).index(self)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Ticket:
    ref: str
    title: str
    stage: Stage
    created: datetime
    description: str | None = None
    updated: datetime | None = None
    depends_on: list[str] = field(default_factory=list)
    custom_fields: dict[str, str] = field(default_factory=dict)
    owner: str | None = None

    @property
    def number(self) -> int:
        return int(self.ref.split("-")[-1])

    @classmethod
    def from_api(cls, data: dict) -> "Ticket":
        owner = data.get("owner") or {}
        return cls(
            ref=data["ref"],
            title=data["title"],
            stage=Stage(data["stage"]),
            created=parse_time(data["created"]),
            description=data.get("description"),
            updated=parse_time(data.get("updated")),
            depends_on=list(data.get("dependsOn") or []),
            custom_fields=dict(data.get("customFields") or {}),
            owner=owner.get("username"),
        )

    def to_json(self, details: bool = True) -> dict:
        data = {
            "ref": self.ref,
            "title": self.title,
            "description": self.description,
            "stage": self.stage.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat() if self.updated else None,
        }
        # List responses never include these fields; omit them rather than report misleading empty values.
        if details:
            data.update(dependsOn=self.depends_on, customFields=self.custom_fields, owner=self.owner)
        return data

    def to_payload(self) -> dict:
        # Full PUT body: any field left out would be cleared by the server.
        return {
            "title": self.title,
            "description": self.description,
            "stage": self.stage.value,
            "dependsOn": self.depends_on or None,
            "customFields": self.custom_fields,
        }


@dataclass
class CustomField:
    id: str
    name: str
    label: str
    type: str = "text"

    @classmethod
    def from_api(cls, data: dict) -> "CustomField":
        return cls(id=data["id"], name=data["name"], label=data["label"], type=data.get("type", "text"))
