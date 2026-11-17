"""
ABC BUTTONS - FRONT-FACE EXACT DESIGN MATCHING ENGINE BENCHMARK
==============================================================
Acceptance test suite & benchmark for the front-face exact design matching engine.

Test Matrices Covered:
  1. Same button on different backgrounds (red satin vs white desk vs cropped)
  2. White versus black buttons (strict color gate)
  3. Plain versus raised-ring designs (front rim gate)
  4. Engraved versus smooth designs (surface pattern gate)
  5. 2-hole versus 4-hole (hole count gate)
  6. Round versus oval versus flower-shaped (outer shape gate)
  7. Natural shell versus plastic lookalikes (material conservative estimation)
  8. Mixed-button photographs (NEED CLEAR FRONT PHOTO detection)
  9. Poor lighting and partially obscured buttons (NEED CLEAR FRONT PHOTO)
 10. Quantitative metrics calculation:
      - Exact-match precision
      - False-positive rate (must be 0.0%)
      - Top-1 accuracy (must be >= 85%)
      - Top-3 accuracy (must be 100%)
      - Correct rejection rate on non-catalog / non-buttons (must be 100%)
 11. Verification that diameter (14L/18L/24L) and thickness are NOT used for visual matching.
 12. Human approval gate requirement before confirming SKU to customer.
"""

import os
import sys
import unittest
import numpy as np

# Ensure parent path is loaded
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import ai_engine
from front_face_engine import (
    FrontFaceDesignMatcher,
    CATALOG_FRONT_FACE_PROFILES,
    get_front_face_matcher
)


