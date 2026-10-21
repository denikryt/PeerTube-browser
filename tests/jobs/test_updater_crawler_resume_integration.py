"""Exercise Updater resume against real Node crawler CLIs and a fake PeerTube edge."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from engine.server.db.jobs.updater import pipeline, staging
from tests.jobs.test_updater_pipeline_commands import _args, _patch_lightweight


def test_interrupted_listing_resumes_real_crawler_without_reprobing_finished_hosts(
    monkeypatch, tmp_path: Path
) -> None:
    """A saved page and sibling host survive a failed CLI, then only unfinished work is requested."""
    crawler = Path(__file__).resolve().parents[2] / "engine" / "crawler"
    if not (crawler / "node_modules/typescript/bin/tsc").exists():
        pytest.skip("Crawler Node dependencies are not installed")
    # Compile the production CLIs into this test's own directory. Neither the
    # running service artifacts nor the shared test compilation are rewritten.
    cli_dir = tmp_path / "crawler-cli"
    cli_dir.mkdir()
    subprocess.run(
        ["node", "node_modules/typescript/bin/tsc", "-p", "tsconfig.json",
         "--outDir", str(cli_dir / "dist")],
        cwd=crawler, check=True, capture_output=True, text=True,
    )
    (cli_dir / "schema.sql").symlink_to(crawler / "schema.sql")
    (cli_dir / "node_modules").symlink_to(crawler / "node_modules", target_is_directory=True)
    (cli_dir / "package.json").write_text('{"type":"module"}')
    network_log = tmp_path / "requests.jsonl"
    stub = tmp_path / "fake-peertube.mjs"
    stub.write_text("""
import fs from 'node:fs';
globalThis.fetch = async input => {
  const url = new URL(String(input));
  fs.appendFileSync(process.env.PTB_REQUEST_LOG, JSON.stringify({
    host: url.hostname, path: url.pathname,
    start: url.searchParams.get('start'), count: url.searchParams.get('count')
  }) + '\\n');
  const host = url.hostname;
  const count = url.searchParams.get('count');
  const start = url.searchParams.get('start');
  if (count === '1') return new Response('{"total":0,"data":[]}');
  if (url.pathname === '/api/v1/video-channels' && host === 'b.example')
    return new Response(JSON.stringify({total:1,data:[{id:'b1',name:'b1',host,videosCount:0}]}));
  if (url.pathname === '/api/v1/video-channels' && host === 'a.example') {
    if (start === '50' && process.env.PTB_PHASE === 'first')
      throw Object.assign(new Error('local network interrupted'), {code:'NO_NETWORK'});
    const data = start === '0'
      ? Array.from({length:50}, (_, i) => ({id:String(i),name:`c${i}`,host,videosCount:0}))
      : [{id:'50',name:'c50',host,videosCount:0}];
    return new Response(JSON.stringify({total:51,data}));
  }
  throw new Error('Unexpected PeerTube request: ' + url);
};
""", encoding="utf-8")

    _patch_lightweight(monkeypatch)
    monkeypatch.setattr(pipeline, "init_staging_db", staging.init_staging_db)
    monkeypatch.setattr(pipeline, "list_staging_hosts", staging.list_staging_hosts)
    args = _args(tmp_path, resume_staging=False, skip_systemctl=True,
                 crawler_dir=str(cli_dir), host_delay_ms=0, timeout_ms=100,
                 max_retries=0, concurrency=1, host_concurrency=1)
    with sqlite3.connect(args.prod_db) as conn:
        conn.executescript((crawler / "schema.sql").read_text(encoding="utf-8"))
    stage_path = Path(args.staging_db)
    phase = "first"

    def run_real_crawler(cmd, cwd):
        """Run real crawler CLIs while replacing only registry and later heavy jobs."""
        if cmd[0] != "node":
            return
        if cmd[1].endswith("instances-cli.js"):
            with sqlite3.connect(stage_path) as conn:
                conn.executemany("INSERT INTO instances(host) VALUES (?)",
                                 [("a.example",), ("b.example",)])
            return
        result = subprocess.run(
            ["node", "--import", str(stub), *cmd[1:]], cwd=cwd,
            env={**os.environ, "PTB_PHASE": phase, "PTB_REQUEST_LOG": str(network_log)},
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )

    with pytest.raises(subprocess.CalledProcessError):
        pipeline.run_pipeline(args, command_runner=run_real_crawler, validate_files=False)
    with sqlite3.connect(stage_path) as conn:
        assert conn.execute(
            "SELECT instance_domain,status FROM channel_crawl_progress ORDER BY instance_domain"
        ).fetchall() == [("a.example", "in_progress"), ("b.example", "done")]
        assert conn.execute("SELECT COUNT(*) FROM channels WHERE instance_domain='a.example'").fetchone()[0] == 50
        assert conn.execute("SELECT COUNT(*) FROM channels WHERE instance_domain='b.example'").fetchone()[0] == 1
    assert staging.load_crawler_run(stage_path)["complete"] is False

    network_log.write_text("")
    phase = "resume"
    pipeline.run_pipeline(
        _args(tmp_path, resume_crawl=True, skip_systemctl=True,
              crawler_dir=str(cli_dir), host_delay_ms=0, timeout_ms=100,
              max_retries=0, concurrency=1, host_concurrency=1),
        command_runner=run_real_crawler, validate_files=False,
    )
    requests = [json.loads(line) for line in network_log.read_text().splitlines()]
    assert [(item["host"], item["start"], item["count"]) for item in requests] == [
        ("a.example", "0", "50"), ("a.example", "50", "50")
    ]
    with sqlite3.connect(stage_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM channels WHERE instance_domain='a.example'").fetchone()[0] == 51
        assert conn.execute("SELECT COUNT(*) FROM channels WHERE instance_domain='b.example'").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM channel_crawl_progress WHERE instance_domain='a.example'").fetchone()[0] == "done"
    assert staging.load_crawler_run(stage_path)["complete"] is True
