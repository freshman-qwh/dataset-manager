from collections import defaultdict
from random import Random

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.models.dataset import utc_now
from app.models.sample import Sample
from app.schemas.split import SplitPlanRequest, SplitPlanResult
from app.services.dataset_service import get_dataset_or_404


def apply_split_plan(session: Session, dataset_id: int, payload: SplitPlanRequest) -> SplitPlanResult:
    get_dataset_or_404(session, dataset_id)
    ratios = _normalized_ratios(payload)
    if ratios["train"] <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="train_ratio must be greater than zero.")

    samples = _select_samples(session, dataset_id, payload)
    rng = Random(payload.seed)
    if payload.stratify_by_tags:
        assignments = _stratified_assignments(samples, ratios, payload.include_test, rng)
        warnings = _coverage_warnings(samples, assignments, ratios, payload.include_test)
    else:
        assignments = _random_assignments(samples, ratios, payload.include_test, rng)
        warnings = []

    for sample in samples:
        if sample.id in assignments:
            sample.split = assignments[sample.id]
            sample.updated_at = utc_now()
            session.add(sample)

    session.commit()
    values = list(assignments.values())
    return SplitPlanResult(
        dataset_id=dataset_id,
        requested=len(samples),
        updated=len(assignments),
        train=values.count("train"),
        val=values.count("val"),
        test=values.count("test"),
        unassigned=len(samples) - len(assignments),
        stratify_by_tags=payload.stratify_by_tags,
        include_test=payload.include_test,
        seed=payload.seed,
        warnings=warnings[:50],
    )


def _select_samples(session: Session, dataset_id: int, payload: SplitPlanRequest) -> list[Sample]:
    statement = select(Sample).where(Sample.dataset_id == dataset_id)
    if payload.normal_only:
        statement = statement.where(Sample.file_status == "normal")
    if payload.only_unassigned:
        statement = statement.where(Sample.split.is_(None))
    return session.exec(statement).all()


def _normalized_ratios(payload: SplitPlanRequest) -> dict[str, float]:
    test_ratio = payload.test_ratio if payload.include_test else 0
    total = payload.train_ratio + payload.val_ratio + test_ratio
    if total <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one split ratio must be greater than zero.")
    return {
        "train": payload.train_ratio / total,
        "val": payload.val_ratio / total,
        "test": test_ratio / total,
    }


def _random_assignments(
    samples: list[Sample],
    ratios: dict[str, float],
    include_test: bool,
    rng: Random,
) -> dict[int, str]:
    shuffled = list(samples)
    rng.shuffle(shuffled)
    counts = _split_counts(len(shuffled), ratios, include_test)
    assignments: dict[int, str] = {}
    cursor = 0
    for split_name in ("train", "val", "test"):
        count = counts[split_name]
        for sample in shuffled[cursor : cursor + count]:
            if sample.id is not None:
                assignments[sample.id] = split_name
        cursor += count
    return assignments


def _stratified_assignments(
    samples: list[Sample],
    ratios: dict[str, float],
    include_test: bool,
    rng: Random,
) -> dict[int, str]:
    tag_counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        for label in _sample_labels(sample):
            tag_counts[label] += 1

    desired_by_label = {
        label: _split_counts(count, ratios, include_test)
        for label, count in tag_counts.items()
    }
    overall_remaining = _split_counts(len(samples), ratios, include_test)
    active_splits = [name for name in ("train", "val", "test") if overall_remaining[name] > 0]

    assignments = _coverage_floor_assignments(
        samples,
        tag_counts,
        desired_by_label,
        overall_remaining,
        include_test,
        rng,
    )

    ordered = list(samples)
    rng.shuffle(ordered)
    ordered.sort(
        key=lambda sample: (
            min(tag_counts.get(label, len(samples)) for label in _sample_labels(sample)),
            len(_sample_labels(sample)),
        )
    )

    for sample in ordered:
        if sample.id is None:
            continue
        if sample.id in assignments:
            continue
        labels = _sample_labels(sample)
        candidates = [split for split in active_splits if overall_remaining[split] > 0]
        if not candidates:
            break
        split_name = max(
            candidates,
            key=lambda split: (
                sum(max(desired_by_label[label][split], 0) for label in labels),
                overall_remaining[split],
                rng.random(),
            ),
        )
        assignments[sample.id] = split_name
        overall_remaining[split_name] -= 1
        for label in labels:
            desired_by_label[label][split_name] -= 1

    for sample in samples:
        if sample.id is not None and sample.id not in assignments:
            assignments[sample.id] = "train"

    return assignments


def _coverage_floor_assignments(
    samples: list[Sample],
    tag_counts: dict[str, int],
    desired_by_label: dict[str, dict[str, int]],
    overall_remaining: dict[str, int],
    include_test: bool,
    rng: Random,
) -> dict[int, str]:
    assignments: dict[int, str] = {}
    targets = [("val", 2)]
    if include_test:
        targets.append(("test", 3))

    for split_name, minimum_count in targets:
        while overall_remaining[split_name] > 0:
            covered = _covered_labels(samples, assignments, split_name)
            missing = {
                label
                for label, count in tag_counts.items()
                if label != "__untagged__" and count >= minimum_count and label not in covered
            }
            if not missing:
                break

            candidates = [
                sample
                for sample in samples
                if sample.id is not None
                and sample.id not in assignments
                and any(label in missing for label in _sample_labels(sample))
            ]
            if not candidates:
                break

            sample = max(
                candidates,
                key=lambda item: (
                    sum(1 for label in _sample_labels(item) if label in missing),
                    sum(1 / tag_counts[label] for label in _sample_labels(item) if label in missing),
                    len(_sample_labels(item)),
                    rng.random(),
                ),
            )
            assignments[sample.id] = split_name
            overall_remaining[split_name] -= 1
            for label in _sample_labels(sample):
                desired_by_label[label][split_name] -= 1

    return assignments


