import math
import unittest

from gridfinity_magnet_fix.geometry import (
    BBox2D,
    FootprintKind,
    ProfileFamily,
    axis_aligned_ratio,
    child_cell_bboxes,
    classify_bbox,
    effective_hole_centers,
    hole_centers,
    nominal_cell_bbox,
    subdivider_segments,
)


class GeometryTests(unittest.TestCase):
    def test_classify_standard_full(self):
        match = classify_bbox(35.62, 35.55, tolerance=0.1)
        self.assertIsNotNone(match)
        self.assertEqual(match.kind, FootprintKind.FULL)
        self.assertEqual(match.family, ProfileFamily.STANDARD)

    def test_classify_missing_lower_chamfer_half(self):
        match = classify_bbox(17.18, 37.15, tolerance=0.1)
        self.assertIsNotNone(match)
        self.assertEqual(match.kind, FootprintKind.HALF_Y)
        self.assertEqual(match.family, ProfileFamily.NO_LOWER_CHAMFER)

    def test_hole_centers_for_full_cell(self):
        bbox = BBox2D(0.0, 0.0, 35.6, 35.6)
        centers = hole_centers(bbox, FootprintKind.FULL)
        self.assertEqual(
            centers,
            (
                (4.8, 4.8),
                (30.8, 30.8),
                (4.8, 30.8),
                (30.8, 4.8),
            ),
        )

    def test_hole_centers_for_half_x(self):
        bbox = BBox2D(0.0, 0.0, 35.6, 15.6)
        centers = hole_centers(bbox, FootprintKind.HALF_X)
        self.assertEqual(centers, ((4.8, 7.8), (30.8, 7.8)))

    def test_hole_centers_for_quarter(self):
        bbox = BBox2D(0.0, 0.0, 15.6, 15.6)
        centers = hole_centers(bbox, FootprintKind.QUARTER)
        self.assertEqual(centers, ((7.8, 7.8),))

    def test_nominal_bbox_for_standard_full(self):
        bbox = BBox2D(3.2, 3.2, 38.8, 38.8)
        nominal = nominal_cell_bbox(bbox, FootprintKind.FULL)
        self.assertEqual(nominal, BBox2D(0.0, 0.0, 42.0, 42.0))

    def test_effective_hole_centers_for_subdivided_full(self):
        bbox = BBox2D(0.0, 0.0, 42.0, 42.0)
        centers = effective_hole_centers(bbox, FootprintKind.FULL, subdividers_enabled=True)
        self.assertEqual(
            centers,
            (
                (10.5, 10.5),
                (31.5, 10.5),
                (10.5, 31.5),
                (31.5, 31.5),
            ),
        )

    def test_subdivider_segments_for_half_x_nominal_length(self):
        bbox = BBox2D(0.0, 0.0, 42.0, 21.0)
        segments = subdivider_segments(bbox, FootprintKind.HALF_X)
        self.assertEqual(segments, ((21.0, 0.0, 21.0, 21.0),))

    def test_child_bboxes_for_subdivided_full(self):
        bbox = BBox2D(0.0, 0.0, 42.0, 42.0)
        children = child_cell_bboxes(bbox, FootprintKind.FULL, subdividers_enabled=True)
        self.assertEqual(
            children,
            (
                BBox2D(0.0, 0.0, 21.0, 21.0),
                BBox2D(21.0, 0.0, 42.0, 21.0),
                BBox2D(0.0, 21.0, 21.0, 42.0),
                BBox2D(21.0, 21.0, 42.0, 42.0),
            ),
        )

    def test_axis_aligned_ratio_tolerates_corner_detail(self):
        points = (
            (0.0, 0.0),
            (10.0, 0.0),
            (10.4, 0.4),
            (10.6, 0.8),
            (10.6, 10.2),
            (10.2, 10.6),
            (11.0, 10.0),
            (0.8, 10.6),
            (0.4, 10.4),
            (0.0, 10.0),
            (0.0, 0.0),
        )
        ratio = axis_aligned_ratio(points, angle_tolerance_deg=6.0)
        self.assertGreater(ratio, 0.8)


if __name__ == "__main__":
    unittest.main()
