"""Headless ParaView render for ``export_field_image``.

Run by ``pvbatch`` with a single JSON argv. Writes the result as JSON to
stdout, prefixed by a sentinel line so ``tools.py`` can parse past any
ParaView startup noise.

Not imported anywhere — invoked as a script. Keeping the ParaView import
inside ``main()`` so static analyzers don't trip over it on machines where
ParaView isn't installed.
"""

from __future__ import annotations

import json
import sys

_RESULT_SENTINEL = "<<<RENDER_RESULT>>>"


def _emit(payload: dict) -> None:
    print(_RESULT_SENTINEL, flush=True)
    print(json.dumps(payload), flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        _emit({"success": False, "reason": "missing_argv"})
        return 1
    try:
        opts = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        _emit({"success": False, "reason": "argv_not_json", "detail": str(exc)})
        return 1

    try:
        from paraview.simple import (
            ColorBy,
            CreateRenderView,
            GetActiveCamera,
            OpenFOAMReader,
            ResetCamera,
            SaveScreenshot,
            Show,
        )
    except ImportError as exc:
        _emit({"success": False, "reason": "paraview_import_failed", "detail": str(exc)})
        return 1

    case_marker = opts["case_marker"]
    field = opts["field"]
    time_request = opts.get("time", "latestTime")
    output_path = opts["output_path"]
    width = int(opts.get("width", 1000))
    height = int(opts.get("height", 600))

    try:
        reader = OpenFOAMReader(FileName=case_marker, CaseType="Reconstructed Case")
        reader.UpdatePipeline()
    except Exception as exc:
        _emit({"success": False, "reason": "openfoam_reader_failed", "detail": str(exc)})
        return 1

    times = list(reader.TimestepValues)
    if not times:
        _emit({"success": False, "reason": "no_time_directories"})
        return 1

    if time_request == "latestTime":
        chosen_time = times[-1]
    else:
        try:
            requested = float(time_request)
        except (TypeError, ValueError):
            _emit({"success": False, "reason": "invalid_time_value", "value": time_request})
            return 1
        chosen_time = min(times, key=lambda t: abs(t - requested))

    cell_arrays = list(reader.CellArrays)
    point_arrays = list(reader.PointArrays)
    if field in cell_arrays:
        association = "CELLS"
    elif field in point_arrays:
        association = "POINTS"
    else:
        _emit({
            "success": False,
            "reason": "field_not_found",
            "available_cell_arrays": cell_arrays,
            "available_point_arrays": point_arrays,
        })
        return 1

    reader.UpdatePipeline(time=chosen_time)

    view = CreateRenderView()
    view.ViewSize = [width, height]
    view.OrientationAxesVisibility = 0
    view.Background = [1.0, 1.0, 1.0]

    display = Show(reader, view)
    ColorBy(display, (association, field))
    display.RescaleTransferFunctionToDataRange(True, False)
    display.SetScalarBarVisibility(view, True)

    # 2D top-down camera for pitzDaily-style cases (~zero z extent). For 3D
    # cases ResetCamera with the default viewing angle is the fallback.
    bounds = reader.GetDataInformation().GetBounds()
    z_extent = bounds[5] - bounds[4]
    xy_extent = max(bounds[1] - bounds[0], bounds[3] - bounds[2])
    if xy_extent > 0 and z_extent / xy_extent < 0.05:
        cam = GetActiveCamera()
        cam.SetParallelProjection(True)
        cx = 0.5 * (bounds[0] + bounds[1])
        cy = 0.5 * (bounds[2] + bounds[3])
        cz = 0.5 * (bounds[4] + bounds[5])
        cam.SetFocalPoint(cx, cy, cz)
        cam.SetPosition(cx, cy, cz + max(xy_extent, 1.0))
        cam.SetViewUp(0.0, 1.0, 0.0)
        cam.SetParallelScale(0.5 * (bounds[3] - bounds[2]))
    ResetCamera(view)

    SaveScreenshot(output_path, view, ImageResolution=[width, height])

    info = reader.GetCellDataInformation() if association == "CELLS" else reader.GetPointDataInformation()
    array_info = info.GetArray(field) if info else None
    if array_info is not None:
        # Magnitude range (component -1) — works for scalars and vectors.
        cmin, cmax = array_info.GetRange(-1)
    else:
        cmin, cmax = 0.0, 0.0

    _emit({
        "success": True,
        "image_path": output_path,
        "rendered_time": float(chosen_time),
        "colorbar_range": [float(cmin), float(cmax)],
        "field_association": association,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
