# Copyright (c) 2023-2024 Antmicro <www.antmicro.com>
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
from pathlib import Path, PurePath

import nox

PYTHON_VERSIONS = ["3.8", "3.9", "3.10", "3.11", "3.12"]


@nox.session(reuse_venv=True)
def pre_commit(session: nox.Session) -> None:
    session.run("pre-commit", "install")
    session.run("pre-commit", "run", "--all-files")


@nox.session(reuse_venv=True)
def lint(session: nox.Session) -> None:
    """Options are defined in pyproject.toml and .flake8 files"""
    session.install(".[lint]")
    session.run("isort", ".")
    session.run("black", ".")
    session.run("flake8", ".")
    session.run("codespell", "-w")


@nox.session()
def test_lint(session: nox.Session) -> None:
    session.install(".[lint]")
    session.run("isort", "--check", ".")
    session.run("black", "--check", ".")
    session.run("flake8", ".")
    session.run("codespell")


# Coverage report generation will work only with packages installed
# in development mode. For more details, check
# https://github.com/pytest-dev/pytest-cov/issues/388


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    session.install("-e", ".[tests,topwrap-parse]")
    session.run("pytest", "-rs", "--cov-report", "html:cov_html", "--cov=topwrap", "tests")


def prepare_pyenv(session: nox.Session) -> dict:
    env = os.environ.copy()
    path = env.get("PATH")

    project_dir = Path(__file__).absolute().parent
    env["PYENV_ROOT"] = env.get("PYENV_ROOT", f"{project_dir}/.nox/pyenv")

    pyenv_bin = PurePath(env["PYENV_ROOT"]) / "bin"
    pyenv_shims = PurePath(env["PYENV_ROOT"]) / "shims"
    path = f"{pyenv_bin}:{pyenv_shims}:{path}"
    env["PATH"] = path

    # Install Pyenv
    if not shutil.which("pyenv", path=path):
        session.error(
            "\n'pyenv' command not found, you can install it by executing:"
            "\n    curl https://pyenv.run | bash"
            "\nSee https://github.com/pyenv/pyenv?tab=readme-ov-file#installation for more information"
        )

    # Install required Python versions if these don't exist
    for ver in PYTHON_VERSIONS:
        if not shutil.which(f"python{ver}", path=path):
            session.log(f"Installing Python {ver}")
            session.run("pyenv", "install", ver, external=True, env=env)

    # Detect which versions are provided by Pyenv
    pythons_in_pyenv = []
    for ver in PYTHON_VERSIONS:
        if shutil.which(f"python{ver}", path=pyenv_shims):
            pythons_in_pyenv += [ver]

    # Allow using Pythons from Pyenv
    if pythons_in_pyenv:
        session.log(f"Configuring Pythons from Pyenv, versions: {pythons_in_pyenv}")
        session.run("pyenv", "global", *pythons_in_pyenv, external=True, env=env)

    return env


@nox.session
def tests_in_env(session: nox.Session) -> None:
    env = prepare_pyenv(session)
    session.run("nox", "-s", "tests", external=True, env=env)


@nox.session
def build(session: nox.Session) -> None:
    session.install("-e", ".[deploy]")
    session.run("python3", "-m", "build")


@nox.session
def build_and_install_and_test(session: nox.Session) -> None:
    build(session)
    session.notify("__install_and_test")


@nox.session(default=False)
def __install_and_test(session: nox.Session) -> None:
    session.install("./dist/topwrap-0.0.1.tar.gz")
    tmpdir = session.create_tmp()
    session.run("cp", "-r", "tests", "examples", tmpdir)
    session.run("mkdir", os.path.join(tmpdir, "topwrap"))
    session.run("cp", "-r", "topwrap/ips", os.path.join(tmpdir, "topwrap/"))
    session.chdir(tmpdir)
    session.run("pytest", "-rs", "--cov-report", "html:cov_html", "--cov=topwrap", "tests")
