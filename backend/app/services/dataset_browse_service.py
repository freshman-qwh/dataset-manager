"""Read-only folder views over registered samples, without traversing the disk."""
import re

from fastapi import HTTPException
from sqlalchemy import and_, case, func, literal, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.browse import BrowseFolder, BrowseSource, DatasetBrowseResponse
from app.services.dataset_service import get_dataset_or_404
from app.services.sample_service import to_sample_read


def normalize_folder(folder: str) -> str:
    value = folder.replace("\\", "/")
    if (value.startswith("/") or re.match(r"^[A-Za-z]:", value)
            or "\x00" in value or any(part in {".", ".."} for part in value.split("/"))):
        raise HTTPException(422, "请选择数据集内的相对文件夹。")
    return "/".join(part for part in value.split("/") if part)


def _source_key(path: str) -> str:
    return path.lower() if re.match(r"^[A-Za-z]:", path) or path.startswith("//") else path


def _source_columns(root_path: str | None) -> tuple[ColumnElement[str], ColumnElement[str], ColumnElement[str]]:
    """Derive source roots from existing records without resolving foreign paths.

    Prefer the dataset root for records underneath it, including files scanned
    from a nested folder. Other scan roots can be inferred from the stored suffix.
    Inconsistent legacy suffixes fall back to the absolute file's parent.
    """
    absolute = func.replace(Sample.absolute_path, "\\", "/")
    relative = func.replace(Sample.relative_path, "\\", "/")
    is_windows = or_(func.substr(absolute, 2, 1) == ":", func.substr(absolute, 1, 2) == "//")
    compared_absolute = case((is_windows, func.lower(absolute)), else_=absolute)
    compared_relative = case((is_windows, func.lower(relative)), else_=relative)
    # rtrim with all non-separator characters stops exactly at the final '/'.
    parent = func.rtrim(func.rtrim(absolute, func.replace(absolute, "/", "")), "/")
    parent = case((parent == "", "/"), else_=parent)
    suffix_matches = and_(
        relative != "",
        func.substr(relative, 1, 1) != "/",
        ~relative.like("../%"),
        func.instr(relative, "/../") == 0,
        func.substr(compared_absolute, -func.length(relative) - 1) == literal("/") + compared_relative,
    )
    inferred = func.substr(absolute, 1, func.length(absolute) - func.length(relative) - 1)
    inferred = case((inferred == "", "/"), else_=inferred)
    source = case((suffix_matches, inferred), else_=parent)
    root = (root_path or "").replace("\\", "/").rstrip("/")
    if root_path and not root:
        root = "/"
    if root:
        root_prefix = root if root == "/" else root + "/"
        root_windows = bool(re.match(r"^[A-Za-z]:", root) or root.startswith("//"))
        root_comparison = func.lower(absolute) if root_windows else absolute
        expected_prefix = root_prefix.lower() if root_windows else root_prefix
        source = case((func.substr(root_comparison, 1, len(root_prefix)) == expected_prefix, root), else_=source)
    key = case((is_windows, func.lower(source)), else_=source)
    relative_to_source = func.substr(absolute, func.length(source) + case((source == "/", 1), else_=2))
    return source, key, relative_to_source


