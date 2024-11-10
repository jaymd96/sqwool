# Makefile

.PHONY: help install lint format test pre-commit install-hooks build publish clean

SRC_DIRS = sqwool/ tests/

# Default target
help:
	@echo "Available commands:"
	@echo "  install           Install runtime dependencies"
	@echo "  install-dev       Install development dependencies"
	@echo "  install-hooks     Install pre-commit hooks"
	@echo "  lint              Run linter (flake8)"
	@echo "  format            Format code with black and isort"
	@echo "  test              Run tests with pytest"
	@echo "  build             Build the package"
	@echo "  publish           Publish the package to PyPI"
	@echo "  clean             Clean build artifacts"

install:
	pip install -r requirements.txt

install-dev:
	pip install -r dev-requirements.txt

install-hooks:
	pre-commit install

# Target to run ruff linting
lint:
	ruff check $(SRC_DIRS)

# Target to automatically fix issues
lint-fix:
	ruff check $(SRC_DIRS) --fix

# Target to run all linting and formatting checks
format:
	black $(SRC_DIRS)
	isort $(SRC_DIRS)
	ruff check $(SRC_DIRS)
test:
	pytest

build:
	python setup.py sdist bdist_wheel

publish: build
	twine upload dist/*

publish-test: build
	twine upload dist/*

clean:
	rm -rf build/ dist/ *.egg-info
