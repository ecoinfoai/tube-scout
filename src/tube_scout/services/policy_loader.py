"""Policy loader service for spec 011 layer-defense configuration.

Reads project-level policy.yaml and validates it into a PolicyConfig model.
All validation errors include actionable English messages.
"""

from pathlib import Path

import yaml

from tube_scout.models.reuse_v2 import PolicyConfig

_POLICY_RELATIVE_PATH = Path("02_analyze") / "content" / "policy.yaml"


def load_policy(project_dir: Path) -> PolicyConfig:
    """Read and validate the project policy YAML file.

    Looks for ``02_analyze/content/policy.yaml`` relative to ``project_dir``.
    Delegates field-level validation (composite_weights sum, band bounds,
    threshold ranges) to the PolicyConfig Pydantic model.

    Args:
        project_dir: Root directory of the tube-scout project job.

    Returns:
        Validated PolicyConfig instance with all thresholds and weights.

    Raises:
        TypeError: If project_dir is not a Path.
        FileNotFoundError: If the policy file does not exist, with a message
            pointing to the CLI recovery command.
        ValueError: If any policy value is out of valid range (propagated
            from PolicyConfig validators).
    """
    if not isinstance(project_dir, Path):
        raise TypeError(
            f"project_dir must be a Path, got {type(project_dir).__name__}"
        )

    policy_path = project_dir / _POLICY_RELATIVE_PATH
    if not policy_path.exists():
        raise FileNotFoundError(
            f"Policy file not found: {policy_path}. "
            "Generate a default policy with: "
            "tube-scout content policy show > policy.yaml"
        )

    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}

    # Normalise layer_c_evolution_band from list → tuple for Pydantic
    if "layer_c_evolution_band" in raw and isinstance(
        raw["layer_c_evolution_band"], list
    ):
        raw["layer_c_evolution_band"] = tuple(raw["layer_c_evolution_band"])

    try:
        return PolicyConfig(**raw)
    except Exception as exc:
        raise ValueError(
            f"Invalid policy configuration in {policy_path}: {exc}"
        ) from exc
