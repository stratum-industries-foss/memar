"""Tests for bed mesh multi-profile functionality."""
import pytest
from app.fleet import _matrix_bounds, _xy_pair, _parse_bed_mesh_profiles


def test_matrix_bounds_normal():
    """Extract min/max from a normal 2D matrix."""
    matrix = [
        [0.1, 0.2, 0.3],
        [0.15, 0.25, 0.35],
        [0.12, 0.22, 0.32],
    ]
    min_z, max_z = _matrix_bounds(matrix)
    assert min_z == 0.1
    assert max_z == 0.35


def test_matrix_bounds_empty():
    """Handle empty matrix."""
    min_z, max_z = _matrix_bounds([])
    assert min_z == 0.0
    assert max_z == 0.0


def test_matrix_bounds_all_empty_rows():
    """Handle matrix with empty rows."""
    matrix = [[], []]
    min_z, max_z = _matrix_bounds(matrix)
    assert min_z == 0.0
    assert max_z == 0.0


def test_matrix_bounds_single_value():
    """Handle single value in matrix."""
    matrix = [[0.5]]
    min_z, max_z = _matrix_bounds(matrix)
    assert min_z == 0.5
    assert max_z == 0.5


def test_matrix_bounds_negative_values():
    """Handle negative Z values."""
    matrix = [[-0.5, -0.1], [0.0, 0.3]]
    min_z, max_z = _matrix_bounds(matrix)
    assert min_z == -0.5
    assert max_z == 0.3


def test_xy_pair_valid():
    """Parse valid [x, y] pair."""
    result = _xy_pair([10.5, 20.3])
    assert result == (10.5, 20.3)


def test_xy_pair_tuple():
    """Parse tuple [x, y] pair."""
    result = _xy_pair((100, 200))
    assert result == (100.0, 200.0)


def test_xy_pair_invalid_type():
    """Reject non-list/tuple."""
    result = _xy_pair("10,20")
    assert result is None


def test_xy_pair_wrong_length():
    """Accept pairs with length >= 2 (take first two)."""
    result = _xy_pair([10, 20, 30])
    assert result == (10.0, 20.0)  # Takes first two values
    result = _xy_pair([10])
    assert result is None  # Less than 2 elements


def test_xy_pair_non_numeric():
    """Reject non-numeric values."""
    result = _xy_pair(["x", "y"])
    assert result is None


def test_parse_bed_mesh_profiles_empty():
    """Handle empty profiles dict."""
    result = _parse_bed_mesh_profiles({})
    assert result == []


def test_parse_bed_mesh_profiles_single():
    """Parse single profile."""
    profiles_dict = {
        "probe1": {
            "points": [[0, 0], [100, 0], [100, 100]],
            "mesh_params": {"spacing": 25},
            "mesh_matrix": [[0.1, 0.2], [0.15, 0.25]],
        }
    }
    result = _parse_bed_mesh_profiles(profiles_dict)
    assert len(result) == 1
    assert result[0]["name"] == "probe1"
    assert result[0]["probed_points"] == 3
    assert result[0]["min_z"] == 0.1
    assert result[0]["max_z"] == 0.25


def test_parse_bed_mesh_profiles_multiple():
    """Parse multiple profiles."""
    profiles_dict = {
        "probe1": {"points": [[0, 0]], "mesh_params": {}, "mesh_matrix": [[0.5]]},
        "probe2": {"points": [[0, 0], [100, 0]], "mesh_params": {}, "mesh_matrix": [[0.3, 0.7]]},
        "manual": {"points": [], "mesh_params": {}, "mesh_matrix": []},
    }
    result = _parse_bed_mesh_profiles(profiles_dict)
    assert len(result) == 3
    assert result[0]["name"] == "probe1"
    assert result[1]["name"] == "probe2"
    assert result[2]["name"] == "manual"


def test_parse_bed_mesh_profiles_skip_invalid():
    """Skip profiles without 'points' key."""
    profiles_dict = {
        "valid": {"points": [[0, 0]], "mesh_params": {}},
        "invalid": {"mesh_params": {}},  # Missing 'points'
    }
    result = _parse_bed_mesh_profiles(profiles_dict)
    assert len(result) == 1
    assert result[0]["name"] == "valid"


def test_parse_bed_mesh_profiles_no_mesh_matrix():
    """Handle profiles with no mesh_matrix."""
    profiles_dict = {
        "probe1": {
            "points": [[0, 0], [100, 0]],
            "mesh_params": {"spacing": 25},
        }
    }
    result = _parse_bed_mesh_profiles(profiles_dict)
    assert len(result) == 1
    assert result[0]["min_z"] is None
    assert result[0]["max_z"] is None


def test_parse_bed_mesh_profiles_preserves_metadata():
    """Preserve all profile metadata."""
    profiles_dict = {
        "custom": {
            "points": [[0, 0], [50, 0], [100, 0], [0, 50], [50, 50], [100, 50], [0, 100], [50, 100], [100, 100]],
            "mesh_params": {"spacing": 50, "min_x": 0, "max_x": 100, "min_y": 0, "max_y": 100, "algo": "lagrange"},
            "mesh_matrix": [[0.0, 0.1, 0.2], [0.15, 0.25, 0.35], [0.1, 0.2, 0.3]],
        }
    }
    result = _parse_bed_mesh_profiles(profiles_dict)
    assert result[0]["probed_points"] == 9
    assert result[0]["mesh_params"]["algo"] == "lagrange"
    assert result[0]["min_z"] == 0.0
    assert result[0]["max_z"] == 0.35


def test_global_minmax_computation():
    """Verify global min/max across profiles."""
    profiles = [
        {"name": "p1", "min_z": 0.1, "max_z": 0.8},
        {"name": "p2", "min_z": 0.2, "max_z": 0.7},
        {"name": "p3", "min_z": 0.0, "max_z": 1.0},
    ]
    mins = [p["min_z"] for p in profiles if p.get("min_z") is not None]
    maxs = [p["max_z"] for p in profiles if p.get("max_z") is not None]
    global_min = min(mins) if mins else None
    global_max = max(maxs) if maxs else None
    assert global_min == 0.0
    assert global_max == 1.0
