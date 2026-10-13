"""Pressure Advance band detection and quality scoring.

Vision module for analyzing PA calibration prints.
Requires: pillow, numpy (optional dependencies)
"""

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class BandAnalysis:
    """Analysis result for a single PA band."""
    band_index: int
    pa_value: float
    quality_score: float  # 0.0-1.0, higher = better
    defects: list[str]  # ["underextrusion", "ghosting", "ripples"]
    edge_sharpness: float  # 0.0-1.0
    line_uniformity: float  # 0.0-1.0
    surface_finish: float  # 0.0-1.0


@dataclass
class CalibrationResult:
    """Complete PA calibration analysis."""
    job_id: str
    band_analyses: list[BandAnalysis]
    recommended_pa: float
    confidence: float  # 0.0-1.0
    notes: str | None = None


class BandDetector:
    """Locate and isolate bands in a calibration print image."""

    def __init__(self, image_path: str):
        self.image_path = image_path
        self._image = None

    def detect_bands(
        self,
        band_count: int,
        orientation: Literal["horizontal", "vertical"] = "vertical"
    ) -> list[tuple[int, int, int, int]]:
        """Segment image into bands.

        Args:
            band_count: Expected number of bands
            orientation: how bands are arranged

        Returns:
            list of (x_min, y_min, x_max, y_max) bounding boxes
        """
        # Stub: actual implementation uses edge detection + clustering
        # For now, return dummy rectangles
        logger.debug(f"Detecting {band_count} bands in {self.image_path}")
        bands = []
        # This will be implemented with actual CV2 edge detection
        return bands


class QualityScorer:
    """Rate the quality of extrusion in a band image."""

    @staticmethod
    def score_band(
        image_array,
        band_bbox: tuple,
        reference_pa: float | None = None
    ) -> BandAnalysis:
        """Score a single band.

        Args:
            image_array: numpy array or PIL Image
            band_bbox: (x_min, y_min, x_max, y_max)
            reference_pa: the PA value this band represents

        Returns:
            BandAnalysis with quality metrics

        Raises:
            NotImplementedError: Scorer requires OpenCV + numpy (Phase 2)
        """
        raise NotImplementedError(
            "Vision module requires OpenCV for edge detection, corner detection, and quality metrics. "
            "Install with: pip install -r requirements-optional.txt\n"
            "Phase 2 deliverable: real image analysis with synthetic + captured test fixtures."
        )


def analyze_calibration_image(
    image_path: str,
    band_metadata,  # PACalibrationModel dict or object
) -> CalibrationResult:
    """End-to-end analysis: detect bands → score each → select best PA.

    Args:
        image_path: path to uploaded calibration print image
        band_metadata: PACalibrationModel (dict with "bands" key containing list)

    Returns:
        CalibrationResult with recommended PA + confidence
    """
    detector = BandDetector(image_path)

    # Handle dict or object metadata
    if isinstance(band_metadata, dict):
        band_count = len(band_metadata.get("bands", []))
        layout = band_metadata.get("layout", "vertical")
        bands = band_metadata.get("bands", [])
    else:
        band_count = band_metadata.band_count
        layout = band_metadata.layout
        bands = band_metadata.bands

    band_bboxes = detector.detect_bands(
        band_count=band_count,
        orientation="vertical" if layout == "vertical" else "horizontal"
    )

    analyses = []
    for i, band_info in enumerate(bands):
        bbox = band_bboxes[i] if i < len(band_bboxes) else (0, 0, 100, 100)
        pa_val = band_info["pa"] if isinstance(band_info, dict) else band_info.pa_value
        analysis = QualityScorer.score_band(
            image_array=None,  # will be loaded from image_path
            band_bbox=bbox,
            reference_pa=pa_val,
        )
        analysis.band_index = i
        analysis.pa_value = pa_val
        analyses.append(analysis)

    # Select best PA (highest quality score)
    best = max(analyses, key=lambda x: x.quality_score) if analyses else analyses[0] if analyses else BandAnalysis(
        band_index=0, pa_value=0.0, quality_score=0.5, defects=[], edge_sharpness=0.5, line_uniformity=0.5, surface_finish=0.5
    )

    result = CalibrationResult(
        job_id="",  # filled by caller
        band_analyses=analyses,
        recommended_pa=best.pa_value,
        confidence=best.quality_score,
        notes=f"Selected PA={best.pa_value} from {len(analyses)} bands",
    )
    return result
