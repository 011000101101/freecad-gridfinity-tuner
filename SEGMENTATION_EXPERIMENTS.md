# Segmentation Experiments

This note captures the discarded body-segmentation prototype work so it can be retried later without repeating the same dead ends.

## Goal That Was Attempted

The assemble pipeline was extended to segment the upper body into:

- `rim`
- `outer shell`
- `top surface`
- `text and symbols`
- `pocket floor`
- `pocket walls`
- `lower body section`
- `remainder`

The intent was an exact boolean partition of the imported upper body after base replacement.

## Implemented Prototype Approaches

### 1. Repeated boolean claiming from `remaining`

Approach:

- build mask solids for each semantic segment
- repeatedly `common()` the current `remaining` shape with the next mask
- `cut()` the claimed shape away

Observed result:

- worked for some very small cases
- produced fragile topology on more complex models
- segment validity and exportability diverged

Failure modes:

- shapes stayed `isValid()` but meshed open
- repeated `common/cut` amplified tiny topology defects

### 2. Slice-stacked pocket wall extraction

Approach:

- slice the mid-body in many thin Z slabs
- build wall rings in each slab from 2D offsets
- fuse all slices back together

Observed result:

- `Pocket Walls` was the most common source of non-manifold or open export meshes
- runtime was poor even on the small benchmark

Conclusion:

- this was both slow and unstable

### 3. Mid-band XY wall-mask extrusion

Approach:

- replace the slice stack with a single XY wall mask projected from the mid-band
- extrude once through the pocket-wall Z range

Observed result:

- better than the slice-stack approach
- still not robust enough as part of the full multi-segment partition

### 4. Partition-based segment classification

Approach:

- build all masks first
- partition the whole upper body once
- classify resulting solids by precedence

Observed result:

- directionally better than repeated `common/cut`
- still produced segments that headless explicit meshing considered open on medium-complexity models

## Export / Meshing Findings

### 5. Explicit per-solid meshing

Approach:

- mesh each deliverable solid with `MeshPart.meshFromShape`
- combine meshes for export

Observed result:

- acceptable for the earlier 2-part assembly path
- not reliable for the advanced segment prototype
- `Detected Rim` and `Outer Shell` could be valid Part solids but still mesh open

### 6. Headless native-export fallback

Approach:

- create temporary `Part::Feature` objects
- round-trip one segment through FreeCAD's own exporter

Observed result:

- not usable in the VM headless environment
- `temp_doc.addObject("Part::Feature", ...)` failed with `Property not found`

Conclusion:

- host GUI export and VM headless export are materially different

## Benchmark Results That Motivated Revert

### Small wrench holder

- advanced segmentation could be made to complete
- runtime was still higher than justified

### Medium wrench holder

- `Detected Rim` then `Outer Shell` failed explicit mesh validation during prototype iterations
- this model was the clearest indication that the advanced segmentation path was not ready

### Bruch

- original 2-part assembly path remained good
- advanced segmentation did not provide enough confidence to keep the added complexity

## Current Decision

The advanced body segmentation was reverted.

Only shared rim detection / optional rim separation remains in scope for now:

- no shell / floor / wall / remainder export parts
- no rim replacement yet
- rim detection logic is retained because it is needed later for both assemble and merge workflows

## Current Rim-Only Status

The reduced-scope implementation keeps only:

- `Prepared Upper Body`
- optional `Detected Rim`
- `Repaired Base Component`

Current rim detection behavior:

- first tries the actual upper-body XY footprint projection
- falls back to the nominal detected-cell footprint only if projection building fails
- treats the `bruch` benchmark as a permanent regression case

Current benchmark expectation:

- `small`: no rim
- `medium`: no rim
- `bruch`: rim detected and exported as a separate component

Implementation note:

- the current rim-height check includes an additional allowance tied to the Z scan step (`4 * scan_step`)
- this was necessary because `bruch` measured a `3.6 mm` possible-rim band from the mesh-derived scan while it still needs to count as a rim benchmark
- if rim detection is revisited later with a more exact geometric method, this allowance should be one of the first things to re-evaluate

## Revisit Guidance

When revisiting advanced segmentation later:

1. Start from a single partition of the original upper body.
2. Do not reintroduce slice-stacked wall solids.
3. Validate segment meshes on `small`, `medium`, and `bruch` before expanding feature scope.
4. Treat host FreeCAD GUI export as the real export path; do not trust headless fallback behavior alone.
