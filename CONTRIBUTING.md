# Contributing to Hue MCP Server

Thank you for your interest in contributing to the Philips Hue MCP Server! This document provides guidelines and instructions for contributing.

## Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/ThomasRohde/hue-mcp.git
   cd hue-mcp
   ```

2. **Set up your development environment:**
   
   Using uv (recommended):
   ```bash
   uv sync
   # Activate virtual environment (optional, uv run handles this automatically)
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
   
   Or using pip:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```

3. **Set up your Hue bridge:**
   - Ensure your Hue bridge is on your local network
   - Press the link button when prompted during first run

## Development Workflow

1. **Create a new branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes:**
   - Write clear, concise code
   - Follow the existing code style
   - Add docstrings to all functions and classes
   - Use type hints for all function parameters and return values

3. **Test your changes:**
   ```bash
   # Test with MCP Inspector
   uv run mcp dev hue_server.py
   
   # Run tests
   uv run pytest
   ```

4. **Check code quality:**
   ```bash
   # Format with ruff
   uv run ruff check --fix hue_server.py
   
   # Type check with mypy
   uv run mypy hue_server.py
   ```

## Code Style Guidelines

- **Python Version:** Target Python 3.10+ for maximum compatibility
- **Type Hints:** Use modern Python type hints (e.g., `list[int]` instead of `List[int]`)
- **Docstrings:** Use Google-style docstrings with Args, Returns, and Examples sections
- **Line Length:** Keep lines under 100 characters
- **Imports:** Group imports in the following order:
  1. Standard library
  2. Third-party packages
  3. Local modules
- **Error Handling:** Provide informative error messages

## Testing

- Write tests for new features and bug fixes
- Ensure all tests pass before submitting a PR
- Include both unit tests and integration tests where appropriate

## Documentation

- Update the README.md if you add new features
- Add docstrings to all new functions and classes
- Include usage examples for new tools or resources

## Pull Request Process

1. **Update documentation:** Ensure README and docstrings are up-to-date
2. **Run tests:** Make sure all tests pass
3. **Update CHANGELOG:** Add your changes to the unreleased section
4. **Create PR:** Submit a pull request with a clear title and description
5. **Address feedback:** Respond to review comments promptly

## Pull Request Guidelines

- **Title:** Use a clear, descriptive title
- **Description:** Explain what changes you made and why
- **Reference Issues:** Link to any related issues
- **Keep it focused:** One feature or fix per PR
- **Small commits:** Make small, logical commits with clear messages

## Bug Reports

When reporting bugs, please include:

- **Description:** Clear description of the bug
- **Steps to Reproduce:** Step-by-step instructions
- **Expected Behavior:** What you expected to happen
- **Actual Behavior:** What actually happened
- **Environment:** Python version, OS, Hue bridge model
- **Logs:** Relevant error messages or logs

## Feature Requests

When requesting features, please include:

- **Use Case:** Why you need this feature
- **Proposed Solution:** How you envision it working
- **Alternatives:** Other solutions you've considered
- **Examples:** Similar features in other tools

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Assume good intentions

## Questions?

If you have questions about contributing, feel free to:
- Open an issue for discussion
- Reach out to the maintainers
- Check existing issues and PRs for similar questions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
