"""What a framework requires of the machine, which its own manifest never says.

Generic manifest parsing already compares a declared range against an installed
version. This asks the question one layer down, and the reason it is worth
asking is that the manifest is *internally consistent* when it goes wrong:
`package.json` says `"node": ">=18"` and `"next": "^15"`, every range is
satisfied, and the build fails on Node 18.0 with a syntax error.

Three frameworks, deeply. Each was chosen for the same property -- a machine
requirement that appears in no manifest, failing with a message that names
something other than the cause:

- Next.js: a syntax error rather than a Node version.
- Spring Boot: a bytecode class-version number rather than a JDK.
- Django: nothing at all, because pip quietly resolves an older Django and the
  project silently runs a version it did not declare.

And the pair that motivated the native-dependency check: `psycopg2` compiles and
`psycopg2-binary` does not. One character, opposite sides of "do you need a C
compiler", and a requirements file gives no hint which one you are reading.
"""

from __future__ import annotations

import json
from pathlib import Path

from devrepro.core.models import FindingState, PlatformInfo, ToolInstallation
from devrepro.project.frameworks import (
    DJANGO_PYTHON_FLOOR,
    NEXT_NODE_FLOOR,
    SPRING_BOOT_JDK_FLOOR,
    detect_django,
    detect_frameworks,
    detect_next,
    detect_spring_boot,
    native_dependencies,
)
from devrepro.rules.base import RuleContext
from devrepro.rules.packs.frameworks import evaluate

NL = chr(10)


def write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def package(root: Path, **deps: str) -> None:
    write(root, "package.json", json.dumps({"dependencies": deps}))


def context(**tools: str) -> RuleContext:
    return RuleContext(
        platform_info=PlatformInfo(os_name="Linux", os_version="1", arch="x86_64"),
        tools=tuple(
            ToolInstallation(name=name, version=version, is_active=True)
            for name, version in tools.items()
        ),
    )


# ================================================================== Next.js


