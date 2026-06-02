"""Tests for the Research-assistant MCP server tools.

Most tests avoid invoking the real wmake or grepping the real
$FOAM_SRC — they exercise the parsers and fork-detection with
synthetic inputs and a tiny fixture source tree.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from research_assistant_mcp.tools import (
    _parse_wmake_output,
    discover_user_lib_path,
    find_examples_of_base_class,
    wmake_and_report,
)

# ---------------------------------------------------------------------------
# wmake output parser
# ---------------------------------------------------------------------------


class TestParseWmakeOutput:
    def test_success_lib(self) -> None:
        log = (
            "Making dependencies: foo.C\n"
            "g++ ... -fPIC -shared ... -o "
            "/home/u/OpenFOAM/u-v2412/platforms/linux64GccDPInt32Opt/lib/libfoo.so\n"
        )
        parsed = _parse_wmake_output(log)
        assert parsed["errors"] == []
        assert parsed["libraries_built"] == [
            "/home/u/OpenFOAM/u-v2412/platforms/linux64GccDPInt32Opt/lib/libfoo.so"
        ]

    def test_missing_header(self) -> None:
        log = (
            "foo.C:42:10: fatal error: missingHeader.H: No such file or directory\n"
            "compilation terminated.\n"
        )
        parsed = _parse_wmake_output(log)
        assert len(parsed["errors"]) == 1
        e = parsed["errors"][0]
        assert e["type"] == "missing_header"
        assert e["missing"] == "missingHeader.H"
        assert e["file"] == "foo.C"
        assert e["line"] == "42"
        assert "EXE_INC" in e["hint"]

    def test_undefined_symbol(self) -> None:
        log = (
            "Make/linux64GccDPInt32Opt/foo.o: In function `Foam::foo()':\n"
            "foo.C:(.text+0x1a): undefined reference to "
            "`Foam::someThing::existed()'\n"
            "collect2: error: ld returned 1 exit status\n"
        )
        parsed = _parse_wmake_output(log)
        e = next(x for x in parsed["errors"] if x["type"] == "undefined_symbol")
        assert "someThing" in e["symbol"]
        assert "ESI/Foundation" in e["hint"]

    def test_missing_library(self) -> None:
        log = "/usr/bin/ld: cannot find -lnonexistentLib\n"
        parsed = _parse_wmake_output(log)
        e = next(x for x in parsed["errors"] if x["type"] == "missing_library")
        assert e["library"] == "nonexistentLib"

    def test_deduplicates_repeated_errors(self) -> None:
        log = "\n".join(
            [
                "foo.C:42:10: fatal error: H.H: No such file or directory",
                "foo.C:42:10: fatal error: H.H: No such file or directory",
                "foo.C:42:10: fatal error: H.H: No such file or directory",
            ]
        )
        parsed = _parse_wmake_output(log)
        assert len(parsed["errors"]) == 1

    def test_generic_compile_error(self) -> None:
        log = "foo.C:13:5: error: 'someUndeclared' was not declared in this scope\n"
        parsed = _parse_wmake_output(log)
        e = next(x for x in parsed["errors"] if x["type"] == "compile_error")
        assert "someUndeclared" in e["message"]

    def test_no_errors_on_empty(self) -> None:
        parsed = _parse_wmake_output("")
        assert parsed["errors"] == []
        assert parsed["libraries_built"] == []
        assert parsed["binaries_built"] == []


# ---------------------------------------------------------------------------
# wmake_and_report (infrastructure paths only — no real wmake invocation)
# ---------------------------------------------------------------------------


class TestWmakeAndReport:
    def test_invalid_directory(self, tmp_path: Path) -> None:
        result = wmake_and_report(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_directory"

    def test_make_dir_missing(self, tmp_path: Path) -> None:
        result = wmake_and_report(str(tmp_path))
        assert result["success"] is False
        assert result["reason"] == "make_dir_missing"

    def test_wmake_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = tmp_path / "lib"
        (d / "Make").mkdir(parents=True)
        (d / "Make" / "files").write_text("foo.C\n\nLIB = $(FOAM_USER_LIBBIN)/libfoo\n")
        (d / "Make" / "options").write_text("EXE_INC =\n\nLIB_LIBS =\n")
        # Hide wmake.
        monkeypatch.setenv("PATH", "/nonexistent")
        result = wmake_and_report(str(d))
        assert result["success"] is False
        assert result["reason"] == "wmake_not_on_path"


# ---------------------------------------------------------------------------
# find_examples_of_base_class
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_foam_src(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / "fake-foam-src"
    src.mkdir()

    # A real-looking BC header.
    (src / "fooFvPatchVectorField.H").write_text(
        "class fooFvPatchVectorField\n"
        ":\n"
        "    public fixedValueFvPatchVectorField\n"
        "{\n"
        "    // ...\n"
        "};\n"
    )
    # Multiple classes in one file — only the first should be matched.
    (src / "many.H").write_text(
        "class barFvPatchVectorField\n"
        "    :\n"
        "    public fixedValueFvPatchVectorField\n"
        "{};\n"
        "\n"
        "class bazFvPatchVectorField\n"
        "    :\n"
        "    public fixedValueFvPatchVectorField\n"
        "{};\n"
    )
    # A class deriving from a different base — must not match.
    (src / "unrelated.H").write_text(
        "class somethingElse\n"
        "    :\n"
        "    public mixedFvPatchVectorField\n"
        "{};\n"
    )
    # An lnInclude symlink directory — must be skipped.
    (src / "module" / "lnInclude").mkdir(parents=True)
    (src / "module" / "lnInclude" / "fooFvPatchVectorField.H").write_text(
        "class duplicateFooDontMatch : public fixedValueFvPatchVectorField {};\n"
    )

    monkeypatch.setenv("FOAM_SRC", str(src))
    monkeypatch.delenv("FOAM_APP", raising=False)
    return src


class TestFindExamples:
    def test_finds_matches(self, fake_foam_src: Path) -> None:
        result = find_examples_of_base_class("fixedValueFvPatchVectorField")
        assert result["success"] is True
        derived = {e["derived_class"] for e in result["examples"]}
        # foo from fooFvPatchVectorField.H, bar from many.H (only first
        # match per file).
        assert "fooFvPatchVectorField" in derived
        assert "barFvPatchVectorField" in derived
        # baz is the second declaration in many.H — must NOT be matched.
        assert "bazFvPatchVectorField" not in derived
        # The lnInclude duplicate must be skipped.
        assert "duplicateFooDontMatch" not in derived
        # somethingElse derives from a different base.
        assert "somethingElse" not in derived

    def test_no_matches(self, fake_foam_src: Path) -> None:
        result = find_examples_of_base_class("doesNotExist")
        assert result["success"] is True
        assert result["examples"] == []

    def test_empty_base_class_rejected(self, fake_foam_src: Path) -> None:
        result = find_examples_of_base_class("  ")
        assert result["success"] is False
        assert result["reason"] == "empty_base_class"

    def test_foam_src_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FOAM_SRC", raising=False)
        monkeypatch.delenv("FOAM_APP", raising=False)
        result = find_examples_of_base_class("fixedValueFvPatchVectorField")
        assert result["success"] is False
        assert result["reason"] == "foam_src_not_set"

    def test_max_results_respected(self, fake_foam_src: Path) -> None:
        result = find_examples_of_base_class(
            "fixedValueFvPatchVectorField", max_results=1
        )
        assert len(result["examples"]) == 1


# ---------------------------------------------------------------------------
# discover_user_lib_path
# ---------------------------------------------------------------------------


class TestDiscoverUserLibPath:
    def test_esi_fork(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WM_PROJECT_VERSION", "v2412")
        monkeypatch.setenv("WM_PROJECT_USER_DIR", "/home/u/OpenFOAM/u-v2412")
        monkeypatch.setenv(
            "FOAM_USER_LIBBIN",
            "/home/u/OpenFOAM/u-v2412/platforms/linux64GccDPInt32Opt/lib",
        )
        monkeypatch.setenv(
            "FOAM_USER_APPBIN",
            "/home/u/OpenFOAM/u-v2412/platforms/linux64GccDPInt32Opt/bin",
        )
        result = discover_user_lib_path()
        assert result["success"] is True
        assert result["fork"] == "esi"
        assert result["wm_project_version"] == "v2412"
        assert "u-v2412" in result["wm_project_user_dir"]

    def test_foundation_fork(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WM_PROJECT_VERSION", "12")
        monkeypatch.setenv("WM_PROJECT_USER_DIR", "/home/u/OpenFOAM/u-12")
        result = discover_user_lib_path()
        assert result["success"] is True
        assert result["fork"] == "foundation"

    def test_foundation_dotted_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WM_PROJECT_VERSION", "12.0")
        result = discover_user_lib_path()
        assert result["success"] is True
        assert result["fork"] == "foundation"

    def test_unknown_fork(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WM_PROJECT_VERSION", "weirdo-fork")
        result = discover_user_lib_path()
        assert result["success"] is True
        assert result["fork"] == "unknown"

    def test_not_sourced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WM_PROJECT_VERSION", raising=False)
        result = discover_user_lib_path()
        assert result["success"] is False
        assert result["reason"] == "openfoam_not_sourced"


# ---------------------------------------------------------------------------
# Optional: real wmake invocation against the shipped custom-bc-example.
# Skipped if OpenFOAM is not sourced — keeps the test suite fast/portable.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("WM_PROJECT_VERSION"),
    reason="OpenFOAM not sourced — skipping real wmake test",
)
class TestWmakeAgainstShippedExample:
    def test_compiles_parabolic_inlet(self) -> None:
        """End-to-end: wmake the shipped custom-bc-example lib.

        We don't assert on ``libraries_built`` because wmake skips
        emitting the ``-o ...libfoo.so`` line when nothing needed
        rebuilding (and CI may re-run this after a prior pass).
        Success + the .so on disk in $FOAM_USER_LIBBIN is enough.
        """
        repo_root = Path(__file__).resolve().parents[3]
        lib_dir = repo_root / "cases" / "examples" / "custom-bc-example" / "lib"
        assert lib_dir.is_dir(), f"Expected lib at {lib_dir}"

        result = wmake_and_report(str(lib_dir), target="libso")
        assert result["success"] is True, (
            f"wmake failed: errors={result.get('errors')}, "
            f"log_tail={result.get('log_tail')}"
        )

        user_libbin = os.environ.get("FOAM_USER_LIBBIN")
        assert user_libbin, "FOAM_USER_LIBBIN must be set when OpenFOAM is sourced"
        so_path = Path(user_libbin) / "libparabolicInletVelocity.so"
        assert so_path.is_file(), (
            f"Expected {so_path} on disk after wmake. "
            f"libraries_built={result.get('libraries_built')}"
        )
