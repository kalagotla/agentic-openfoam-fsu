/*---------------------------------------------------------------------------*\
  agentic-openfoam — custom-bc-example                          
\*---------------------------------------------------------------------------*/

#include "parabolicInletVelocityFvPatchVectorField.H"
#include "addToRunTimeSelectionTable.H"
#include "fvPatchFieldMapper.H"
#include "volFields.H"

// * * * * * * * * * * * * * * * * Constructors  * * * * * * * * * * * * * * //

Foam::parabolicInletVelocityFvPatchVectorField::
parabolicInletVelocityFvPatchVectorField
(
    const fvPatch& p,
    const DimensionedField<vector, volMesh>& iF
)
:
    fixedValueFvPatchVectorField(p, iF),
    Umax_(0),
    flowDir_(Zero),
    transverseDir_(Zero),
    centre_(0),
    halfHeight_(1)
{}


Foam::parabolicInletVelocityFvPatchVectorField::
parabolicInletVelocityFvPatchVectorField
(
    const fvPatch& p,
    const DimensionedField<vector, volMesh>& iF,
    const dictionary& dict
)
:
    fixedValueFvPatchVectorField(p, iF, dict),
    Umax_(dict.get<scalar>("Umax")),
    flowDir_(dict.get<vector>("flowDir")),
    transverseDir_(dict.get<vector>("transverseDir")),
    centre_(dict.get<scalar>("centre")),
    halfHeight_(dict.get<scalar>("halfHeight"))
{
    if (mag(flowDir_) < SMALL || mag(transverseDir_) < SMALL)
    {
        FatalErrorInFunction
            << "flowDir and transverseDir must both be non-zero" << nl
            << exit(FatalError);
    }
    if (halfHeight_ <= SMALL)
    {
        FatalErrorInFunction
            << "halfHeight must be > 0; got " << halfHeight_ << nl
            << exit(FatalError);
    }
    flowDir_ /= mag(flowDir_);
    transverseDir_ /= mag(transverseDir_);
}


Foam::parabolicInletVelocityFvPatchVectorField::
parabolicInletVelocityFvPatchVectorField
(
    const parabolicInletVelocityFvPatchVectorField& ptf,
    const fvPatch& p,
    const DimensionedField<vector, volMesh>& iF,
    const fvPatchFieldMapper& mapper
)
:
    fixedValueFvPatchVectorField(ptf, p, iF, mapper),
    Umax_(ptf.Umax_),
    flowDir_(ptf.flowDir_),
    transverseDir_(ptf.transverseDir_),
    centre_(ptf.centre_),
    halfHeight_(ptf.halfHeight_)
{}


Foam::parabolicInletVelocityFvPatchVectorField::
parabolicInletVelocityFvPatchVectorField
(
    const parabolicInletVelocityFvPatchVectorField& ptf
)
:
    fixedValueFvPatchVectorField(ptf),
    Umax_(ptf.Umax_),
    flowDir_(ptf.flowDir_),
    transverseDir_(ptf.transverseDir_),
    centre_(ptf.centre_),
    halfHeight_(ptf.halfHeight_)
{}


Foam::parabolicInletVelocityFvPatchVectorField::
parabolicInletVelocityFvPatchVectorField
(
    const parabolicInletVelocityFvPatchVectorField& ptf,
    const DimensionedField<vector, volMesh>& iF
)
:
    fixedValueFvPatchVectorField(ptf, iF),
    Umax_(ptf.Umax_),
    flowDir_(ptf.flowDir_),
    transverseDir_(ptf.transverseDir_),
    centre_(ptf.centre_),
    halfHeight_(ptf.halfHeight_)
{}


// * * * * * * * * * * * * * * * Member Functions  * * * * * * * * * * * * * //

void Foam::parabolicInletVelocityFvPatchVectorField::updateCoeffs()
{
    if (updated())
    {
        return;
    }

    const vectorField& Cf = patch().Cf();
    vectorField U(Cf.size(), Zero);

    forAll(Cf, faceI)
    {
        const scalar y = (Cf[faceI] & transverseDir_) - centre_;
        const scalar eta = y / halfHeight_;
        // Clamp the parabola to zero outside [-1, 1] so a slightly oversized
        // patch (e.g. a wall cell at the channel edge) does not produce
        // negative velocity from the (1 - eta^2) term.
        const scalar profile = max(scalar(0), scalar(1) - sqr(eta));
        U[faceI] = Umax_ * profile * flowDir_;
    }

    operator==(U);
    fixedValueFvPatchVectorField::updateCoeffs();
}


void Foam::parabolicInletVelocityFvPatchVectorField::write(Ostream& os) const
{
    fvPatchField<vector>::write(os);
    os.writeEntry("Umax", Umax_);
    os.writeEntry("flowDir", flowDir_);
    os.writeEntry("transverseDir", transverseDir_);
    os.writeEntry("centre", centre_);
    os.writeEntry("halfHeight", halfHeight_);
    fvPatchField<vector>::writeValueEntry(os);
}


// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

namespace Foam
{
    makePatchTypeField
    (
        fvPatchVectorField,
        parabolicInletVelocityFvPatchVectorField
    );
}


// ************************************************************************* //
