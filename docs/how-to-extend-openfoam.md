# How to extend OpenFOAM

Custom boundary conditions, function objects, transport models, and solvers for OpenFOAM v2412 (ESI release). Worked example: [`cases/examples/custom-bc-example/`](../cases/examples/custom-bc-example/) — a compilable parabolic-inlet BC.

## The canonical workflow

For any new BC, function object, transport model, or solver:

1. **Find the closest existing example** in `$FOAM_SRC` or
   `$FOAM_APP`. Don't write from scratch. For a BC, look under
   `$FOAM_SRC/finiteVolume/fields/fvPatchFields/derived/`. For a
   solver, copy from `$FOAM_APP/solvers/`.
2. **Copy into your user dir** at `$WM_PROJECT_USER_DIR`
   (typically `~/OpenFOAM/<user>-v2412/`). Rename the class and the
   files consistently.
3. **Edit `Make/files`** to set:
   - the source list (your `.C` files),
   - the target — `$(FOAM_USER_LIBBIN)/lib<Name>` for a library, or
     `$(FOAM_USER_APPBIN)/<name>` for an application.
   **Always use the USER variants** — `$FOAM_LIBBIN` and `$FOAM_APPBIN`
   are root-owned.
4. **Edit `Make/options`** to add the `-I` include paths and `-l`
   link flags. `LIB_SRC` and `LIB_LIBS` substitutions handle the
   OpenFOAM module paths; you rarely need anything else.
5. **`wmake libso`** (library) or **`wmake`** (executable). If
   `wmakeLnInclude` hasn't been run for a directory you depend on,
   `wmake` will do it.
6. **Load the library** in your case's `system/controlDict` via
   `libs ("libfoo.so");`. **This is the most common omission.** The
   library compiles, the type-registration macro fires, but the
   solver still doesn't see your type because the `.so` was never
   `dlopen`'d.
