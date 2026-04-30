import json

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.tag import Tag
from app.schemas.tag import TagCreate, TagRead, TagUpdate


def tag_to_read(tag: Tag) -> TagRead:
    return TagRead(
        id=tag.id or 0,
        dataset_id=tag.dataset_id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        parent_id=tag.parent_id,
        aliases=_loads_aliases(tag.aliases_json),
    )


def list_tags(session: Session, dataset_id: int) -> list[TagRead]:
    tags = session.exec(select(Tag).where(Tag.dataset_id == dataset_id).order_by(Tag.name)).all()
    return [tag_to_read(tag) for tag in tags]


def create_tag(session: Session, dataset_id: int, payload: TagCreate) -> TagRead:
    name = payload.name.strip()
    aliases = _clean_aliases(payload.aliases)
    _validate_tag_identity(session, dataset_id, name, aliases)
    _validate_parent(session, dataset_id, payload.parent_id)
    tag = Tag(
        dataset_id=dataset_id,
        name=name,
        color=payload.color,
        description=payload.description,
        parent_id=payload.parent_id,
        aliases_json=json.dumps(aliases, ensure_ascii=False),
    )
    session.add(tag)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.") from exc
    session.refresh(tag)
    return tag_to_read(tag)


def get_tag_or_404(session: Session, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tag {tag_id} was not found.")
    return tag


def update_tag(session: Session, tag_id: int, payload: TagUpdate) -> TagRead:
    tag = get_tag_or_404(session, tag_id)
    updates = payload.model_dump(exclude_unset=True)
    next_name = updates["name"].strip() if "name" in updates and updates["name"] is not None else tag.name
    next_aliases = _clean_aliases(updates["aliases"]) if "aliases" in updates and updates["aliases"] is not None else _loads_aliases(tag.aliases_json)
    _validate_tag_identity(session, tag.dataset_id, next_name, next_aliases, current_id=tag.id)
    if "parent_id" in updates:
        _validate_parent(session, tag.dataset_id, updates["parent_id"], current_id=tag.id)

    if "name" in updates and updates["name"] is not None:
        tag.name = next_name
    if "color" in updates:
        tag.color = updates["color"]
    if "description" in updates:
        tag.description = updates["description"]
    if "parent_id" in updates:
        tag.parent_id = updates["parent_id"]
    if "aliases" in updates and updates["aliases"] is not None:
        tag.aliases_json = json.dumps(next_aliases, ensure_ascii=False)

    session.add(tag)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.") from exc
    session.refresh(tag)
    return tag_to_read(tag)


def delete_tag(session: Session, tag_id: int) -> None:
    tag = get_tag_or_404(session, tag_id)
    tag.samples.clear()
    session.add(tag)
    session.delete(tag)
    session.commit()


def _loads_aliases(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def find_tag_by_name_or_alias(session: Session, dataset_id: int, value: str) -> Tag | None:
    key = value.strip().casefold()
    if not key:
        return None
    tags = session.exec(select(Tag).where(Tag.dataset_id == dataset_id)).all()
    for tag in tags:
        if tag.name.casefold() == key:
            return tag
        if any(alias.casefold() == key for alias in _loads_aliases(tag.aliases_json)):
            return tag
    return None


def tag_matches_value(tag: Tag, value: str) -> bool:
    key = value.strip().casefold()
    return tag.name.casefold() == key or any(alias.casefold() == key for alias in _loads_aliases(tag.aliases_json))


def _clean_aliases(values: list[str]) -> list[str]:
    aliases: list[str] = []
    seen = set()
    for raw in values:
        alias = raw.strip()
        key = alias.casefold()
        if alias and key not in seen:
            seen.add(key)
            aliases.append(alias)
    return aliases


def _validate_tag_identity(
    session: Session,
    dataset_id: int,
    name: str,
    aliases: list[str],
    current_id: int | None = None,
) -> None:
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tag name is required.")

    name_key = name.casefold()
    alias_keys = set()
    for alias in aliases:
        alias_key = alias.casefold()
        if alias_key == name_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag alias conflicts with tag name: {alias}",
            )
        alias_keys.add(alias_key)

    tags = session.exec(select(Tag).where(Tag.dataset_id == dataset_id)).all()
    for tag in tags:
        if current_id is not None and tag.id == current_id:
            continue
        existing_keys = {tag.name.casefold(), *[alias.casefold() for alias in _loads_aliases(tag.aliases_json)]}
        if name_key in existing_keys:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag name conflicts with an existing tag name or alias: {name}",
            )
        conflict = alias_keys.intersection(existing_keys)
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tag alias conflicts with an existing tag name or alias: {sorted(conflict)[0]}",
            )


def _validate_parent(
    session: Session,
    dataset_id: int,
    parent_id: int | None,
    current_id: int | None = None,
) -> None:
    if parent_id is None:
        return
    if current_id is not None and parent_id == current_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tag cannot be its own parent.")
    parent = session.get(Tag, parent_id)
    if not parent or parent.dataset_id != dataset_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent tag must belong to the same dataset.")