def test_next_15_requires_node_18_18(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.3")
    found = detect_next(tmp_path)
    assert [(r.tool, r.required) for r in found] == [("node", ">=18.18.0")]


def test_each_next_major_carries_its_own_floor(tmp_path: Path) -> None:
    for major, floor in NEXT_NODE_FLOOR.items():
        package(tmp_path, next=f"^{major}.0.0")
        assert detect_next(tmp_path)[0].required == f">={floor}"


def test_an_unrecognised_next_major_claims_nothing(tmp_path: Path) -> None:
    """A guessed floor produces a confident wrong finding, which is worse than silence."""
    package(tmp_path, next="^99.0.0")
    assert detect_next(tmp_path) == []


def test_a_project_without_next_is_not_a_next_project(tmp_path: Path) -> None:
    package(tmp_path, react="^19.0.0")
    assert detect_next(tmp_path) == []


def test_next_is_found_in_dev_dependencies_too(tmp_path: Path) -> None:
    write(tmp_path, "package.json", json.dumps({"devDependencies": {"next": "^14.2.0"}}))
    assert detect_next(tmp_path)[0].required == ">=18.17.0"


def test_the_detail_explains_why_the_manifest_looked_fine(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.0")
    detail = detect_next(tmp_path)[0].detail
    assert "internally consistent" in detail
    assert "syntax error" in detail


# =================================================================== Django


def test_django_5_requires_python_3_10(tmp_path: Path) -> None:
    write(tmp_path, "manage.py", "#!/usr/bin/env python")
    write(tmp_path, "requirements.txt", "Django>=5.0,<6" + NL)
    found = detect_django(tmp_path)
    assert [(r.tool, r.required) for r in found] == [("python", ">=3.10")]


def test_manage_py_alone_is_not_enough(tmp_path: Path) -> None:
    """It says a Django project is here, not which Django."""
    write(tmp_path, "manage.py", "#!/usr/bin/env python")
    assert detect_django(tmp_path) == []


def test_a_declaration_in_pyproject_is_read(tmp_path: Path) -> None:
    write(tmp_path, "manage.py", "x")
    write(tmp_path, "pyproject.toml", "[project]" + NL + 'dependencies = ["Django==4.2.11"]' + NL)
    assert detect_django(tmp_path)[0].required == ">=" + DJANGO_PYTHON_FLOOR["4.2"]


def test_a_lowercase_django_is_read(tmp_path: Path) -> None:
    write(tmp_path, "manage.py", "x")
    write(tmp_path, "requirements.txt", "django~=5.1.0" + NL)
    assert detect_django(tmp_path)[0].required == ">=3.10"


def test_the_django_detail_names_the_silent_failure(tmp_path: Path) -> None:
    """This one produces no error at all: pip resolves an older Django instead."""
    write(tmp_path, "manage.py", "x")
    write(tmp_path, "requirements.txt", "Django>=5.0" + NL)
    assert "silently runs a different version" in detect_django(tmp_path)[0].detail


# ============================================================== Spring Boot


def test_spring_boot_3_requires_jdk_17(tmp_path: Path) -> None:
    write(
        tmp_path,
        "build.gradle.kts",
        'plugins { id("org.springframework.boot") version "3.2.4" }' + NL,
    )
    found = detect_spring_boot(tmp_path)
    assert [(r.tool, r.required) for r in found] == [("java", ">=17")]


def test_a_maven_project_is_read_from_its_parent(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pom.xml",
        "<project><parent>"
        + "<artifactId>spring-boot-starter-parent</artifactId>"
        + "<version>2.7.18</version>"
        + "</parent></project>",
    )
    assert detect_spring_boot(tmp_path)[0].required == ">=" + SPRING_BOOT_JDK_FLOOR[2]


def test_gradle_wins_when_a_project_has_both(tmp_path: Path) -> None:
    """A migration leaves both behind; two answers here would be two findings
    about the same thing."""
    write(
        tmp_path,
        "build.gradle",
        "plugins { id 'org.springframework.boot' version '3.1.0' }" + NL,
    )
    write(
        tmp_path,
        "pom.xml",
        "<project><artifactId>spring-boot-starter-parent</artifactId><version>2.7.0</version></project>",
    )
    found = detect_spring_boot(tmp_path)
    assert len(found) == 1
    assert found[0].source == "build.gradle"


def test_a_plain_gradle_project_is_not_spring_boot(tmp_path: Path) -> None:
    write(tmp_path, "build.gradle", "plugins { id 'java' }" + NL)
    assert detect_spring_boot(tmp_path) == []


# ======================================================= native dependencies


def test_psycopg2_and_psycopg2_binary_are_not_the_same(tmp_path: Path) -> None:
    """One character, opposite sides of "do you need a C compiler".

    A substring match reports the binary wheel as needing a toolchain, which is
    exactly backwards and sends somebody installing build-essential they did not
    need.
    """
    write(tmp_path, "requirements.txt", "psycopg2-binary==2.9.9" + NL)
    assert native_dependencies(tmp_path) == []

    write(tmp_path, "requirements.txt", "psycopg2==2.9.9" + NL)
    assert [name for name, *_ in native_dependencies(tmp_path)] == ["psycopg2"]


def test_a_bare_requirement_with_no_version_is_matched(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "mysqlclient" + NL)
    assert [name for name, *_ in native_dependencies(tmp_path)] == ["mysqlclient"]


def test_javascript_native_dependencies_are_found(tmp_path: Path) -> None:
    package(tmp_path, sharp="^0.33.0", react="^19.0.0")
    found = native_dependencies(tmp_path)
    assert [name for name, *_ in found] == ["sharp"]
    assert "glibc floor" in found[0][3]


def test_each_dependency_is_reported_once(tmp_path: Path) -> None:
    package(tmp_path, sharp="^0.33.0")
    write(tmp_path, "requirements.txt", "sharp" + NL)
    assert len(native_dependencies(tmp_path)) == 1


def test_a_project_with_nothing_native_reports_nothing(tmp_path: Path) -> None:
    package(tmp_path, react="^19.0.0")
    assert native_dependencies(tmp_path) == []


# ================================================================ the pack


def test_a_machine_below_the_floor_blocks(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.0")
    findings = evaluate(context(node="18.0.0"), tuple(detect_frameworks(tmp_path)))
    assert findings[0].rule_id == "next/runtime-too-old"
    assert findings[0].state is FindingState.BLOCKED
    assert findings[0].detected == "18.0.0"


def test_a_machine_above_the_floor_passes(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.0")
    findings = evaluate(context(node="22.11.0"), tuple(detect_frameworks(tmp_path)))
    assert findings[0].rule_id == "next/runtime-ok"
    assert findings[0].state is FindingState.PASS


def test_an_absent_runtime_blocks_and_says_which(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.0")
    findings = evaluate(context(), tuple(detect_frameworks(tmp_path)))
    assert findings[0].rule_id == "next/runtime-missing"
    assert "does not resolve on PATH" in findings[0].summary


def test_an_unparseable_installed_version_is_not_a_failure(tmp_path: Path) -> None:
    """Reported elsewhere as unreadable; inventing a failure here would tell
    somebody to reinstall a working runtime."""
    package(tmp_path, next="^15.0.0")
    assert evaluate(context(node="unknown"), tuple(detect_frameworks(tmp_path))) == []


def test_a_native_dependency_is_information_not_a_problem(tmp_path: Path) -> None:
    """A machine with a working toolchain installs it without noticing."""
    package(tmp_path, sharp="^0.33.0")
    findings = evaluate(context(), (), tuple(native_dependencies(tmp_path)))
    assert findings[0].rule_id == "sharp/needs-toolchain"
    assert findings[0].state is FindingState.INFO


def test_every_finding_carries_evidence_pointing_at_the_declaration(tmp_path: Path) -> None:
    package(tmp_path, next="^15.0.0", sharp="^0.33.0")
    findings = evaluate(
        context(node="18.0.0"),
        tuple(detect_frameworks(tmp_path)),
        tuple(native_dependencies(tmp_path)),
    )
    assert findings
    for finding in findings:
        assert finding.evidence
        assert finding.evidence[0].path == "package.json"


def test_nothing_is_invoked() -> None:
    """`next info`, `manage.py check` and `gradlew` all start a runtime, and two
    of them execute the project's own configuration."""
    source = (
        Path(__file__).resolve().parent.parent / "devrepro" / "project" / "frameworks.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "runner", "popen"):
        assert forbidden not in source.lower()


def test_a_poetry_declaration_is_read(tmp_path: Path) -> None:
    """A Django project is about as likely to use Poetry as PEP 621.

    Reading only one of them would miss half of them silently, which is the
    worst failure mode for a detector: it reports nothing and looks correct.
    """
    write(tmp_path, "manage.py", "x")
    write(
        tmp_path,
        "pyproject.toml",
        "[tool.poetry.dependencies]" + NL + 'django = "^5.1"' + NL,
    )
    assert detect_django(tmp_path)[0].required == ">=3.10"


def test_a_poetry_table_declaration_is_read(tmp_path: Path) -> None:
    write(tmp_path, "manage.py", "x")
    write(
        tmp_path,
        "pyproject.toml",
        "[tool.poetry.dependencies]" + NL + 'django = { version = "5.0.6" }' + NL,
    )
    assert detect_django(tmp_path)[0].required == ">=3.10"


def test_the_word_django_in_prose_is_not_a_declaration(tmp_path: Path) -> None:
    """The reason `pyproject.toml` is parsed rather than searched.

    Loosening the line-anchored regex enough to reach a name inside a TOML
    array would also match it in a description, a URL or a comment.
    """
    write(tmp_path, "manage.py", "x")
    write(
        tmp_path,
        "pyproject.toml",
        "[project]" + NL + 'description = "A Django 5.0 tutorial"' + NL,
    )
    assert detect_django(tmp_path) == []