class TestFrontFaceMatcherBenchmark(unittest.TestCase):
    """Rigorous acceptance test benchmark for Front-Face Exact Design Matching Engine."""

    @classmethod
    def setUpClass(cls):
        cls.matcher = get_front_face_matcher()
        cls.test_dir = os.path.join(os.path.dirname(__file__), "test_inquiries")

    # -------------------------------------------------------------------------
    # Test 1: Same button on different backgrounds
    # -------------------------------------------------------------------------
    def test_01_same_button_different_backgrounds(self):
        """Verify that fabric, satin cloth, or table background does NOT change the matched front-face SKU."""
        samples = [
            ("buyer_mop_white_2hole.jpg", "Natural white river shell 2-hole on red satin fabric"),
            ("exact_user_button_photo.jpg", "Natural white river shell 2-hole on wooden table surface"),
            ("user_uploaded_crop_test.jpg", "Cropped natural white river shell 2-hole on white paper")
        ]

        matched_skus = []
        for fname, desc in samples:
            fpath = os.path.join(self.test_dir, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    img_bytes = f.read()
                res = self.matcher.match(img_bytes, desc)
                matched_skus.append(res["best_match_sku"])
                self.assertEqual(res["decision_label"], "EXACT DESIGN CANDIDATE")
                self.assertEqual(res["best_match_sku"], "ABC-139")

        # All 3 different backgrounds must yield the same exact SKU: ABC-139
        self.assertTrue(all(s == "ABC-139" for s in matched_skus), f"Background influenced match: {matched_skus}")

    # -------------------------------------------------------------------------
    # Test 2: White versus Black buttons (Strict Color Gate)
    # -------------------------------------------------------------------------
    def test_02_white_versus_black_buttons_strict_color_gate(self):
        """Never return black buttons as exact matches for clearly white buttons."""
        white_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 4,
            "front_design": "smooth_rim",
            "is_engraved": False,
            "color_family": "white",
            "color_pattern": "solid_iridescent",
            "apparent_material": "shell_mop"
        }

        # Candidate ABC-138 is Midnight Black Lip
        cand = self.matcher.score_candidate(white_sample, CATALOG_FRONT_FACE_PROFILES["ABC-138"])
        self.assertFalse(cand["gates"]["color_gate"], "White button MUST fail color gate against Midnight Black ABC-138")
        self.assertFalse(cand["all_gates_passed"], "Gate failure must prevent all_gates_passed")
        self.assertTrue(any("Severe Color Conflict" in r for r in cand["mismatch_reasons"]))

        # Match call with white button query must never choose ABC-138 as exact match
        fpath = os.path.join(self.test_dir, "buyer_mop_white_2hole.jpg")
        with open(fpath, "rb") as f:
            img_bytes = f.read()
        res = self.matcher.match(img_bytes, "White pearl button")
        self.assertNotEqual(res["best_match_sku"], "ABC-138", "White sample must not match black SKU")

    # -------------------------------------------------------------------------
    # Test 3: Plain versus Raised-Ring designs
    # -------------------------------------------------------------------------
    def test_03_plain_versus_raised_ring_designs(self):
        """Flat-face button must not match raised saucer rim as an exact match."""
        flat_face_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 2,
            "front_design": "flat_face",
            "is_engraved": False,
            "color_family": "white",
            "color_pattern": "solid_iridescent",
            "apparent_material": "shell_mop"
        }

        # Compare against ABC-139 which has a deep saucer rim
        cand_saucer = self.matcher.score_candidate(flat_face_sample, CATALOG_FRONT_FACE_PROFILES["ABC-139"])
        self.assertFalse(cand_saucer["gates"]["design_gate"], "Flat face must fail design gate against raised saucer rim")
        self.assertTrue(any("Rim Conflict" in r for r in cand_saucer["mismatch_reasons"]))

    # -------------------------------------------------------------------------
    # Test 4: Engraved versus Smooth designs
    # -------------------------------------------------------------------------
    def test_04_engraved_versus_smooth_designs(self):
        """Never treat plain and engraved buttons as exact matches."""
        engraved_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 4,
            "front_design": "engraved_pattern",
            "is_engraved": True,
            "color_family": "white",
            "color_pattern": "solid_iridescent",
            "apparent_material": "shell_mop"
        }

        # All 21 standard catalog buttons are smooth / non-engraved
        for sku, prof in CATALOG_FRONT_FACE_PROFILES.items():
            if not prof.get("is_card"):
                cand = self.matcher.score_candidate(engraved_sample, prof)
                self.assertFalse(cand["gates"]["design_gate"], f"Engraved sample must fail design gate against {sku}")
                self.assertFalse(cand["all_gates_passed"])

        res = self.matcher.match(b"dummy_button_data_12345", "Custom engraved designer logo button with 4 holes")
        self.assertEqual(res["decision_label"], "NO EXACT MATCH", "Engraved sample must produce NO EXACT MATCH")
        self.assertIsNone(res["best_match_sku"])

    # -------------------------------------------------------------------------
    # Test 5: 2-hole versus 4-hole (Hole Count Gate)
    # -------------------------------------------------------------------------
    def test_05_2hole_versus_4hole_strict_gate(self):
        """Hole count mismatch must strictly prevent an EXACT MATCH result."""
        two_hole_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 2,
            "front_design": "saucer_rim",
            "is_engraved": False,
            "color_family": "gold_amber",
            "color_pattern": "solid_iridescent",
            "apparent_material": "shell_mop"
        }

        # ABC-137 is strictly 4-hole
        cand_4hole = self.matcher.score_candidate(two_hole_sample, CATALOG_FRONT_FACE_PROFILES["ABC-137"])
        self.assertFalse(cand_4hole["gates"]["hole_gate"], "2-hole sample must fail hole gate against 4-hole ABC-137")
        self.assertFalse(cand_4hole["all_gates_passed"])
        self.assertTrue(any("Hole Count Conflict" in r for r in cand_4hole["mismatch_reasons"]))

        # ABC-139 is strictly 2-hole
        cand_2hole = self.matcher.score_candidate(two_hole_sample, CATALOG_FRONT_FACE_PROFILES["ABC-139"])
        self.assertTrue(cand_2hole["gates"]["hole_gate"], "2-hole sample must pass hole gate against 2-hole ABC-139")

    # -------------------------------------------------------------------------
    # Test 6: Round versus Oval versus Flower-shaped (Outer Shape Gate)
    # -------------------------------------------------------------------------
    def test_06_round_versus_flower_versus_oval(self):
        """Outer shape conflict must prevent an EXACT MATCH result."""
        flower_sample = {
            "is_button": True,
            "outer_shape": "flower",
            "holes_detected": 2,
            "front_design": "flower_contour",
            "is_engraved": False,
            "color_family": "white",
            "color_pattern": "solid_iridescent",
            "apparent_material": "shell_mop"
        }

        # Compare against round catalog button ABC-139
        cand = self.matcher.score_candidate(flower_sample, CATALOG_FRONT_FACE_PROFILES["ABC-139"])
        self.assertFalse(cand["gates"]["shape_gate"], "Flower shape must fail shape gate against round SKU")
        self.assertFalse(cand["all_gates_passed"])
        self.assertTrue(any("Outer Shape Conflict" in r for r in cand["mismatch_reasons"]))

        res = self.matcher.match(b"dummy_flower_btn", "Flower shaped carved shell button")
        self.assertEqual(res["decision_label"], "NO EXACT MATCH")

    # -------------------------------------------------------------------------
    # Test 7: Natural Shell versus Plastic Lookalikes
    # -------------------------------------------------------------------------
    def test_07_natural_shell_versus_plastic_lookalikes(self):
        """Distinguish confirmed material from visual guesses and catalog polyester."""
        poly_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 4,
            "front_design": "center_well_rim",
            "is_engraved": False,
            "color_family": "white",
            "color_pattern": "chalk_matte",
            "apparent_material": "polyester_resin"
        }

        # Chalk polyester button must match ABC-POLY-18L-08 or ABC-147
        cand_poly = self.matcher.score_candidate(poly_sample, CATALOG_FRONT_FACE_PROFILES["ABC-POLY-18L-08"])
        self.assertTrue(cand_poly["all_gates_passed"])
        self.assertGreaterEqual(cand_poly["confidence_score"], 85)

        # Wood/Horn sample must be rejected from active catalog
        wood_sample = {
            "is_button": True,
            "outer_shape": "round",
            "holes_detected": 4,
            "front_design": "center_well_rim",
            "is_engraved": False,
            "color_family": "brown",
            "color_pattern": "wood_grain",
            "apparent_material": "wood"
        }
        cand_wood = self.matcher.score_candidate(wood_sample, CATALOG_FRONT_FACE_PROFILES["ABC-136"])
        self.assertFalse(cand_wood["gates"]["material_gate"], "Wood must fail material gate")
        self.assertTrue(any("Material Scope Conflict" in r for r in cand_wood["mismatch_reasons"]))

    # -------------------------------------------------------------------------
    # Test 8: Mixed-button photographs
    # -------------------------------------------------------------------------
    def test_08_mixed_button_photographs(self):
        """For photos containing multiple distinct designs, detect ambiguity and request clarification."""
        res = self.matcher.match(b"fake_mixed_bytes_123", "Multiple different buttons scattered on table, various designs")
        self.assertEqual(res["decision_label"], "NEED CLEAR FRONT PHOTO")
        self.assertEqual(res["match_status"], "NEED_CLEAR_PHOTO")
        self.assertIsNone(res["best_match_sku"])
        self.assertIn("ek se zyada button designs", res["whatsapp_buyer_draft"])

    # -------------------------------------------------------------------------
    # Test 9: Poor lighting and partially obscured buttons
    # -------------------------------------------------------------------------
    def test_09_poor_lighting_and_partially_obscured(self):
        """Low lighting or blurred details must yield NEED CLEAR FRONT PHOTO."""
        res = self.matcher.match(b"fake_dark_bytes_123", "blurry dark photo of a button")
        self.assertEqual(res["decision_label"], "NEED CLEAR FRONT PHOTO")
        self.assertEqual(res["match_status"], "NEED_CLEAR_PHOTO")
        self.assertIsNone(res["best_match_sku"])

    # -------------------------------------------------------------------------
    # Test 10: Quantitative Metrics & Benchmark Evaluation
    # -------------------------------------------------------------------------
    def test_10_quantitative_benchmark_metrics(self):
        """Measures exact-match precision, false-positive rate, Top-1 accuracy, Top-3 accuracy, and correct rejection."""
        # Unseen Benchmark Dataset: (filename, ground_truth_sku, ground_truth_label, query_text)
        benchmark_cases = [
            ("buyer_mop_white_2hole.jpg", "ABC-139", "EXACT DESIGN CANDIDATE", "White 2-hole river shell with raised outer rim"),
            ("buyer_mop_turquoise_blue.jpg", "ABC-142", "EXACT DESIGN CANDIDATE", "Turquoise blue dyed MOP shell"),
            ("buyer_mop_factory_bulk.jpg", "ABC-136", "EXACT DESIGN CANDIDATE", "White agoya pearl shell bulk buttons"),
            ("buyer_mop_smoky_grey_4hole.jpg", "ABC-141", "EXACT DESIGN CANDIDATE", "Smoky charcoal trocas shell 4-hole"),
            ("buyer_abc_sample_hanger_card.jpg", "ABC-SAMPLE-CARD-01", "EXACT DESIGN CANDIDATE", "Sample hanger card"),
            ("card_upright.jpg", "ABC-SAMPLE-CARD-01", "EXACT DESIGN CANDIDATE", "Card upright sample set"),
            ("exact_user_button_photo.jpg", "ABC-139", "EXACT DESIGN CANDIDATE", "River shell 2-hole user photo"),
            ("user_uploaded_crop_test.jpg", "ABC-139", "EXACT DESIGN CANDIDATE", "Cropped river shell photo")
        ]

        # Negative / Rejection Cases: (name, query, expected_label)
        rejection_cases = [
            ("synthetic_noise", "plain background noise", "NO EXACT MATCH"),
            ("wood_toggle", "Wooden duffle coat horn toggle button", "NO EXACT MATCH"),
            ("metal_shank", "Blazer gold brass shank button with crest", "NO EXACT MATCH"),
            ("custom_engraved", "Custom engraved laser logo shirt button", "NO EXACT MATCH"),
            ("flower_novelty", "Five petal flower shaped acrylic button", "NO EXACT MATCH"),
            ("plain_fabric", "Plain bedsheet fabric swatch with no buttons", "NO EXACT MATCH"),
            ("mixed_pile", "Multiple different mixed buttons scattered together", "NEED CLEAR FRONT PHOTO")
        ]

        top_1_hits = 0
        top_3_hits = 0
        total_positives = len(benchmark_cases)

        for fname, true_sku, expected_label, desc in benchmark_cases:
            fpath = os.path.join(self.test_dir, fname)
            with open(fpath, "rb") as f:
                img_data = f.read()

            res = ai_engine.analyze_button_or_fabric_image(img_data, desc)
            top_cands = res.get("top_candidates", [])
            cand_skus = [c.get("sku") for c in top_cands]

            # Top-1 Check
            if cand_skus and cand_skus[0] == true_sku:
                top_1_hits += 1

            # Top-3 Check
            if true_sku in cand_skus:
                top_3_hits += 1

            self.assertEqual(res.get("decision_label"), expected_label, f"Failed decision label for {fname}")

        # Negative samples evaluation
        correct_rejections = 0
        false_positives = 0

        for r_name, query_text, exp_label in rejection_cases:
            dummy_bytes = bytes([128] * 1024)
            res = ai_engine.analyze_button_or_fabric_image(dummy_bytes, query_text)
            actual_label = res.get("decision_label")

            if actual_label in ["NO EXACT MATCH", "NEED CLEAR FRONT PHOTO"]:
                correct_rejections += 1
            else:
                false_positives += 1

        top_1_acc = (top_1_hits / total_positives) * 100.0
        top_3_acc = (top_3_hits / total_positives) * 100.0
        fp_rate = (false_positives / len(rejection_cases)) * 100.0
        rejection_rate = (correct_rejections / len(rejection_cases)) * 100.0

        print(f"\n================ FRONT-FACE EXACT MATCH BENCHMARK RESULTS ================")
        print(f"Positive Test Samples: {total_positives}")
        print(f"Negative/Rejection Samples: {len(rejection_cases)}")
        print(f"Top-1 Accuracy: {top_1_acc:.1f}% ({top_1_hits}/{total_positives})")
        print(f"Top-3 Accuracy: {top_3_acc:.1f}% ({top_3_hits}/{total_positives})")
        print(f"False Positive Rate: {fp_rate:.1f}% ({false_positives}/{len(rejection_cases)})")
        print(f"Unknown Rejection Rate: {rejection_rate:.1f}% ({correct_rejections}/{len(rejection_cases)})")
        print(f"=========================================================================\n")

        self.assertGreaterEqual(top_1_acc, 85.0, "Top-1 accuracy must be >= 85%")
        self.assertEqual(top_3_acc, 100.0, "Top-3 accuracy must be 100%")
        self.assertEqual(fp_rate, 0.0, "False positive rate must be 0.0% (strict avoidance of false exact matches)")
        self.assertEqual(rejection_rate, 100.0, "Rejection of unknown/non-catalog designs must be 100%")

    # -------------------------------------------------------------------------
    # Test 11: Explicit Exclusion of Diameter / Thickness / Ligne Size
    # -------------------------------------------------------------------------
    def test_11_diameter_and_thickness_excluded_from_visual_matching(self):
        """Verify that line sizes (14L/18L/24L) or thickness are NOT used for candidate ranking."""
        matcher = self.matcher
        # Two identical designs differing only in size notes
        q1 = matcher.extract_features(b"valid_button_bytes_123", "White 2-hole river shell 14L")
        q2 = matcher.extract_features(b"valid_button_bytes_123", "White 2-hole river shell 24L")

        c1 = matcher.score_candidate(q1, CATALOG_FRONT_FACE_PROFILES["ABC-139"])
        c2 = matcher.score_candidate(q2, CATALOG_FRONT_FACE_PROFILES["ABC-139"])

        self.assertEqual(c1["raw_score"], c2["raw_score"], "Visual score must be invariant to user-requested ligne size")

    # -------------------------------------------------------------------------
    # Test 12: Mandatory Human Approval Gate
    # -------------------------------------------------------------------------
    def test_12_mandatory_human_approval_gate(self):
        """Require human approval before confirming an exact SKU to the customer."""
        fpath = os.path.join(self.test_dir, "buyer_mop_white_2hole.jpg")
        with open(fpath, "rb") as f:
            img_bytes = f.read()

        res = ai_engine.analyze_button_or_fabric_image(img_bytes, "White 2-hole river shell")
        self.assertTrue(res.get("requires_human_approval"), "Analysis output must enforce requires_human_approval")
        self.assertIn("requires_human_approval", res)


if __name__ == "__main__":
    unittest.main()
