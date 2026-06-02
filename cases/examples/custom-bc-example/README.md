# parabolicInletVelocity

Custom boundary condition for OpenFOAM v2412: a spatial Poiseuille profile for fully-developed channel inlets. Not shipped in OpenFOAM v2412 — `Function1`-based ramps exist but no spatial profile.

Full custom-extension failure-mode catalogue: [`docs/how-to-extend-openfoam.md`](../../../docs/how-to-extend-openfoam.md).

## Layout

```
cases/examples/custom-bc-example/
├── lib/                                      # the C++ source for the BC
│   ├── parabolicInletVelocityFvPatchVectorField.H
│   ├── parabolicInletVelocityFvPatchVectorField.C
│   └── Make/
│       ├── files                             # source list + library target
│       └── options                           # include + link flags
└── test-case/                                # a 2D channel flow that uses it
    ├── 0/{U,p}
    ├── constant/{transportProperties,turbulenceProperties}
    ├── system/{controlDict,blockMeshDict,fvSchemes,fvSolution}
    ├── Allrun
    └── Allclean
```

## Build it

```sh
of2412                                # source OpenFOAM v2412
cd cases/examples/custom-bc-example/lib
wmake libso
```

The library lands at `$FOAM_USER_LIBBIN/libparabolicInletVelocity.so`
(typically `~/OpenFOAM/<user>-v2412/platforms/linux64GccDPInt32Opt/lib/`).

## Run the test case

```sh
cd cases/examples/custom-bc-example/test-case
./Allrun                              # builds the lib if needed, runs simpleFoam
```

On a typical laptop the case converges in ~120 iterations (< 1 second).
The outlet profile should be (nearly) the same parabola as the inlet,
because the channel is in fully-developed Poiseuille flow.

## How the BC is used in `0/U`

```c
inlet
{
    type            parabolicInletVelocity;
    Umax            1.5;            // centreline velocity [m/s]
    flowDir         (1 0 0);        // flow direction (auto-normalised)
    transverseDir   (0 1 0);        // axis along which the profile varies
    centre          0.05;           // coord on transverseDir at the centreline
    halfHeight      0.05;           // channel half-height
    value           uniform (0 0 0); // initial field; replaced on first update
}
```

And in `system/controlDict`:

```c
libs            ("libparabolicInletVelocity.so");
```

The `libs` entry is what loads the `.so` into the solver at runtime. Forget
this line and OpenFOAM will refuse to recognise `parabolicInletVelocity` as a
patch field type, even though the library is built — `dlopen` happens
inside the solver, not inside `blockMesh`.

## What the BC code teaches

1. **The five constructors.** Every derived patch field must define
   five constructors (default, from-dict, mapped, copy, copy-with-iF).
   They are pure boilerplate, but missing one is the most common
   reason a custom BC fails to map cleanly across decomposition.
2. **`updateCoeffs`.** This is where the physics lives. The base class
   `fixedValueFvPatchVectorField::updateCoeffs()` MUST be called at the
   end, or the patch field will not be marked as updated and OpenFOAM
   will recompute it endlessly.
3. **`addToRunTimeSelectionTable` via `makePatchTypeField`.** This
   registers the type name (`"parabolicInletVelocity"`) so that
   OpenFOAM's selection table can resolve it from a `0/U` dictionary
   string. Without this macro the type is invisible at runtime.
4. **`Make/files` + `Make/options`.** The build system. `Make/files`
   lists sources and the library target; `Make/options` provides
   include paths and `-l` flags. Both are read by `wmake`.

## Extensions to try

- **Time-varying parameters.** Replace `scalar Umax_` with `autoPtr<Function1<scalar>> Umax_` (model on `swirlInletVelocityFvPatchVectorField.C` in `$FOAM_SRC`). Ramp without recompiling.
- **Custom function objects.** Derive from `Foam::functionObjects::fvMeshFunctionObject` to compute and write diagnostics during a run (friction factor over time, etc.).
- **Custom turbulence models.** Derive from `Foam::eddyViscosity<Foam::RASModel<BasicTurbulenceModel>>` and register via `makeTurbulenceModel.H`. Substantially more involved — see [`docs/how-to-extend-openfoam.md`](../../../docs/how-to-extend-openfoam.md).
