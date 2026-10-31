"""Standalone CPU worker. Only this optional process imports the ML stack."""
import argparse
import hashlib
import json
import math
import os
import time
from importlib.metadata import version
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def progress(root, stage, current=0, total=1):
    write_json(root / "progress.json", dict(stage=stage, current=current, total=total))


def run(root):
    import numpy as np
    import torch
    from PIL import Image, ImageOps
    from torchvision.transforms.functional import pil_to_tensor
    from anomalib.models.image.padim.torch_model import PadimModel
    from anomalib.models.image.patchcore.torch_model import PatchcoreModel

    if version("anomalib") != "2.7.0":
        raise RuntimeError("算法环境需要 anomalib==2.7.0。")
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.manual_seed(42)
    np.random.seed(42)
    request = json.loads((root / "input.json").read_text(encoding="utf-8"))
    rows, recipe = request["rows"], request["recipe"]
    size = recipe["image_size"]
    for row in rows:
        path = (root / row["image_path"]).resolve()
        if not path.is_relative_to(root) or sha(path) != row["sha256"]:
            raise ValueError("算法输入的文件路径或 hash 不一致。")
    progress(root, "preparing_model")
    if recipe["model"] == "padim":
        model = PadimModel(backbone="resnet18", pre_trained=False, n_features=100)
    elif recipe["model"] == "patchcore":
        model = PatchcoreModel(layers=["layer2", "layer3"], backbone="resnet18", pre_trained=False, num_neighbors=3)
    else:
        raise ValueError("不支持的基线算法。")
    started = time.monotonic()
    parent = request.get("parent_model")
    if parent:
        weights = Path(parent["path"])
        if sha(weights) != parent["sha256"]:
            raise ValueError("原模型文件已变化。")
        state = torch.load(weights, map_location="cpu", weights_only=True)
        for name, buffer in list(model.named_buffers()):
            if name in state and buffer.shape != state[name].shape:
                owner, _, field = name.rpartition(".")
                setattr(model.get_submodule(owner) if owner else model, field, torch.empty_like(state[name]))
        model.load_state_dict(state, strict=True)
    else:
        cache = Path(request["weight_cache"])
        cache.mkdir(parents=True, exist_ok=True)
        progress(root, "preparing_weights")
        weights = torch.hub.load_state_dict_from_url(
            "https://download.pytorch.org/models/resnet18-f37072fd.pth",
            model_dir=str(cache), map_location="cpu", progress=False, check_hash=True,
        )
        if not sha(cache / "resnet18-f37072fd.pth").startswith("f37072fd"):
            raise ValueError("预训练权重校验失败，请重新准备权重缓存。")
        loaded = model.feature_extractor.feature_extractor.load_state_dict(weights, strict=False)
        if loaded.missing_keys:
            raise ValueError(f"预训练主干参数不完整：{loaded.missing_keys}")

    mean = torch.tensor([0.485, 0.456, 0.406]).reshape(3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).reshape(3, 1, 1)
    roi = recipe.get("roi")

    def read(row):
        with Image.open(root / row["image_path"]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        box = (0, 0, width, height)
        if roi:
            box = (round(roi["x"] * width), round(roi["y"] * height),
                   round((roi["x"] + roi["width"]) * width), round((roi["y"] + roi["height"]) * height))
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                raise ValueError("ROI 在部分图片中小于 4 像素，请扩大区域。")
        tensor = pil_to_tensor(image.crop(box).resize((size, size), Image.Resampling.BILINEAR)).float() / 255
        return (tensor - mean) / std, image, box

    if not parent:
        training = [r for r in rows if r["split"] == "train"]
        if not training or any(r["label_index"] != 0 for r in training):
            raise ValueError("拟合数据必须为纯正常图片。")
        model.train()
        model.feature_extractor.eval()
        with torch.no_grad():
            for index in range(0, len(training), 4):
                progress(root, "fitting_features", index, len(training))
                model(torch.stack([read(r)[0] for r in training[index:index + 4]]))
            progress(root, "fitting_distribution", len(training), len(training))
            if recipe["model"] == "padim":
                model.fit()
            else:
                model.subsample_embedding(sampling_ratio=0.01)
        torch.save(model.state_dict(), root / "model.pt")
    fit_seconds = 0.0 if parent else time.monotonic() - started
    model.eval()
    predictions = []
    map_samples = []
    for directory in ("maps", "previews", "heatmaps"):
        (root / directory).mkdir(exist_ok=True)
    with torch.no_grad():
        for index, row in enumerate(rows, 1):
            tensor, image, box = read(row)
            output = model(tensor.unsqueeze(0))
            score = float(output.pred_score.reshape(-1)[0])
            values = output.anomaly_map.squeeze().cpu().numpy().astype(np.float32)
            if not math.isfinite(score) or not np.isfinite(values).all():
                raise ValueError("算法产生非有限分数，请检查正常样本多样性或改用另一个基线。")
            np.save(root / "maps" / f"{row['sample_id']}.npy", values, allow_pickle=False)
            if row["split"] == "val":
                map_samples.append(float(np.quantile(values, 0.995)))
            image.thumbnail((960, 960))
            image.save(root / "previews" / f"{row['sample_id']}.jpg", quality=90)
            predictions.append(dict(sample_id=row["sample_id"], score=score))
            progress(root, "predicting", index, len(rows))
    scale = parent["map_scale"] if parent else max(max(map_samples, default=1.0), 1e-8)
    for row in rows:
        values = np.clip(np.load(root / "maps" / f"{row['sample_id']}.npy", allow_pickle=False) / scale, 0, 1)
        rgb = np.stack([np.clip(1.5 - np.abs(4 * values - offset), 0, 1) for offset in (3, 2, 1)], axis=-1)
        heatmap = Image.fromarray((rgb * 255).astype(np.uint8)).convert("RGBA")
        with Image.open(root / "previews" / f"{row['sample_id']}.jpg") as image:
            width, height = image.size
        if roi:
            box = (round(roi["x"] * width), round(roi["y"] * height),
                   round((roi["x"] + roi["width"]) * width), round((roi["y"] + roi["height"]) * height))
            canvas = Image.new("RGBA", (width, height))
            canvas.paste(heatmap.resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.BILINEAR), box[:2])
            heatmap = canvas
        else:
            heatmap = heatmap.resize((width, height), Image.Resampling.BILINEAR)
        heatmap.save(root / "heatmaps" / f"{row['sample_id']}.png")
    write_json(root / "result.json", dict(schema_version=1, anomalib=version("anomalib"),
        recipe=recipe, predictions=predictions, fit_seconds=fit_seconds,
        total_seconds=time.monotonic() - started, map_scale=scale,
        model_sha256=parent["sha256"] if parent else sha(root / "model.pt")))
    progress(root, "completed", len(rows), len(rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve())
