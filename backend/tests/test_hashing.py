from app.utils.hashing import sha256_file


def test_sha256_file(tmp_path):
    target = tmp_path / "sample.txt"
    target.write_text("dataset-manager", encoding="utf-8")

    assert sha256_file(target) == "ab01a1e0c70cb244dd64ea2e3636524d1b2d4684ed23d699c9f3ed72003a454a"