def _covered_labels(samples: list[Sample], assignments: dict[int, str], split_name: str) -> set[str]:
    covered: set[str] = set()
    for sample in samples:
        if sample.id is None or assignments.get(sample.id) != split_name:
            continue
        covered.update(label for label in _sample_labels(sample) if label != "__untagged__")
    return covered


def _split_counts(count: int, ratios: dict[str, float], include_test: bool) -> dict[str, int]:
    if count <= 0:
        return {"train": 0, "val": 0, "test": 0}

    active = ["train"]
    if ratios["val"] > 0:
        active.append("val")
    if include_test and ratios["test"] > 0:
        active.append("test")

    raw = {name: count * ratios[name] for name in ("train", "val", "test")}
    counts = {name: int(raw[name]) for name in ("train", "val", "test")}
    remainder = count - sum(counts.values())
    for name in sorted(("train", "val", "test"), key=lambda item: raw[item] - counts[item], reverse=True):
        if remainder <= 0:
            break
        if ratios[name] <= 0:
            continue
        counts[name] += 1
        remainder -= 1

    if count >= len(active):
        for name in active:
            if counts[name] == 0:
                donor = max((item for item in active if item != name), key=lambda item: counts[item])
                if counts[donor] > 1:
                    counts[donor] -= 1
                    counts[name] += 1

    if not include_test:
        counts["test"] = 0

    delta = count - sum(counts.values())
    counts["train"] += delta
    return counts


def _sample_labels(sample: Sample) -> list[str]:
    names = sorted({tag.name for tag in sample.tags if tag.name})
    return names or ["__untagged__"]


def _coverage_warnings(
    samples: list[Sample],
    assignments: dict[int, str],
    ratios: dict[str, float],
    include_test: bool,
) -> list[str]:
    warnings: list[str] = []
    label_counts: dict[str, int] = defaultdict(int)
    label_split_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"train": 0, "val": 0, "test": 0})

    for sample in samples:
        if sample.id is None:
            continue
        split_name = assignments.get(sample.id)
        if not split_name:
            continue
        for label in _sample_labels(sample):
            if label == "__untagged__":
                continue
            label_counts[label] += 1
            label_split_counts[label][split_name] += 1

    validation_capacity = _coverage_capacity("val", 2, samples, assignments, label_counts)
    test_capacity = _coverage_capacity("test", 3, samples, assignments, label_counts)

    for label in sorted(label_counts):
        count = label_counts[label]
        if ratios["val"] > 0:
            if count < 2:
                warnings.append(f"{label}: 只有 {count} 个可处理样本，无法保证验证集覆盖。")
            elif label_split_counts[label]["val"] == 0:
                warnings.append(_missing_coverage_warning(label, count, "验证集", validation_capacity))
        if include_test and ratios["test"] > 0:
            if count < 3:
                warnings.append(f"{label}: 只有 {count} 个可处理样本，无法保证测试集覆盖。")
            elif label_split_counts[label]["test"] == 0:
                warnings.append(_missing_coverage_warning(label, count, "测试集", test_capacity))
    return warnings


def _coverage_capacity(
    split_name: str,
    minimum_count: int,
    samples: list[Sample],
    assignments: dict[int, str],
    label_counts: dict[str, int],
) -> tuple[int, int | None]:
    split_size = sum(1 for value in assignments.values() if value == split_name)
    coverable_labels = {
        label
        for label, count in label_counts.items()
        if label != "__untagged__" and count >= minimum_count
    }
    return split_size, _minimum_samples_to_cover_labels(samples, coverable_labels)


def _missing_coverage_warning(label: str, count: int, split_label: str, capacity: tuple[int, int | None]) -> str:
    split_size, minimum_needed = capacity
    if minimum_needed is not None and split_size < minimum_needed:
        return (
            f"{label}: 有 {count} 个可处理样本，但{split_label}只有 {split_size} 个名额；"
            f"至少需要 {minimum_needed} 个名额才能覆盖所有可覆盖标签。"
        )
    return f"{label}: 有 {count} 个可处理样本，但没有进入{split_label}。"


def _minimum_samples_to_cover_labels(samples: list[Sample], labels: set[str]) -> int | None:
    if not labels:
        return 0
    if len(labels) > 14:
        return None

    ordered_labels = sorted(labels)
    label_indexes = {label: index for index, label in enumerate(ordered_labels)}
    full_mask = (1 << len(ordered_labels)) - 1
    masks: set[int] = set()
    for sample in samples:
        mask = 0
        for label in _sample_labels(sample):
            if label in label_indexes:
                mask |= 1 << label_indexes[label]
        if mask:
            masks.add(mask)

    if not masks:
        return None

    distances = {0: 0}
    for mask in sorted(masks, key=int.bit_count, reverse=True):
        next_distances = dict(distances)
        for covered, distance in distances.items():
            merged = covered | mask
            next_distances[merged] = min(next_distances.get(merged, len(labels) + 1), distance + 1)
        distances = next_distances

    return distances.get(full_mask)
