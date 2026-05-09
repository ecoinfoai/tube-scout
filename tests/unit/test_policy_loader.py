"""Unit tests for policy_loader service (T009 RED).

Tests validate that load_policy correctly loads policy.yaml, rejects
invalid configurations with actionable English messages, and fails fast
on missing files.
"""

import textwrap
from pathlib import Path

import pytest

from tube_scout.services.policy_loader import load_policy


def _write_policy(tmp_path: Path, content: str) -> Path:
    project_dir = tmp_path / "project"
    analyze_dir = project_dir / "02_analyze" / "content"
    analyze_dir.mkdir(parents=True)
    (analyze_dir / "policy.yaml").write_text(textwrap.dedent(content))
    return project_dir


_VALID_YAML = """\
    layer_a_min_seconds: 60
    layer_c_evolution_band: [0.60, 0.75]
    matching_cosine_cull: 0.55
    pattern_whole_threshold_ratio: 0.50
    composite_weights:
      i1: 0.20
      i2: 0.20
      i3: 0.10
      i4: 0.05
      i5: 0.05
      i6: 0.20
      i7: 0.10
      i8: 0.10
"""


def test_load_valid_yaml(tmp_path: Path) -> None:
    """load_policy returns a PolicyConfig with correct field values."""
    project_dir = _write_policy(tmp_path, _VALID_YAML)
    policy = load_policy(project_dir)
    assert policy.layer_a_min_seconds == 60.0
    assert policy.layer_c_evolution_band == (0.60, 0.75)
    assert policy.matching_cosine_cull == 0.55
    assert policy.pattern_whole_threshold_ratio == 0.50
    assert abs(sum(policy.composite_weights.values()) - 1.0) < 0.01


def test_missing_file_actionable_message(tmp_path: Path) -> None:
    """FileNotFoundError message points to the CLI recovery command."""
    empty_project = tmp_path / "empty_project"
    empty_project.mkdir()
    with pytest.raises(FileNotFoundError) as exc_info:
        load_policy(empty_project)
    assert "tube-scout content policy show > policy.yaml" in str(exc_info.value)


def test_invalid_composite_weights_sum(tmp_path: Path) -> None:
    """ValueError is raised when composite_weights deviate from 1.0 by >0.01."""
    yaml = """\
        layer_a_min_seconds: 60
        layer_c_evolution_band: [0.60, 0.75]
        matching_cosine_cull: 0.55
        pattern_whole_threshold_ratio: 0.50
        composite_weights:
          i1: 0.20
          i2: 0.20
          i3: 0.10
          i4: 0.05
          i5: 0.05
          i6: 0.20
          i7: 0.10
          i8: 0.05
    """
    project_dir = _write_policy(tmp_path, yaml)
    with pytest.raises(ValueError) as exc_info:
        load_policy(project_dir)
    msg = str(exc_info.value)
    assert "composite_weights" in msg
    assert "1.0" in msg


def test_invalid_evolution_band(tmp_path: Path) -> None:
    """ValueError is raised when layer_c_evolution_band violates 0 <= low < high <= 1."""
    yaml = """\
        layer_a_min_seconds: 60
        layer_c_evolution_band: [0.80, 0.60]
        matching_cosine_cull: 0.55
        pattern_whole_threshold_ratio: 0.50
        composite_weights:
          i1: 0.20
          i2: 0.20
          i3: 0.10
          i4: 0.05
          i5: 0.05
          i6: 0.20
          i7: 0.10
          i8: 0.10
    """
    project_dir = _write_policy(tmp_path, yaml)
    with pytest.raises(ValueError) as exc_info:
        load_policy(project_dir)
    assert "layer_c_evolution_band" in str(exc_info.value)


def test_negative_layer_a_threshold(tmp_path: Path) -> None:
    """ValueError is raised when layer_a_min_seconds <= 0."""
    yaml = """\
        layer_a_min_seconds: -1
        layer_c_evolution_band: [0.60, 0.75]
        matching_cosine_cull: 0.55
        pattern_whole_threshold_ratio: 0.50
        composite_weights:
          i1: 0.20
          i2: 0.20
          i3: 0.10
          i4: 0.05
          i5: 0.05
          i6: 0.20
          i7: 0.10
          i8: 0.10
    """
    project_dir = _write_policy(tmp_path, yaml)
    with pytest.raises(ValueError):
        load_policy(project_dir)


def test_invalid_pattern_ratio(tmp_path: Path) -> None:
    """ValueError is raised when pattern_whole_threshold_ratio is outside (0, 1)."""
    yaml = """\
        layer_a_min_seconds: 60
        layer_c_evolution_band: [0.60, 0.75]
        matching_cosine_cull: 0.55
        pattern_whole_threshold_ratio: 1.5
        composite_weights:
          i1: 0.20
          i2: 0.20
          i3: 0.10
          i4: 0.05
          i5: 0.05
          i6: 0.20
          i7: 0.10
          i8: 0.10
    """
    project_dir = _write_policy(tmp_path, yaml)
    with pytest.raises(ValueError):
        load_policy(project_dir)
