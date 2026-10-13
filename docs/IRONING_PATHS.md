# Ironing Path Generation Module

## Overview

The ironing path generation module (`backend/app/ironing_paths.py`) implements automatic generation of ironing paths for 3D printing. Ironing is a post-print surface smoothing technique that runs a non-extruding or low-flow pass over the top layer to flatten and improve surface quality.

## Features

- **G-code Parsing**: Parses standard Marlin/Klipper G-code into structured commands
- **Layer Extraction**: Automatically detects and extracts individual print layers by Z height
- **Top Surface Detection**: Identifies the topmost layer and extracts its contours
- **Path Generation**: Generates parallel ironing lines with configurable:
  - Flow rate (0-100% of normal)
  - Speed (mm/s)
  - Z offset from surface
  - Line spacing
  - Extrusion modes (no extrusion, light flow, medium flow)
- **Path Validation**: Verifies generated G-code for correctness and completeness

## Architecture

### Core Classes

#### `Point3D`
Represents a 3D coordinate with position (X, Y, Z) and extrusion (E).
```python
point = Point3D(x=100.0, y=50.0, z=0.2, e=10.5)
distance = point.distance_to(other_point)  # Euclidean distance
distance_2d = point.distance_2d(other_point)  # XY plane only
```

#### `GCodeCommand`
Represents a single G-code line with parsed parameters.
```python
cmd = GCodeCommand(
    command="G1",
    x=100.0,
    y=50.0,
    z=0.2,
    e=5.0,
    f=3000,
    comment="Move to position"
)
gcode_str = cmd.to_gcode()  # Convert back to G-code string
```

#### `GCodeParser`
Static methods for parsing G-code content.
```python
commands = GCodeParser.parse(gcode_content)
# Returns list[GCodeCommand]
```

#### `LayerExtractor`
Extracts individual layers by detecting Z height changes.
```python
layers = LayerExtractor.extract_layers(commands)
# Returns list[list[GCodeCommand]]
```

#### `TopSurfaceDetector`
Identifies and extracts the top surface.
```python
top_layer = TopSurfaceDetector.get_top_layer(layers)
surface_points = TopSurfaceDetector.extract_surface_moves(top_layer)
# Returns list[Point3D]
```

#### `IroningPathGenerator`
Generates ironing G-code commands.
```python
ironing_moves = IroningPathGenerator.generate_ironing_moves(
    surface_points=points,
    config=ironing_config
)
# Returns list[GCodeCommand]
```

#### `IroningPathValidator`
Validates generated ironing paths.
```python
validation_results = IroningPathValidator.validate_paths(
    paths=ironing_moves,
    surface_points=surface_points
)
# Returns dict with validation results
```

### Configuration

#### `IroningConfig`
Configures ironing behavior.

```python
config = IroningConfig(
    enabled=True,
    mode=IroningMode.LIGHT_FLOW,  # NO_EXTRUSION, LIGHT_FLOW, MEDIUM_FLOW
    flow_rate=0.5,                # 50% of normal flow
    speed=30.0,                   # mm/s
    z_offset=0.0,                 # mm above surface
    pattern_spacing=1.0,          # mm between parallel lines
    reverse_direction=False       # reverse first pass direction
)

# Serialize to dictionary
data = config.to_dict()

# Deserialize from dictionary
config = IroningConfig.from_dict(data)
```

#### `IroningMode` Enum
- `NO_EXTRUSION`: Don't extrude during ironing (pure mechanical pressing)
- `LIGHT_FLOW`: Extrude at 40-50% flow rate
- `MEDIUM_FLOW`: Extrude at 60-70% flow rate

## Usage Example

### Complete Pipeline

```python
from app.ironing_paths import (
    GCodeParser,
    IroningConfig,
    IroningMode,
    IroningPathGenerator,
    LayerExtractor,
    TopSurfaceDetector,
    create_default_config,
)

# Read G-code file
with open("print.gcode", "r") as f:
    gcode_content = f.read()

# Parse G-code
commands = GCodeParser.parse(gcode_content)

# Extract layers
layers = LayerExtractor.extract_layers(commands)

# Get top layer
top_layer = TopSurfaceDetector.get_top_layer(layers)

# Extract surface points
surface_points = TopSurfaceDetector.extract_surface_moves(top_layer)

# Create configuration
config = IroningConfig(
    enabled=True,
    mode=IroningMode.LIGHT_FLOW,
    flow_rate=0.5,
    speed=30.0,
    pattern_spacing=1.0,
)

# Generate ironing paths
ironing_moves = IroningPathGenerator.generate_ironing_moves(
    surface_points=surface_points,
    config=config
)

# Convert to G-code string
ironing_gcode = "\n".join(move.to_gcode() for move in ironing_moves)

# Append to original G-code (just before M104/M84 commands)
# ...
```

### Creating Output G-code

