"""Tests for the OpenFOAM dictionary reader.

The narration audit's numbers rest on reading case files correctly, so
these cover the syntax OpenFOAM dicts actually use — multi-token values,
nested blocks, vector and dimension literals — and the cases where the
reader must report rather than guess.
"""

from __future__ import annotations

from pathlib import Path

from foam_dict import flatten, parse_dict_file, parse_dict_text, read_case_settings

CONTROL_DICT = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     simpleFoam;

startFrom       startTime;
endTime         5000;
deltaT          1;
writeInterval   1000;

functions
{
    centerlines
    {
        type            sets;
        libs            (sampling);
        writeControl    onEnd;
    }
}
"""


def test_simple_keys_are_read() -> None:
    settings, problems = parse_dict_text(CONTROL_DICT)
    assert settings["application"] == "simpleFoam"
    assert settings["endTime"] == "5000"
    assert problems == []


def test_nested_blocks_flatten_to_dotted_keys() -> None:
    settings, _ = parse_dict_text(CONTROL_DICT)
    assert settings["functions.centerlines.type"] == "sets"
    assert settings["functions.centerlines.writeControl"] == "onEnd"


def test_comments_are_stripped() -> None:
    settings, _ = parse_dict_text(CONTROL_DICT)
    # Nothing from the banner or the trailing separator line leaks in.
    assert not any("=====" in k for k in settings)
    assert not any("*" in k for k in settings)


def test_multi_token_scheme_values_stay_whole() -> None:
    text = """
    divSchemes
    {
        default         none;
        div(phi,U)      Gauss linearUpwind grad(U);
    }
    """
    settings, _ = parse_dict_text(text)
    # The whole scheme is one value: "Gauss" alone would not distinguish
    # linearUpwind from limitedLinear.
    assert settings["divSchemes.div(phi,U)"] == "Gauss linearUpwind grad(U)"
    assert settings["divSchemes.default"] == "none"


def test_vectors_and_dimensions_survive_as_one_value() -> None:
    text = """
    dimensions      [0 2 -1 0 0 0 0];
    internalField   uniform (0 0 0);
    """
    settings, _ = parse_dict_text(text)
    assert settings["dimensions"] == "[0 2 -1 0 0 0 0]"
    assert settings["internalField"] == "uniform (0 0 0)"


def test_boundary_field_entries_are_addressable() -> None:
    text = """
    boundaryField
    {
        movingWall
        {
            type            fixedValue;
            value           uniform (1 0 0);
        }
        frontAndBack
        {
            type            empty;
        }
    }
    """
    settings, _ = parse_dict_text(text)
    assert settings["boundaryField.movingWall.type"] == "fixedValue"
    assert settings["boundaryField.movingWall.value"] == "uniform (1 0 0)"
    assert settings["boundaryField.frontAndBack.type"] == "empty"


def test_foamfile_header_is_dropped(tmp_path: Path) -> None:
    p = tmp_path / "controlDict"
    p.write_text(CONTROL_DICT)
    settings, _ = parse_dict_file(p)
    # The header tracks the file's own path, not any decision — diffing it
    # would manufacture changes nobody made.
    assert not any(k.startswith("FoamFile") for k in settings)
    assert "application" in settings


def test_unbalanced_braces_are_reported_not_guessed() -> None:
    settings, problems = parse_dict_text("a { b 1;")
    assert settings["a.b"] == "1"
    assert problems  # the missing close brace is surfaced


def test_macros_are_left_literal() -> None:
    # Resolving a macro wrongly is invisible; leaving it literal is not.
    settings, _ = parse_dict_text("nu              $nuValue;\n#include \"initialConditions\"\n")
    assert settings["nu"] == "$nuValue"


def test_reading_a_case_walks_the_standard_subdirs(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "constant" / "polyMesh").mkdir()
    (case / "system" / "controlDict").write_text(CONTROL_DICT)
    (case / "constant" / "transportProperties").write_text("nu  0.0025;\n")
    (case / "0" / "U").write_text("internalField uniform (0 0 0);\n")
    (case / "constant" / "polyMesh" / "points").write_text("bogus")

    settings = read_case_settings(case)
    assert set(settings) == {
        "system/controlDict",
        "constant/transportProperties",
        "0/U",
    }
    # polyMesh is mesh output, not a decision, and is skipped.
    assert not any("polyMesh" in k for k in settings)

    flat = flatten(settings)
    assert flat[("constant/transportProperties", "nu")] == "0.0025"