def browse_dataset(
    session: Session,
    dataset_id: int,
    *,
    folder: str = "",
    source_root: str = "",
    recursive: bool = False,
    search: str = "",
    file_type: str = "",
    page: int = 1,
    page_size: int = 60,
    folder_page: int = 1,
    folder_page_size: int = 100,
    category_id: int | None = None,
    batch_id: int | None = None,
    all_sources: bool = False,
) -> DatasetBrowseResponse:
    dataset = get_dataset_or_404(session, dataset_id)
    folder = normalize_folder(folder)
    prefix = folder + "/" if folder else ""
    source, source_key, normalized_path = _source_columns(dataset.root_path)
    source_groups = (
        select(source_key.label("key"), func.min(source).label("path"),
            func.count(Sample.id).label("sample_count"),
            func.sum(case((Sample.file_type == "image", 1), else_=0)).label("image_count"))
        .where(Sample.dataset_id == dataset_id).group_by(source_key)
        .order_by(func.lower(func.min(source)), func.min(source))
    )
    source_rows = session.exec(source_groups).all()
    # SQLite lower() folds ASCII only. Merge the much smaller root summary in
    # Python as well, so Windows source paths with accented letters stay one
    # source. Samples themselves remain bounded SQL queries.
    source_summaries: dict[str, BrowseSource] = {}
    source_keys: dict[str, list[str]] = {}
    for row in source_rows:
        key = _source_key(row.path)
        if key not in source_summaries:
            source_summaries[key] = BrowseSource(path=row.path, sample_count=0, image_count=0)
            source_keys[key] = []
        source_summaries[key].sample_count += row.sample_count
        source_summaries[key].image_count += row.image_count
        source_keys[key].append(row.key)
    sources = list(source_summaries.values())
    if source_root:
        selected_key = _source_key(source_root.replace("\\", "/").rstrip("/") or "/")
        if selected_key not in source_keys:
            raise HTTPException(404, "该来源没有已登记的文件，请重新选择来源。")
    else:
        preferred = (dataset.root_path or "").replace("\\", "/").rstrip("/") or "/"
        preferred_key = _source_key(preferred)
        selected_key = preferred_key if preferred_key in source_keys else next(iter(source_keys), "")
    source_root = source_summaries[selected_key].path if selected_key in source_summaries else (dataset.root_path or "").replace("\\", "/")
    scope = [Sample.dataset_id == dataset_id, source_key.in_(source_keys.get(selected_key, []))]
    if all_sources:
        source_root = ""
        scope = [Sample.dataset_id == dataset_id]
    from app.models.organization import DatasetCategory, DatasetBatch
    for identity, model, column in (
        (category_id, DatasetCategory, Sample.category_id),
        (batch_id, DatasetBatch, Sample.batch_id),
    ):
        if identity is not None:
            entity = session.get(model, identity)
            if entity is None or entity.dataset_id != dataset_id:
                raise HTTPException(422, "类别或批次不属于当前数据集，请重新选择。")
            scope.append(column == identity)
    if prefix:
        # Substring equality is literal and case-sensitive: '%'/'_' in real
        # folder names are not wildcards, and 'a' never selects sibling 'ab'.
        scope.append(func.substr(normalized_path, 1, len(prefix)) == prefix)
    tail = func.substr(normalized_path, len(prefix) + 1)
    separator = func.instr(tail, "/")
    child_name = func.substr(tail, 1, separator - 1)
    folder_groups = (
        select(
            child_name.label("name"),
            func.count(Sample.id).label("sample_count"),
            func.sum(case((Sample.file_type == "image", 1), else_=0)).label("image_count"),
            func.min(case(((Sample.file_type == "image") & (Sample.file_status == "normal"), Sample.id))).label("cover_sample_id"),
        )
        .where(*scope, separator > 0, literal(not all_sources))
        .group_by(child_name)
        .subquery()
    )
    folders_total = int(session.exec(select(func.count()).select_from(folder_groups)).one())
    folder_page_size = min(max(folder_page_size, 1), 200)
    folder_page = min(max(folder_page, 1), max((folders_total + folder_page_size - 1) // folder_page_size, 1))
    folder_rows = session.exec(
        select(folder_groups.c.name, folder_groups.c.sample_count, folder_groups.c.image_count, folder_groups.c.cover_sample_id)
        .order_by(func.lower(folder_groups.c.name), folder_groups.c.name)
        .offset((folder_page - 1) * folder_page_size)
        .limit(folder_page_size)
    ).all()

    cover_ids = [row.cover_sample_id for row in folder_rows if row.cover_sample_id is not None]
    cover_hashes = dict(session.exec(select(Sample.id, Sample.file_hash).where(Sample.id.in_(cover_ids))).all()) if cover_ids else {}

    filters = list(scope)
    if not recursive and not all_sources:
        filters.append(separator == 0)
    if file_type:
        filters.append(Sample.file_type == file_type)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped.lower() + "%"
        filters.append(or_(
            func.lower(Sample.filename).like(pattern, escape="\\"),
            func.lower(normalized_path).like(pattern, escape="\\"),
        ))
    total = int(session.exec(select(func.count(Sample.id)).where(*filters)).one())
    page_size = min(max(page_size, 1), 200)
    page = min(max(page, 1), max((total + page_size - 1) // page_size, 1))
    samples = session.exec(
        select(Sample)
        .where(*filters)
        .order_by(func.lower(normalized_path), normalized_path, Sample.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .options(selectinload(Sample.tags))
    ).all()
    return DatasetBrowseResponse(
        dataset_id=dataset_id,
        folder=folder,
        recursive=recursive,
        source_root=source_root,
        sources=sources,
        folders=[BrowseFolder(
            name=row.name,
            path=prefix + row.name,
            sample_count=row.sample_count,
            image_count=row.image_count,
            cover_sample_id=row.cover_sample_id,
            cover_file_hash=cover_hashes.get(row.cover_sample_id),
        ) for row in folder_rows],
        folders_total=folders_total,
        folder_page=folder_page,
        folder_page_size=folder_page_size,
        items=[to_sample_read(sample, dataset.triage_policy_version) for sample in samples],
        total=total,
        page=page,
        page_size=page_size,
    )
