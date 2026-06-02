/*---------------------------------------------------------------------------*\
  agentic-openfoam — custom-bc-example                          

  Class
      Foam::parabolicInletVelocityFvPatchVectorField

  Description
      Parabolic (Poiseuille) inlet velocity profile for fully-developed
      channel-class flows. The profile is:

          U(y) = Umax * (1 - ((y - y0) / h)^2) * flowDir

      where y is the projection of the face centre onto a user-specified
      transverse axis, y0 is the channel centreline coordinate on that axis,
      and h is the channel half-height. Values below zero (outside the
      half-height window) are clamped to zero.

      Useful as a benchmark inlet for laminar channel flow, plane-Poiseuille
      verification, and any case where the inlet should not introduce a
      development length.

  Usage
      Set the patch entry in 0/U:

      <patchName>
      {
          type            parabolicInletVelocity;
          Umax            1.5;            // centreline velocity [m/s]
          flowDir         (1 0 0);        // unit vector along the flow
          transverseDir   (0 1 0);        // unit vector along the profile
          centre          0.05;           // coord on transverseDir [m]
          halfHeight      0.05;           // channel half-height [m]
          value           uniform (0 0 0); // initial field; replaced on first update
      }

  SourceFiles
      parabolicInletVelocityFvPatchVectorField.C

\*---------------------------------------------------------------------------*/

#ifndef parabolicInletVelocityFvPatchVectorField_H
#define parabolicInletVelocityFvPatchVectorField_H

#include "fixedValueFvPatchFields.H"

namespace Foam
{

/*---------------------------------------------------------------------------*\
    Class parabolicInletVelocityFvPatchVectorField Declaration
\*---------------------------------------------------------------------------*/

class parabolicInletVelocityFvPatchVectorField
:
    public fixedValueFvPatchVectorField
{
    // Private data

        //- Centreline (peak) velocity
        scalar Umax_;

        //- Flow direction (auto-normalised)
        vector flowDir_;

        //- Transverse axis along which the parabola varies (auto-normalised)
        vector transverseDir_;

        //- Coordinate on transverseDir at the channel centreline
        scalar centre_;

        //- Channel half-height
        scalar halfHeight_;


public:

    //- Runtime type information
    TypeName("parabolicInletVelocity");


    // Constructors

        //- Construct from patch and internal field
        parabolicInletVelocityFvPatchVectorField
        (
            const fvPatch&,
            const DimensionedField<vector, volMesh>&
        );

        //- Construct from patch, internal field and dictionary
        parabolicInletVelocityFvPatchVectorField
        (
            const fvPatch&,
            const DimensionedField<vector, volMesh>&,
            const dictionary&
        );

        //- Construct by mapping onto a new patch
        parabolicInletVelocityFvPatchVectorField
        (
            const parabolicInletVelocityFvPatchVectorField&,
            const fvPatch&,
            const DimensionedField<vector, volMesh>&,
            const fvPatchFieldMapper&
        );

        //- Construct as copy
        parabolicInletVelocityFvPatchVectorField
        (
            const parabolicInletVelocityFvPatchVectorField&
        );

        //- Construct as copy setting internal field reference
        parabolicInletVelocityFvPatchVectorField
        (
            const parabolicInletVelocityFvPatchVectorField&,
            const DimensionedField<vector, volMesh>&
        );

        //- Return a clone
        virtual tmp<fvPatchField<vector>> clone() const
        {
            return fvPatchField<vector>::Clone(*this);
        }

        //- Clone with an internal field reference
        virtual tmp<fvPatchField<vector>> clone
        (
            const DimensionedField<vector, volMesh>& iF
        ) const
        {
            return fvPatchField<vector>::Clone(*this, iF);
        }


    // Member functions

        //- Update the patch values
        virtual void updateCoeffs();

        //- Write
        virtual void write(Ostream&) const;
};


} // End namespace Foam

#endif

// ************************************************************************* //
