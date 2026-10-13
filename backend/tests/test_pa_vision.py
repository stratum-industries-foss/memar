"""Tests for PA vision analysis."""

import pytest
from app.pa_vision import BandAnalysis, QualityScorer, CalibrationResult, analyze_calibration_image


def test_quality_scorer_not_implemented():
    """Quality scorer raises NotImplementedError (Phase 2 deliverable)."""
    with pytest.raises(NotImplementedError, match="Vision module requires OpenCV"):
        QualityScorer.score_band(
            image_array=None,
            band_bbox=(10, 20, 100, 50),
            reference_pa=0.05,
        )


def test_band_analysis_ordering():
    """Best band is selected from multiple analyses."""
    analyses = [
        BandAnalysis(
            band_index=0,
            pa_value=0.0,
            quality_score=0.5,
            defects=[],
            edge_sharpness=0.5,
            line_uniformity=0.5,
            surface_finish=0.5
        ),
        BandAnalysis(
            band_index=1,
            pa_value=0.05,
            quality_score=0.9,
            defects=[],
            edge_sharpness=0.9,
            line_uniformity=0.9,
            surface_finish=0.9
        ),
        BandAnalysis(
            band_index=2,
            pa_value=0.10,
            quality_score=0.6,
            defects=[],
            edge_sharpness=0.6,
            line_uniformity=0.6,
            surface_finish=0.6
        ),
    ]

    best = max(analyses, key=lambda x: x.quality_score)
    assert best.pa_value == 0.05


def test_calibration_result_creation():
    """CalibrationResult holds expected data."""
    band = BandAnalysis(
        band_index=0,
        pa_value=0.05,
        quality_score=0.85,
        defects=[],
        edge_sharpness=0.85,
        line_uniformity=0.85,
        surface_finish=0.85
    )

    result = CalibrationResult(
        job_id="test-job-123",
        band_analyses=[band],
        recommended_pa=0.05,
        confidence=0.85,
        notes="Test result",
    )

    assert result.job_id == "test-job-123"
    assert result.recommended_pa == 0.05
    assert result.confidence == 0.85
    assert len(result.band_analyses) == 1


def test_analyze_calibration_image_not_implemented():
    """analyze_calibration_image raises NotImplementedError (Phase 2 deliverable)."""
    metadata_dict = {
        "bands": [
            {"index": 0, "pa": 0.0, "z": 10.0},
            {"index": 1, "pa": 0.05, "z": 15.0},
        ],
        "layout": "vertical",
    }

    with pytest.raises(NotImplementedError, match="Vision module requires OpenCV"):
        analyze_calibration_image(
            image_path="/fake/path.jpg",
            band_metadata=metadata_dict,
        )
