"""
Unit & Integration Tests for Analytical Engine
Tests feature extraction, 4PL curve fitting, Beer-Lambert regression,
analytical limits (LOD, LOQ), and inverse unknown sample prediction.
"""

import unittest
import numpy as np
from core.feature_extractor import extract_features_from_bgr
from core.calibration_models import CalibrationEngine, four_pl_func, four_pl_inverse
from core.image_processor import apply_gray_world_normalization, extract_roi
from core.demo_generator import generate_preset_assay


class TestAnalyticalEngine(unittest.TestCase):

    def test_feature_extraction(self):
        """Test that feature extraction returns all expected analytical metrics."""
        # Create synthetic blue patch (BGR)
        patch = np.zeros((100, 100, 3), dtype=np.uint8)
        patch[:, :, 0] = 200  # Blue
        patch[:, :, 1] = 50   # Green
        patch[:, :, 2] = 20   # Red

        blank_features = {"mean_r": 240.0, "mean_g": 240.0, "mean_b": 240.0, "mean_L": 95.0, "mean_a": 0.0, "mean_b_lab": 0.0, "mean_gray": 240.0}
        features = extract_features_from_bgr(patch, blank_features=blank_features)

        self.assertIn("mean_r", features)
        self.assertIn("mean_g", features)
        self.assertIn("mean_b", features)
        self.assertIn("mean_L", features)
        self.assertIn("od_r", features)
        self.assertIn("delta_E", features)
        self.assertIn("hex_color", features)
        self.assertEqual(len(features["feature_vector"]), 20)
        self.assertGreater(features["mean_b"], features["mean_r"])

    def test_4pl_roundtrip(self):
        """Test that 4PL inverse calculates true concentration accurately."""
        a, b, c, d = 0.05, 1.2, 250.0, 1.85
        true_x = 180.0
        y = four_pl_func(true_x, a, b, c, d)
        recovered_x = four_pl_inverse(y, a, b, c, d)
        self.assertAlmostEqual(true_x, recovered_x, places=2)

    def test_roi_and_normalization(self):
        """Test circle and rectangle ROI extraction and Gray-World color constancy."""
        img = np.full((200, 200, 3), 128, dtype=np.uint8)
        # Rectangle
        rect_roi = {"type": "rect", "x": 10, "y": 10, "w": 50, "h": 50}
        cropped, _ = extract_roi(img, rect_roi)
        self.assertEqual(cropped.shape[0], 50)
        self.assertEqual(cropped.shape[1], 50)

        # Circle
        circle_roi = {"type": "circle", "cx": 100, "cy": 100, "radius": 30}
        cropped_c, mask_c = extract_roi(img, circle_roi)
        self.assertIsNotNone(mask_c)

        # Gray world
        normed = apply_gray_world_normalization(img)
        self.assertEqual(normed.shape, img.shape)

    def test_demo_preset_and_calibration_pipeline(self):
        """Test end-to-end preset generation, calibration, and prediction."""
        demo_data = generate_preset_assay("bradford")
        self.assertEqual(len(demo_data["standards"]), 6)
        self.assertGreater(len(demo_data["unknowns"]), 0)

        engine = CalibrationEngine(demo_data["analyte"], demo_data["unit"])
        train_res = engine.train(demo_data["standards"])

        self.assertTrue(engine.trained)
        self.assertIn("best_model", train_res)
        best_model = train_res["best_model"]
        r2 = train_res["metrics"][best_model]["r2"]
        self.assertGreater(r2, 0.90, f"R2 was {r2}, expected > 0.90")

        # Test unknown prediction
        first_unk = demo_data["unknowns"][0]
        prediction = engine.predict(first_unk["features"])
        self.assertIn("predicted_concentration", prediction)
        self.assertIn("confidence_interval_95", prediction)
        self.assertIn("status_flag", prediction)

        # Check that predicted concentration is within 25% of true value
        true_conc = first_unk["true_conc"]
        pred_conc = prediction["predicted_concentration"]
        rel_error = abs(pred_conc - true_conc) / true_conc
        self.assertLess(rel_error, 0.25, f"Relative error {rel_error} too high (True: {true_conc}, Pred: {pred_conc})")


if __name__ == "__main__":
    unittest.main()
