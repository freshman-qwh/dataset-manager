from sqlmodel import Session, select

from app.models.sample import Sample
from app.schemas.industrial import IndustrialReadiness
from app.services.anomaly_protocol_service import _components
from app.services.dataset_service import get_dataset_or_404


def readiness(session: Session, dataset_id: int) -> IndustrialReadiness:
    dataset = get_dataset_or_404(session, dataset_id)
    samples = list(session.exec(select(Sample).where(Sample.dataset_id == dataset_id, Sample.file_type == "image")).all())
    def valid(sample: Sample) -> bool:
        return (sample.file_status == "normal" and sample.triage_status in {"ok", "ng"}
                and sample.triaged_file_hash == sample.file_hash
                and sample.triage_policy_version == dataset.triage_policy_version)
    groups = _components(samples)
    normal = [members for members in groups.values() if all(valid(s) and s.triage_status == "ok" and s.ok_grade == "clear" for s in members)]
    missing = sum(not s.capture_group_id for s in samples)
    review = sum(s.triage_status != "untriaged" and (not valid(s) or s.triage_status == "ok" and s.ok_grade is None) for s in samples)
    if not samples:
        step, label, explanation = "scan", "扫描第一批图片", "选择本机图片目录，原图保留在原位置。"
    elif any(s.triage_status == "untriaged" for s in samples):
        step, label, explanation = "triage", "继续分拣", "先区分完全正常、临界、异常和待定。"
    elif review:
        step, label, explanation = "review", "检查待复核图片", "待定、旧判定和不可用文件需先核对；也可在验证时明确排除。"
    elif missing:
        step, label, explanation = "groups", "补充采集分组", "同一工件的多视角/连拍属于同组，先预览工件与批次映射。"
    else:
        step, label, explanation = "prepare", "准备异常检测数据", "分拣与分组已就绪，可检查独立划分或进入快速验证。"
    return IndustrialReadiness(total_images=len(samples), normal_candidates=sum(len({s.file_hash for s in members}) for members in normal),
        normal_groups=len(normal), missing_groups=missing, needs_review=review,
        next_step=step, next_label=label, explanation=explanation)
