# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2025-10-30

### Changed
- **BREAKING**: Changed default transport from SSE to stdio. Now `--sse` flag is required for SSE transport instead of `--stdio` for stdio transport
- Updated documentation to reflect stdio as the default transport method

## [0.2.0] - 2025-10-30

### Changed
- **BREAKING**: Migrated from pip to [uv](https://docs.astral.sh/uv/) package manager
- **BREAKING**: Updated minimum Python version from 3.9 to 3.10
- Updated all development dependencies to latest versions:
  - pytest: 7.0.0 → 8.3.0
  - pytest-asyncio: 0.21.0 → 0.24.0
  - ruff: 0.1.0 → 0.8.0
  - mypy: 1.0.0 → 1.13.0
- Simplified dependency management with `uv sync` workflow
- Updated all documentation to use uv commands instead of pip/venv
- Updated pyproject.toml with uv-specific configuration sections

### Added
- `[tool.uv]` configuration section in pyproject.toml
- `[tool.uv.sources]` section for potential future dependency overrides
- Comprehensive uv usage instructions throughout README.md

### Removed
- Removed Python 3.9 support (now requires Python 3.10+)

## [0.1.0] - 2024

### Added
- Comprehensive docstrings for all functions and classes
- Type hints using modern Python syntax (list, dict instead of List, Dict)
- `set_color_temperature` tool for controlling white light temperature (2000K-6500K)
- Development dependencies in pyproject.toml (pytest, ruff, mypy)
- MIT License file
- CONTRIBUTING.md with development guidelines
- Basic test suite with pytest
- CHANGELOG.md for tracking changes

### Changed
- Updated Python version requirement from 3.13+ to 3.9+ for better compatibility
- Enhanced README with current MCP SDK best practices
- Improved `rgb_to_xy` function with better gamma correction and documentation
- Updated pyproject.toml with comprehensive project metadata
- Better error messages throughout the codebase
- Modernized all type hints to use built-in types

### Fixed
- Missing `set_color_temperature` tool that was documented in README
- Import ordering and code formatting issues
- Type hint inconsistencies

### Documentation
- Updated README with uv installation instructions
- Clarified MCP Inspector usage vs direct execution
- Added more detailed Quick Start guide
- Enhanced API reference with better examples

## [0.1.0] - 2024

### Added
- Initial release
- MCP server implementation for Philips Hue
- Support for light control (on/off, brightness, color, effects)
- Group management
- Scene handling
- Activity-based presets
- Natural language prompts for light control
- Automatic bridge discovery and authentication
- Configuration persistence in ~/.hue-mcp/config.json
