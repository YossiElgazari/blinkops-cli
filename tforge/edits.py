from tforge.models import Stage, Ticket


def parse_field_assignments(values: list[str]) -> dict[str, str]:
    fields = {}
    for value in values:
        name, sep, field_value = value.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"'{value}' must look like name=value")
        fields[name.strip()] = field_value.strip()
    return fields


def apply_edits(
    ticket: Ticket,
    title: str | None = None,
    description: str | None = None,
    stage: Stage | None = None,
    add_deps: list[str] | None = None,
    remove_deps: list[str] | None = None,
    clear_deps: bool = False,
    set_fields: dict[str, str] | None = None,
    unset_fields: list[str] | None = None,
) -> dict:
    wanted: dict = {}
    if title is not None:
        wanted["title"] = title.strip()
    if description is not None:
        wanted["description"] = description.strip() or None
    if stage is not None:
        wanted["stage"] = stage

    deps = [] if clear_deps else list(ticket.depends_on)
    deps = [ref for ref in deps if ref not in (remove_deps or [])]
    for ref in add_deps or []:
        if ref not in deps:
            deps.append(ref)
    wanted["depends_on"] = deps

    fields = dict(ticket.custom_fields)
    for name in unset_fields or []:
        fields.pop(name, None)
    for name, value in (set_fields or {}).items():
        # An empty value removes the field, like in the web app.
        if value:
            fields[name] = value
        else:
            fields.pop(name, None)
    wanted["custom_fields"] = fields

    # Keep only real changes, so an update that changes nothing can skip the PUT.
    return {key: value for key, value in wanted.items() if getattr(ticket, key) != value}
