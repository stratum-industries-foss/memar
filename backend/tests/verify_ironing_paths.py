#!/usr/bin/env python
"""
Verification script for ironing path generation.

This script loads three reference models and generates ironing paths for each,
verifying that the module correctly:
1. Parses G-code
2. Extracts top surfaces
3. Generates ironing paths
4. Validates the output

Usage:
    python verify_ironing_paths.py
"""

import os
from pathlib import Path

from app.ironing_paths import (
    GCodeParser,
    IroningConfig,
    IroningMode,
    IroningPathGenerator,
    IroningPathValidator,
    LayerExtractor,
    TopSurfaceDetector,
)


def verify_model(name: str, gcode_path: str, config: IroningConfig) -> bool:
    """
    Verify ironing path generation for a single model.

    Args:
        name: Human-readable model name
        gcode_path: Path to G-code file
        config: Ironing configuration

    Returns:
        True if verification passed, False otherwise
    """
    print(f"\n{'=' * 60}")
    print(f"Verifying: {name}")
    print(f"{'=' * 60}")

    # Check file exists
    if not os.path.exists(gcode_path):
        print(f"ERROR: G-code file not found: {gcode_path}")
        return False

    # Read G-code
    with open(gcode_path, "r") as f:
        gcode_content = f.read()

    print(f"✓ Loaded G-code file ({len(gcode_content)} bytes)")

    # Parse G-code
    commands = GCodeParser.parse(gcode_content)
    print(f"✓ Parsed {len(commands)} G-code commands")

    # Extract layers
    layers = LayerExtractor.extract_layers(commands)
    print(f"✓ Extracted {len(layers)} layers")

    # Get top layer
    top_layer = TopSurfaceDetector.get_top_layer(layers)
    if not top_layer:
        print("✗ No top layer found")
        return False
    print(f"✓ Extracted top layer with {len(top_layer)} commands")

    # Extract surface moves
    surface_points = TopSurfaceDetector.extract_surface_moves(top_layer)
    if not surface_points:
        print("✗ No surface points extracted")
        return False
    print(f"✓ Extracted {len(surface_points)} surface points")

    # Print surface bounds
    xs = [p.x for p in surface_points]
    ys = [p.y for p in surface_points]
    zs = [p.z for p in surface_points]
    print(f"  - X range: {min(xs):.1f} to {max(xs):.1f} mm")
    print(f"  - Y range: {min(ys):.1f} to {max(ys):.1f} mm")
    print(f"  - Z height: {min(zs):.2f} to {max(zs):.2f} mm")

    # Generate ironing paths
    ironing_moves = IroningPathGenerator.generate_ironing_moves(
        surface_points, config
    )
    if not ironing_moves:
        print("✗ No ironing moves generated")
        return False
    print(f"✓ Generated {len(ironing_moves)} ironing G-code commands")

    # Validate paths
    validation = IroningPathValidator.validate_paths(ironing_moves, surface_points)
    print(f"\nValidation Results:")
    for key, value in validation.items():
        status = "✓" if value else "✗"
        print(f"  {status} {key}: {value}")

    # Check all validations passed
    if not all(validation.values()):
        print("\n✗ Validation failed")
        return False

    # Print sample G-code
    print(f"\nGenerated Ironing G-code (first 10 lines):")
    for i, move in enumerate(ironing_moves[:10]):
        gcode_line = move.to_gcode()
        print(f"  {i+1}: {gcode_line}")

    print(f"\n✓ Model verification PASSED")
    return True


def main():
    """Run verification for all reference models."""
    print("Ironing Path Generation Verification")
    print("=" * 60)

    # Get script directory
    script_dir = Path(__file__).parent
    fixtures_dir = script_dir / "fixtures"

    # Ensure fixtures directory exists
    fixtures_dir.mkdir(exist_ok=True)

    # Define reference models
    models = [
        {
            "name": "Reference Model 1: Simple Square",
            "file": fixtures_dir / "reference_model_square.gcode",
            "config": IroningConfig(
                enabled=True,
                mode=IroningMode.LIGHT_FLOW,
                flow_rate=0.5,
                speed=30.0,
                pattern_spacing=2.0,
            ),
        },
        {
            "name": "Reference Model 2: Complex Circle",
            "file": fixtures_dir / "reference_model_circle.gcode",
            "config": IroningConfig(
                enabled=True,
                mode=IroningMode.LIGHT_FLOW,
                flow_rate=0.6,
                speed=25.0,
                pattern_spacing=1.5,
            ),
        },
        {
            "name": "Reference Model 3: Tiny Detail",
            "file": fixtures_dir / "reference_model_tiny.gcode",
            "config": IroningConfig(
                enabled=True,
                mode=IroningMode.NO_EXTRUSION,
                flow_rate=0.0,
                speed=15.0,
                pattern_spacing=0.5,
            ),
        },
    ]

    # Verify each model
    results = []
    for model in models:
        result = verify_model(
            model["name"],
            str(model["file"]),
            model["config"],
        )
        results.append((model["name"], result))

    # Summary
    print(f"\n{'=' * 60}")
    print("VERIFICATION SUMMARY")
    print(f"{'=' * 60}")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    if passed == total:
        print(f"\n✓ All verification checks PASSED")
        return 0
    else:
        print(f"\n✗ Some verification checks FAILED")
        return 1


if __name__ == "__main__":
    exit(main())
