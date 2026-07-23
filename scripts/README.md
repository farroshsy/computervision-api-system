# Project Management Tools

This directory contains tools to help manage and track the progress of the OCR API project.

## Available Tools

### 1. Test API Script (`test_api.py`)
Run tests against the OCR API using real KTP images.

**Usage:**
```bash
# Run all tests
python3 scripts/test_api.py

# Test a specific image
curl -X POST http://localhost:8000/api/v1/ocr/ktp \
  -H "Content-Type: multipart/form-data" \
  -F "file=@test_images/ktp/sample_ktp.jpg"
```

### 2. Progress Tracker (`track_progress.py`)
Track and visualize project progress across all milestones.

**Usage:**
```bash
# Update progress and show report
python3 scripts/track_progress.py
```

### 3. Project Management (`PROJECT_MANAGEMENT.md`)
Overview of project status, current tasks, and next steps.

## Directory Structure

```
scripts/
├── test_api.py          # Test OCR API with real images
├── track_progress.py    # Track project progress
└── README.md            # This file

test_images/            # Directory for test images
└── ktp/                # KTP test images
    ├── sample1.jpg
    └── sample2.jpg
```

## Adding Test Images
1. Place KTP images in the `test_images/ktp/` directory
2. Supported formats: JPG, JPEG, PNG
3. Naming convention: `ktp_<description>.<ext>` (e.g., `ktp_sample1.jpg`)

## Viewing Results
Test results are saved to `test_results.json` and progress is tracked in `project_progress.json`.

## CI/CD Integration
Add this to your CI/CD pipeline to automatically track progress:

```yaml
# .github/workflows/test.yml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run tests
        run: python scripts/test_api.py
      - name: Update progress
        run: python scripts/track_progress.py
```