7. **Run.** If the solver fails with "unknown type X", you forgot
   step 6 or the `.so` is in the wrong directory (see failure mode
   #2 below).

## The five failure modes

Ordered by frequency, not severity.

### 1. Missing `libs ()` in `controlDict`

**Symptom.** Runtime error at solver startup:

```
--> FOAM FATAL IO ERROR: (openfoam-2412)
Unknown patchField type parabolicInletVelocity for patch type patch

Valid patchField types are :

26
(
calculated
codedFixedValue
fixedValue
...
)
```

The type list does not include yours, even though `wmake` succeeded
and `ls $FOAM_USER_LIBBIN` shows the `.so`.

**Cause.** The library is on disk but was never loaded into the
solver process. OpenFOAM resolves type-registration tables at
`dlopen` time, not at link time.

**Fix.** Add to `system/controlDict` (top level, not inside any
sub-dict):

```c
libs            ("libparabolicInletVelocity.so");
```

For multiple libraries:

```c
libs
(
    "libfoo.so"
    "libbar.so"
);
```

### 2. Wrong target directory

**Symptom.** `wmake` fails with:

```
cannot create regular file '/usr/lib/openfoam/openfoam2412/platforms/linux64GccDPInt32Opt/lib/libfoo.so': Permission denied
```

Or — more insidiously — `wmake` succeeds but the solver still can't
find the type, because the library landed somewhere the solver isn't
looking (e.g. the cwd).

**Cause.** `Make/files` points at `$FOAM_LIBBIN` (system-owned) or
omits the directory entirely.

**Fix.** In `Make/files`:

```
parabolicInletVelocityFvPatchVectorField.C

LIB = $(FOAM_USER_LIBBIN)/libparabolicInletVelocity
```

Note: **no `.so` extension** on the `LIB` line — `wmake` adds it.

### 3. ESI ↔ Foundation ABI mismatch

**Symptom.** Library compiles against one release, loads against
another, and the solver dies with:

```
symbol lookup error: libfoo.so: undefined symbol: _ZN4Foam12parabolicInletVelocityFvPatchVectorFieldC1ERKNS_7fvPatchERKNS_18DimensionedFieldINS_6VectorIdEENS_7volMeshEEE
```

The mangled symbol mentions a class that exists in both forks but
with different internal layouts.

**Cause.** The ESI fork (`openfoam.com`, versions like `v2412`) and
the Foundation fork (`openfoam.org`, versions like `12`, `13`) have
diverged enough that compiled `.so` files are NOT drop-in portable
between them. Header layouts, RTS macros, and even some signatures
differ.

**Fix.** Always check before compiling:

```sh
echo $WM_PROJECT_VERSION   # which fork+version is sourced
echo $FOAM_USER_LIBBIN     # which user dir the lib will go to
```

If both `~/OpenFOAM/<user>-v2412/` and `~/OpenFOAM/<user>-12/` exist
on your machine, **they are separate target dirs**. Re-compile in
the user dir matching the sourced version. The cross-fork
incompatibility is documented at
<https://openfoamwiki.net/index.php/Installation/Compatibility_Matrix>.

### 4. Missing `lnInclude` paths in `Make/options`

**Symptom.** Compile fails with:

```
fatal error: fvPatchFieldMapper.H: No such file or directory
```

or:

```
fatal error: turbulentTransportModel.H: No such file or directory
```

The header exists in `$FOAM_SRC` but `wmake` cannot find it.

**Cause.** `Make/options` does not list the right `lnInclude`
directories under `EXE_INC`. Each OpenFOAM module has an `lnInclude/`
subdirectory containing symlinks to all its public headers; you
must add it explicitly.

**Fix.** A standard `Make/options` for a custom BC looks like:

```
EXE_INC = \
    -I$(LIB_SRC)/finiteVolume/lnInclude \
    -I$(LIB_SRC)/meshTools/lnInclude

LIB_LIBS = \
    -lfiniteVolume \
    -lmeshTools
```

For a turbulence-model derivation you'll also need:

```
    -I$(LIB_SRC)/TurbulenceModels/turbulenceModels/lnInclude \
    -I$(LIB_SRC)/TurbulenceModels/incompressible/lnInclude \
    -I$(LIB_SRC)/transportModels \
```

Reference: look at the `Make/options` of the example BC nearest to
yours and copy its include list.

### 5. Missing `makePatchTypeField` (or equivalent RTS macro)

**Symptom.** Library compiles cleanly. Library loads via `libs ()`.
But the solver still doesn't recognise your type:

```
Unknown patchField type myCustomBC ...
```

**Cause.** You forgot the macro at the bottom of the `.C` file that
adds your type to the runtime selection table. Without it, the
class exists in the `.so` but isn't registered as a selectable type.

**Fix.** Add at the bottom of your `.C` file, after the namespace
`Foam` content:

```cpp
namespace Foam
{
    makePatchTypeField
    (
        fvPatchVectorField,
        parabolicInletVelocityFvPatchVectorField
    );
}
```

The macro varies by class hierarchy:

- BC derived from `fvPatchVectorField` → `makePatchTypeField`
- Function object → `addToRunTimeSelectionTable(functionObject, ...)`
- Turbulence model → `addToRunTimeSelectionTable(<base>, <derived>, dictionary)`
  plus `makeTurbulenceModel` or similar.

When in doubt, look at the bottom of the OpenFOAM source file you
copied from. The RTS macro is always there.

## codeStream / codedFixedValue — the inline alternative

For one-off BCs that you don't want to ship as a separate library,
OpenFOAM supports inline C++ via `codedFixedValue`, `codedMixed`,
`codedFunctionObject`, and `codeStream`. Example:

```c
inlet
{
    type            codedFixedValue;
    value           uniform (0 0 0);
    name            myInlet;     // unique tag; cached as a .so under dynamicCode/
    code
    #{
        const vectorField& Cf = patch().Cf();
        vectorField U(Cf.size(), Zero);
        forAll(Cf, i)
        {
            scalar y = Cf[i].y() - 0.05;
            U[i] = vector(1.5 * (1.0 - sqr(y/0.05)), 0, 0);
        }
        operator==(U);
    #};
}
```

**When to use:** experimental BCs, one-off function objects, dictionary-
driven extensions you don't want to maintain separately.

**Limits:**

- No access to OpenFOAM's RTS machinery (no new selectable types).
- Lives in the case directory; not reusable across cases without
  copy-paste.
- Requires `allowSystemOperations 1` in `$WM_PROJECT_DIR/etc/controlDict`,
  which Talos flagged as an RCE surface
  ([TALOS-2025-2292](https://talosintelligence.com/vulnerability_reports/TALOS-2025-2292)).
  Do not enable on shared machines without thinking about it.
- Compile errors surface as long C++ traces in the run log — fine
  for an agent that can iterate, painful for a human.

For research code you intend to keep, use a proper library
(`cases/examples/custom-bc-example/`). For one-shot experiments, `codedFixedValue`
is fine.

## Agent-assisted extension

The `research_assistant` MCP server wraps the build loop and source-tree
discovery so an agent can iterate on a custom BC without losing context to
raw `wmake` output:

- `discover_user_lib_path()` → `$FOAM_USER_LIBBIN`, `$WM_PROJECT_USER_DIR`, `$WM_PROJECT_VERSION` (also detects ESI vs Foundation fork).
- `find_examples_of_base_class(base_class, max_results)` → greps `$FOAM_SRC` / `$FOAM_APP` for existing derivations so the agent can model on the closest match.
- `wmake_and_report(directory)` → runs `wmake`, parses errors into structured returns (`missing_header`, `missing_library`, `undefined_symbol`, `compile_error`) with hints.

The researcher writes the C++; the agent does not generate it. See [`servers/research_assistant/README.md`](../servers/research_assistant/README.md) and [`docs/architecture.md`](architecture.md) for tool signatures.

## References

- OpenFOAM User Guide §3.2 — Compiling applications and libraries:
  <https://doc.cfd.direct/openfoam/user-guide-v12/compiling-applications>
- ESI v2412 API guide (`codeStream` etc.):
  <https://www.openfoam.com/documentation/guides/latest/api/>
- Holzmann CFD code-development screencasts:
  <https://wiki.openfoam.com/Code_development_by_Tobias_Holzmann>
- Kassem — How to add a new turbulence model (post-OF-3.0):
  <http://hassankassem.me/posts/newturbulencemodel6/>
- Nilsson / Chalmers — Implement a new boundary condition (PDF):
  <https://www.tfd.chalmers.se/~hani/kurser/OS_CFD_2010/implementBoundaryCondition.pdf>
- OpenFOAM Wiki — Installation Compatibility Matrix (ESI vs Foundation):
  <https://openfoamwiki.net/index.php/Installation/Compatibility_Matrix>
