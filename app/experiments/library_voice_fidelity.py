"""Runtime ECAPA speaker comparison used by the voice-drift check."""
import json
import os
import subprocess

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ecapa_pairs(pairs, python_bin, timeout=3600):
    """Speaker-embedding cosine, run under the interpreter that has
    speechbrain. Never falls back to an acoustic distance: a silent
    substitution of a different metric is the failure mode this whole
    investigation keeps rediscovering."""
    if not pairs or not python_bin or not os.path.exists(python_bin):
        return [None] * len(pairs), "no speechbrain interpreter"
    script = os.path.join(APP, "experiments", "_ecapa_batch.py")
    if not os.path.exists(script):
        return [None] * len(pairs), "_ecapa_batch.py missing"
    # Contract is STDIN and cwd=APP, per its own docstring. The first version
    # here passed a temp-file path as argv and got an unparsable-output error
    # that looked like a speechbrain problem.
    #
    # ABSOLUTE PATHS, BECAUSE THIS CALL CHANGES DIRECTORY. cwd=APP means every
    # relative path the caller handed us is now resolved against app/ instead
    # of wherever the caller was standing. On 2026-08-18 the re-gate chain
    # passed --dataset ab_test_runtime/decontaminate/... from the repo root and
    # all 67 adapters failed identically:
    #
    #     NOT MEASURED: rc=3 opening '.../val/sample_3063.wav': System error
    #     every one of 6 pairs failed - check the paths
    #
    # The clips were present and readable the whole time; app/ab_test_runtime/
    # is what did not exist. Two hours of GPU time produced no measurement, and
    # the advice printed - "check the paths" - pointed at the datasets rather
    # than at the directory this line changes. Whoever crosses a cwd boundary
    # owns the conversion.
    #
    # A DOCUMENTED TRAP, not an exotic one: python's tracker has carried the
    # cwd/relative-path discrepancy since issue 15533 (POSIX and Windows
    # resolve differently), and the standing advice in the subprocess docs and
    # every write-up since is the same - pass absolute paths, because `cwd`
    # changes where the CHILD resolves names without changing what the relative
    # strings you already built mean.
    pairs = [[os.path.abspath(a), os.path.abspath(b)] for a, b in pairs]
    try:
        out = subprocess.run([python_bin, script],
                             input=json.dumps([[a, b] for a, b in pairs]),
                             capture_output=True, text=True, timeout=timeout,
                             cwd=APP)
        if out.returncode != 0:
            return [None] * len(pairs), f"rc={out.returncode} {out.stderr[-160:]}"
        return json.loads(out.stdout.strip().splitlines()[-1]), None
    except Exception as exc:                                # noqa: BLE001
        return [None] * len(pairs), str(exc)[:140]
