"""The CI workflows, and the Gopher probe they rely on.

Three workflows failed on every run for months: two because a secret or a
repository setting they need was never configured, and one because it treated
"the node I monitor is down" as its own failure. A workflow that is red for a
reason nobody is acting on stops being read at all, so each of them now
reports the condition and stops cleanly.

These tests pin that behaviour, and exercise the probe script the workflows
call — it replaced a netcat invocation whose flags only one of the two jobs
had actually installed.
"""

import importlib.util
import json
import socket
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PROBE = ROOT / ".github" / "scripts" / "pillar_probe.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("pillar_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    """YAML 1.1 reads the `on:` key as the boolean True."""
    return wf.get("on", wf.get(True))


# ---------------------------------------------------------------------------
# A stand-in Gopher server. Nothing here needs the Pillar itself — the point
# is that the probe survives whatever it is pointed at, including nothing.
# ---------------------------------------------------------------------------

class _FakeGopher:
    def __init__(self, responses):
        self.responses = responses
        # Bind the loopback address explicitly: a wildcard bind can be
        # answered by an unrelated local listener.
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.host, self.port = self._sock.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._running = True
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2)
                    selector = conn.recv(4096).decode("utf-8", "replace").strip()
                    conn.sendall(self.responses.get(selector, b""))
                except OSError:
                    pass

    def close(self):
        self._running = False
        self._sock.close()


# Since 0.5.0 a Pillar appends a signature block to every answer. Anything
# that parses a response has to look past it — the old health workflow did
# not, so its JSON step would have failed against a live node as surely as
# against a dead one.
SIGNATURE_TRAILER = (
    b"---BEGIN REFINET SIGNATURE---\r\n"
    b"pid:" + b"d1" * 32 + b"\r\n"
    b"pubkey:" + b"aa" * 32 + b"\r\n"
    b"sig:" + b"48" * 64 + b"\r\n"
    b"hash:" + b"64" * 32 + b"\r\n"
    b"v:1\r\nselector:/health/services\r\ntime:1789842715\r\n"
    b"sig1:" + b"ed" * 64 + b"\r\n"
    b"---END REFINET SIGNATURE---\r\n"
)

ROOT_MENU = (
    b"iREFInet Pillar \xe2\x80\x94 sovereign infrastructure\t\terror.host\t1\r\n"
    b"1Services\t/services\tlocalhost\t7070\r\n.\r\n"
) + SIGNATURE_TRAILER

SERVICES = json.dumps([
    {"name": "rpc", "available": True},
    {"name": "vault", "available": False},
], indent=2).encode() + b"\r\n.\r\n" + SIGNATURE_TRAILER


@pytest.fixture
def pillar():
    server = _FakeGopher({"": ROOT_MENU, "/health/services": SERVICES})
    yield server
    server.close()


