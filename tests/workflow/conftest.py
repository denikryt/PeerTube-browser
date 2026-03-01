import pytest
import subprocess
import shutil
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

@pytest.fixture
def tmp_repo(tmp_path):
    """
    Creates a temporary git repository with the workflow CLI installed.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    
    # Create directory structure
    (repo_dir / "dev/map").mkdir(parents=True)
    (repo_dir / "dev/workflow_lib").mkdir(parents=True)
    
    # Copy workflow CLI files
    shutil.copy(ROOT_DIR / "dev/workflow", repo_dir / "dev/workflow")
    for lib_file in (ROOT_DIR / "dev/workflow_lib").glob("*.py"):
        shutil.copy(lib_file, repo_dir / "dev/workflow_lib/")
    
    (repo_dir / "dev/workflow").chmod(0o755)
    
    # Create empty docs for features
    (repo_dir / "dev/TASK_LIST.md").write_text("# Task List\n")
    (repo_dir / "dev/TASK_EXECUTION_PIPELINE.md").write_text("# Task Execution Pipeline\n")
    (repo_dir / "dev/FEATURE_PLANS.md").write_text("# Feature Plans\n")
    
    # Initialize git
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    
    return repo_dir

class WorkflowRunner:
    def __init__(self, repo_dir):
        self.repo_dir = repo_dir
        self.workflow_path = repo_dir / "dev/workflow"

    def run(self, *args, check=True, parse_json=True):
        cmd = [str(self.workflow_path)] + list(args)
        result = subprocess.run(
            cmd,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        
        if check and result.returncode != 0:
            error_msg = f"Workflow command failed with code {result.returncode}: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            pytest.fail(error_msg)
            
        output = result.stdout
        if parse_json:
            try:
                # Assuming the CLI might output some text before/after JSON in some cases, 
                # though usually it should be clean.
                return json.loads(output)
            except json.JSONDecodeError:
                return output
        return output

@pytest.fixture
def workflow(tmp_repo):
    """
    Returns a WorkflowRunner instance for the temporary repository.
    """
    return WorkflowRunner(tmp_repo)
