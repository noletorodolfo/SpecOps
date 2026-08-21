import os

import pytest

from core import project


def test_find_project_root_discovers_by_walking_up(tmp_path):
    (tmp_path / ".specops").mkdir()
    nested = tmp_path / "backend" / "modules" / "auth"
    nested.mkdir(parents=True)

    root = project.find_project_root(start=str(nested))

    assert root == str(tmp_path)


def test_find_project_root_raises_when_nothing_found(tmp_path):
    with pytest.raises(SystemExit):
        project.find_project_root(start=str(tmp_path))


def test_find_project_root_explicit_path_wins(tmp_path):
    initialized = tmp_path / "real-project"
    (initialized / ".specops").mkdir(parents=True)
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()

    root = project.find_project_root(explicit=str(initialized), start=str(elsewhere))

    assert root == str(initialized)


def test_find_project_root_explicit_path_without_specops_raises(tmp_path):
    uninitialized = tmp_path / "not-a-project"
    uninitialized.mkdir()

    with pytest.raises(SystemExit):
        project.find_project_root(explicit=str(uninitialized))


def test_init_project_creates_the_full_skeleton(tmp_path):
    specops_dir, already_existed = project.init_project(str(tmp_path))

    assert already_existed is False
    assert specops_dir == str(tmp_path / ".specops")
    for sub in project.DATA_SUBDIRS:
        assert os.path.isdir(os.path.join(specops_dir, sub))
    assert os.path.exists(os.path.join(specops_dir, "governance.yml"))


def test_init_project_is_idempotent_and_never_overwrites_governance(tmp_path):
    specops_dir, _ = project.init_project(str(tmp_path))
    governance_path = os.path.join(specops_dir, "governance.yml")
    with open(governance_path, "w") as f:
        f.write("# customized by hand\n")

    _, already_existed = project.init_project(str(tmp_path))

    assert already_existed is True
    with open(governance_path) as f:
        assert f.read() == "# customized by hand\n"


def test_init_project_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    specops_dir, _ = project.init_project(os.getcwd())
    assert specops_dir == str(tmp_path / ".specops")