@pytest.fixture
def dead_port():
    """A port nobody is listening on."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


class TestProbe:
    def test_online_when_the_pillar_answers(self, pillar, capsys):
        assert probe.main(["online", pillar.host, str(pillar.port)]) == 0
        assert "online" in capsys.readouterr().out

    def test_offline_is_reported_not_raised(self, dead_port, capsys):
        """An unreachable host is an answer, not a crash."""
        assert probe.main(["online", "127.0.0.1", str(dead_port)]) == 1
        assert "offline" in capsys.readouterr().out

    def test_a_stranger_on_the_port_is_not_a_pillar(self, capsys):
        server = _FakeGopher({"": b"220 smtp ready\r\n"})
        try:
            assert probe.main(["online", server.host, str(server.port)]) == 1
        finally:
            server.close()

    def test_retries_are_bounded(self, dead_port):
        rc = probe.main(["online", "127.0.0.1", str(dead_port),
                         "--retries", "3", "--delay", "0"])
        assert rc == 1

    def test_menu_is_truncated_to_the_line_budget(self, pillar, capsys):
        assert probe.main(["menu", pillar.host, str(pillar.port), "--lines", "1"]) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 1

    def test_services_summarises_availability(self, pillar, capsys):
        assert probe.main(["services", pillar.host, str(pillar.port)]) == 0
        out = capsys.readouterr().out
        assert "Services: 1/2 available" in out
        assert "rpc" in out and "vault" in out

    def test_services_on_a_silent_host_fails_without_a_traceback(self, dead_port, capsys):
        assert probe.main(["services", "127.0.0.1", str(dead_port)]) == 1
        assert "No answer" in capsys.readouterr().err

    def test_the_signature_trailer_is_not_part_of_the_payload(self):
        """A signed response is still JSON once its envelope is removed."""
        assert json.loads(probe.body_of(SERVICES))[0]["name"] == "rpc"
        assert "REFINET SIGNATURE" not in probe.body_of(ROOT_MENU)

    def test_an_unsigned_response_still_parses(self):
        """Envelope stripping must not depend on the trailer being there."""
        assert json.loads(probe.body_of(b'[{"name":"rpc"}]\r\n.\r\n')) == [
            {"name": "rpc"}]

    def test_menu_shows_content_not_the_signature_block(self, pillar, capsys):
        assert probe.main(["menu", pillar.host, str(pillar.port)]) == 0
        assert "REFINET SIGNATURE" not in capsys.readouterr().out

    def test_probe_imports_nothing_outside_the_standard_library(self):
        """The workflows that call it install no dependencies."""
        source = PROBE.read_text(encoding="utf-8")
        imports = {line.split()[1].split(".")[0]
                   for line in source.splitlines()
                   if line.startswith("import ")}
        assert imports <= {"argparse", "json", "socket", "sys", "time"}


class TestWorkflowsParse:
    def test_every_workflow_is_valid_yaml(self):
        files = sorted(WORKFLOWS.glob("*.yml"))
        assert len(files) >= 5
        for path in files:
            assert yaml.safe_load(path.read_text(encoding="utf-8")), path.name

    def test_no_workflow_depends_on_a_netcat_flavour(self):
        """`nc -q` is netcat-openbsd only, and one job never installed it."""
        for path in WORKFLOWS.glob("*.yml"):
            assert "nc -q" not in path.read_text(encoding="utf-8"), path.name

    def test_every_job_that_runs_pytest_installs_the_test_extra(self):
        """requirements.txt does not carry pytest-timeout or pyyaml.

        Three workflows run the suite. A job that installs only
        requirements.txt fails at collection the moment a test needs
        anything from the `test` extra — which is how the release workflow
        would have broken on the first v* tag.
        """
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for job_name, job in (_workflow(path.name)["jobs"]).items():
                runs = " ".join(s.get("run", "") for s in job.get("steps", []))
                if "pytest tests/" not in runs:
                    continue
                assert "[test]" in runs, (
                    f"{path.name}:{job_name} runs the suite without "
                    f"installing the test extra")

    def test_referenced_scripts_exist(self):
        for path in WORKFLOWS.glob("*.yml"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if ".github/scripts/" in line:
                    ref = line.split(".github/scripts/")[1].split()[0].strip("\"'\\")
                    assert (ROOT / ".github" / "scripts" / ref).exists(), line


class TestDeployIsGatedOnItsSecret:
    def test_deploy_runs_only_when_a_token_is_configured(self):
        jobs = _workflow("deploy.yml")["jobs"]
        assert "preflight" in jobs
        for name in ("test", "deploy"):
            assert "preflight" in jobs[name]["needs"]
            assert jobs[name]["if"] == "needs.preflight.outputs.deploy == 'true'"

    def test_preflight_decides_from_the_secret_itself(self):
        """`secrets` is unreadable from a job-level `if:`, hence the output."""
        preflight = _workflow("deploy.yml")["jobs"]["preflight"]
        step = preflight["steps"][0]
        assert "FLY_API_TOKEN" in step["env"]
        assert "deploy=false" in step["run"] and "deploy=true" in step["run"]
        assert preflight["outputs"]["deploy"]

    def test_a_missing_token_is_a_notice_not_an_error(self):
        run = _workflow("deploy.yml")["jobs"]["preflight"]["steps"][0]["run"]
        assert "::notice" in run and "::error" not in run

    def test_secrets_are_passed_through_the_environment(self):
        """Interpolating a secret into a quoted shell word lets it break out."""
        text = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
        assert "REFINET_PID_JSON='${{" not in text


class TestWebsiteIsGatedOnPages:
    def test_deploy_runs_only_when_pages_is_enabled(self):
        jobs = _workflow("pages.yml")["jobs"]
        assert jobs["deploy"]["if"] == "needs.preflight.outputs.enabled == 'true'"
        assert jobs["preflight"]["permissions"]["pages"] == "read"

    def test_the_notice_names_the_netlify_alternative(self):
        run = _workflow("pages.yml")["jobs"]["preflight"]["steps"][0]["run"]
        assert "::notice" in run and "Netlify" in run


class TestHealthReportsRatherThanFails:
    def test_an_offline_pillar_does_not_fail_the_run(self):
        """Both fetch steps are skipped when the probe says offline."""
        steps = _workflow("health.yml")["jobs"]["check"]["steps"]
        fetches = [s for s in steps if s.get("name", "").startswith("Fetch")]
        assert len(fetches) == 2
        for step in fetches:
            assert step["if"] == "steps.probe.outputs.status == 'online'"

    def test_the_badge_is_written_either_way(self):
        steps = _workflow("health.yml")["jobs"]["check"]["steps"]
        badge = next(s for s in steps if s.get("name") == "Write status badge")
        assert "if" not in badge

    def test_the_badge_commit_has_write_permission(self):
        assert _workflow("health.yml")["permissions"]["contents"] == "write"

    def test_the_probed_host_is_configurable(self):
        for name in ("health.yml", "deploy.yml"):
            env = _workflow(name)["env"]
            assert "vars.PILLAR_HOST" in env["PILLAR_HOST"]
            assert "gopher.refinet.io" in env["PILLAR_HOST"]

    def test_the_schedule_is_intact(self):
        triggers = _triggers(_workflow("health.yml"))
        assert triggers["schedule"][0]["cron"] == "*/15 * * * *"
        assert "workflow_dispatch" in triggers
