import subprocess

from scripts.write_image_provenance import source_tree_sha256


def command(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_uninitialized_gitlink_never_uses_parent_repository_revision(tmp_path):
    command(tmp_path, "init")
    command(tmp_path, "update-index", "--add", "--cacheinfo", "160000," + "b" * 40 + ",vendor/upstream")
    command(tmp_path, "-c", "user.name=SyntheticFixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-m", "synthetic gitlink fixture")
    absent = source_tree_sha256(tmp_path)
    (tmp_path / "vendor/upstream").mkdir(parents=True)
    assert source_tree_sha256(tmp_path) == absent
    command(tmp_path, "update-index", "--cacheinfo", "160000," + "c" * 40 + ",vendor/upstream")
    assert source_tree_sha256(tmp_path) != absent
