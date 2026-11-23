from __future__ import annotations

from pydantic import BaseModel, Field

from core.policy import check_patch
from core.sandbox import DockerSandbox, SandboxResult


class VerificationReport(BaseModel):
    policy_ok: bool = False
    reproduced_before: bool = False
    repro_passes_after: bool = False
    regression_green: bool = False
    verified: bool = False
    failure_reason: str = ""
    steps: dict[str, SandboxResult] = Field(default_factory=dict)


def verify_patch(sandbox: DockerSandbox, repo_path: str, *, repro_name: str,
                 repro_source: str, patch: str,
                 regression_targets: list[str] | None = None,
                 timeout_s: int | None = None) -> VerificationReport:
    report = VerificationReport()
    policy = check_patch(patch, sandbox.settings)
    if not policy.ok:
        report.failure_reason = "policy: " + "; ".join(policy.violations)
        return report
    report.policy_ok = True
    files = {repro_name: repro_source}
    before = sandbox.run_pytest(repo_path, [repro_name], files=files, timeout_s=timeout_s)
    report.steps["repro_before"] = before
    if before.status != "failed":
        report.failure_reason = f"repro did not fail on unpatched code (status={before.status})"
        return report
    report.reproduced_before = True
    after = sandbox.run_pytest(repo_path, [repro_name], files=files, patch=patch, timeout_s=timeout_s)
    report.steps["repro_after"] = after
    if not after.passed:
        report.failure_reason = f"repro did not pass with patch (status={after.status}; {after.detail})"
        return report
    report.repro_passes_after = True
    regression = sandbox.run_pytest(repo_path, regression_targets, files=files, patch=patch,
                                    timeout_s=timeout_s)
    report.steps["regression"] = regression
    if not regression.passed:
        report.failure_reason = f"regression suite did not pass (status={regression.status})"
        return report
    report.regression_green = True
    report.verified = True
    return report