```python
# Generate ironing moves
ironing_moves = IroningPathGenerator.generate_ironing_moves(points, config)

# Convert to string
gcode_lines = [move.to_gcode() for move in ironing_moves]
ironing_gcode = "\n".join(gcode_lines)

# Optionally write to file
with open("ironing.gcode", "w") as f:
    f.write(ironing_gcode)
```

## Configuration Examples

### Standard PLA Ironing (50% flow, 30 mm/s)
```python
pla_config = IroningConfig(
    enabled=True,
    mode=IroningMode.LIGHT_FLOW,
    flow_rate=0.5,
    speed=30.0,
    pattern_spacing=1.0,
)
```

### Aggressive Ironing (no extrusion, smooth surface)
```python
aggressive_config = IroningConfig(
    enabled=True,
    mode=IroningMode.NO_EXTRUSION,
    flow_rate=0.0,
    speed=20.0,
    z_offset=0.05,  # Slight pressure
    pattern_spacing=0.8,
)
```

### Fine Detail Ironing (slower, more control)
```python
detail_config = IroningConfig(
    enabled=True,
    mode=IroningMode.MEDIUM_FLOW,
    flow_rate=0.6,
    speed=15.0,
    pattern_spacing=0.5,
    z_offset=-0.1,  # Slightly lower for better contact
)
```

## Testing

The module includes comprehensive unit tests in `tests/test_ironing_paths.py`:

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/test_ironing_paths.py -v
```

**Test Coverage:**
- Point3D distance calculations
- G-code command parsing and generation
- Layer extraction
- Top surface detection
- Configuration serialization
- Ironing path generation
- Path validation
- Integration tests with three reference models

**Reference Models:**
1. **Simple Square (100×100mm)**: Basic rectangular print
2. **Complex Circle (80mm diameter)**: Curved surface paths
3. **Tiny Detail (10×10mm)**: Small precision features

### Verification Script

Run the verification script to test all three reference models:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. python tests/verify_ironing_paths.py
```

This generates ironing paths for each model and validates output.

## Performance Considerations

- **Memory**: Each path point stores X, Y, Z, E coordinates (minimal overhead)
- **Speed**: Parsing and generation are linear O(n) in number of commands
- **Typical timings**:
  - Parse 1000 lines: ~5ms
  - Extract layers: ~2ms
  - Generate ironing paths: ~10ms

## Integration with MEMAR

To integrate ironing path generation into MEMAR's Klipper/Moonraker workflow:

1. **File Upload**: User uploads G-code via frontend
2. **Analysis**: Parse and extract top surface
3. **Configuration**: Provide UI for ironing settings
4. **Generation**: Generate ironing paths
5. **Download**: Append ironing moves to original G-code
6. **Printing**: Upload modified G-code to printer

### Backend API Endpoint (Future)

```python
@app.post("/api/gcode/ironing")
async def generate_ironing(request: IroningRequest) -> IroningResponse:
    """Generate ironing paths for uploaded G-code."""
    commands = GCodeParser.parse(request.gcode_content)
    layers = LayerExtractor.extract_layers(commands)
    top_layer = TopSurfaceDetector.get_top_layer(layers)
    points = TopSurfaceDetector.extract_surface_moves(top_layer)
    
    config = IroningConfig.from_dict(request.config)
    ironing_moves = IroningPathGenerator.generate_ironing_moves(points, config)
    
    return IroningResponse(
        ironing_gcode="\n".join(m.to_gcode() for m in ironing_moves),
        validation=IroningPathValidator.validate_paths(ironing_moves, points),
    )
```

## Known Limitations

1. **Rectangular patterns only**: Currently generates parallel rectangular ironing lines
   - Future: Support circular/custom patterns
2. **Single layer ironing**: Only irons the topmost layer
   - Future: Support ironing multiple top layers
3. **No adaptive spacing**: Pattern spacing is uniform
   - Future: Adaptive spacing based on surface geometry
4. **Basic extrusion calculation**: E values are simplified
   - Future: Accurate flow rate calculation based on nozzle diameter

## Future Enhancements

- [ ] Support for multiple ironing layers (top N layers)
- [ ] Circular ironing pattern
- [ ] Spiral ironing pattern (outside-in or inside-out)
- [ ] Adaptive line spacing based on surface complexity
- [ ] Extrusion width-based flow compensation
- [ ] Temperature adjustment during ironing
- [ ] Fan speed adjustment
- [ ] Backward compatibility with other slicers (Cura, Simplify3D)
- [ ] CLI tool for batch G-code processing
- [ ] Web UI for configuration and preview

## References

- Marlin G-code Reference: https://marlin.fandom.com/wiki/G-code
- Klipper G-code Documentation: https://www.klipper3d.org/
- 3D Print Surface Quality Research: Ironing effects on layer adhesion and finish

## License

Part of MEMAR project. See LICENSE file in repository root.
