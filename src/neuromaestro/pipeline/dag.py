"""
DAG dependency rules:
  1. unzip -> recon (if both requested)
  2. recon -> all downstream non-staged tasks (bids, mriqc, intermed)
  3. intermed -> staged tasks (multi_stage: true in config)
  4. Without intermed, staged tasks run in parallel with recon
  5. Within each config section: post -> prep
"""

from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field
from collections import deque
import typer
from .utils.output_checker import OutputChecker

@dataclass
class TaskNode:
    """Task node in DAG"""
    name: str
    task_config: Dict[str, Any]
    dependencies: Set[str] = field(default_factory=set)
    job_ids: List[str] = field(default_factory=list)
    completed: bool = False
    
    def add_dependency(self, dep_name: str):
        self.dependencies.add(dep_name)


class DAGExecutor:
    """DAG-based task executor"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.nodes: Dict[str, TaskNode] = {}
        self.execution_order: List[str] = []
        self.project_config = None
    
    def add_task(self, task_name: str, task_config: Dict[str, Any], dependencies: Optional[List[str]] = None):
        if task_name in self.nodes:
            return
        node = TaskNode(
            name=task_name,
            task_config=task_config,
            dependencies=set(dependencies or [])
        )
        self.nodes[task_name] = node
    
    def build_dag(self, requested_tasks: List[str]) -> List[str]:
        """Build DAG from requested tasks"""
        for task_name in requested_tasks:
            self._register_task(task_name)

        self._apply_prep_sequence(requested_tasks)
        self._apply_recon_dependencies(requested_tasks)
        self._apply_intermed_dependencies(requested_tasks)
        self._apply_section_dependencies(requested_tasks)
        self._prune_dangling_dependencies()

        return self._topological_sort()

    def _register_task(self, task_name: str):
        if task_name in self.nodes:
            return
        from .utils.config_utils import find_task_config_by_name_with_project
        task_config = find_task_config_by_name_with_project(task_name, getattr(self, 'project_config', None))
        if not task_config:
            raise ValueError(
                f"Task '{task_name}' has no configuration in config.yaml. "
                "Check the task name, or add it to the global config."
            )
        self.add_task(task_name, task_config)

    def _prune_dangling_dependencies(self):
        """Drop dependencies on tasks that were never registered.

        Without this a dangling edge keeps in_degree above zero forever and
        _topological_sort reports a circular dependency that does not exist.
        """
        valid = set(self.nodes)
        for node in self.nodes.values():
            node.dependencies &= valid

    def _apply_prep_sequence(self, requested_tasks: List[str]):
        """unzip -> recon if both requested"""
        if 'unzip' in self.nodes and 'recon' in self.nodes:
            self.nodes['recon'].add_dependency('unzip')

    def _apply_recon_dependencies(self, requested_tasks: List[str]):
        """recon -> all downstream non-staged tasks.

        Staged tasks (multi_stage=true) are always excluded: without intermed
        they run in parallel with recon; with intermed they depend on it instead.
        """
        if 'recon' not in requested_tasks:
            return

        downstream = set(requested_tasks) - {'unzip', 'recon'}
        for task_name in downstream:
            if task_name not in self.nodes:
                continue
            if self.nodes[task_name].task_config.get('multi_stage'):
                continue
            self.nodes[task_name].add_dependency('recon')

    def _apply_intermed_dependencies(self, requested_tasks: List[str]):
        """intermed -> staged prep tasks only (multi_stage: true, stage: prep)"""
        from .utils.config_utils import get_all_task_names
        intermed_tasks = [t for t in requested_tasks if t in get_all_task_names('intermed')]
        if not intermed_tasks:
            return
        for task_name in requested_tasks:
            if task_name in self.nodes:
                cfg = self.nodes[task_name].task_config
                if cfg.get('multi_stage') and cfg.get('stage') == 'prep':
                    for st in intermed_tasks:
                        self.nodes[task_name].add_dependency(st)

    def _apply_section_dependencies(self, requested_tasks: List[str]):
        """Within each config section, post tasks depend on prep tasks"""
        requested_set = set(requested_tasks)
        for section_tasks in self.config.values():
            if not isinstance(section_tasks, list):
                continue
            prep_tasks = [t['name'] for t in section_tasks if t.get('stage') == 'prep' and t['name'] in requested_set]
            post_tasks = [t['name'] for t in section_tasks if t.get('stage') == 'post' and t['name'] in requested_set]
            for post in post_tasks:
                for prep in prep_tasks:
                    if post in self.nodes and prep in self.nodes:
                        self.nodes[post].add_dependency(prep)

    def _topological_sort(self) -> List[str]:
        """Topological sort on DAG"""
        in_degree = {name: len(node.dependencies) for name, node in self.nodes.items()}
        queue = deque([name for name, degree in in_degree.items() if degree == 0])
        result = []
        
        while queue:
            current = queue.popleft()
            result.append(current)
            for name, node in self.nodes.items():
                if current in node.dependencies:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)
        
        if len(result) != len(self.nodes):
            raise ValueError("Circular dependency detected")
        
        return result
    
    def execute(self, requested_tasks, input_dir, output_dir, work_dir, container_dir,
                dry_run, context=None, option_env=None, project_config=None,
                original_work_dir=None, db_path: Optional[str] = None,
                resume: bool = False, checks_config_path: Optional[str] = None,
                execution_id: Optional[int] = None):
        """Execute tasks in DAG order"""
        if context is None:
            context = {}
        
        self.project_config = project_config
        all_job_ids = {}

        # Resume: initialise OutputChecker once if --resume was requested
        checker = None
        if resume and checks_config_path:
            prefix = (project_config or {}).get('prefix', 'sub-')
            session = (option_env or {}).get('session', '01')
            checker = OutputChecker(
                # Checks resolve against the output tree: output_pattern writes the
                # task subdirectories under output_dir, not under work_dir.
                config_path=checks_config_path,
                work_dir=output_dir,
                prefix=prefix,
                session=session,
            )
            checker.warn_missing_configs(requested_tasks)
        
        # Build DAG for requested tasks
        execution_order = self.build_dag(requested_tasks)

        # Validate all scripts exist before submitting anything
        if not dry_run:
            self._validate_all_scripts(project_config)

        typer.echo("\nDAG execution plan:")
        for task_name in execution_order:
            task_deps = sorted(self.nodes[task_name].dependencies)
            dep_str = ', '.join(task_deps) if task_deps else '(no dependencies)'
            typer.echo(f"  {task_name} <- {dep_str}")
        typer.echo("")

        # Execute all tasks
        for task_name in execution_order:
            node = self.nodes[task_name]
            wait_jobs = []
            for dep_name in node.dependencies:
                if dep_name in all_job_ids:
                    wait_jobs.extend(all_job_ids[dep_name])
            
            all_subjects = context.get('subjects', [])

            # Resume: filter already-completed subjects
            if checker and not dry_run:
                if checker.is_group(task_name):
                    # Group task: single job, all-or-nothing on the group result
                    rows = checker.check_group(task_name)
                    if rows and all(r["status"] == "PASS" for r in rows):
                        typer.echo(f"[resume] {task_name}: group result complete, skipping task.")
                        all_job_ids[task_name] = []
                        node.completed = True
                        continue
                    subjects_str = ','.join(all_subjects)
                else:
                    pending = checker.get_pending_subjects(task_name, all_subjects)
                    if len(pending) < len(all_subjects):
                        skipped = sorted(set(all_subjects) - set(pending))
                        typer.echo(
                            f"[resume] {task_name}: skipping {len(skipped)} completed subject(s): "
                            f"{', '.join(skipped)}"
                        )
                    if not pending:
                        typer.echo(f"[resume] {task_name}: all subjects complete, skipping task.")
                        all_job_ids[task_name] = []
                        node.completed = True
                        continue
                    subjects_str = ','.join(pending)
            else:
                subjects_str = ','.join(all_subjects)

            task_env = dict(option_env or {})

            # Execute task
            try:
                job_ids = self._execute_single_task(
                    node, subjects=subjects_str,
                    input_dir=input_dir, output_dir=output_dir, work_dir=work_dir,
                    container_dir=container_dir, dry_run=dry_run,
                    wait_jobs=wait_jobs, option_env=task_env,
                    project_config=project_config, requested_tasks=requested_tasks,
                    original_work_dir=original_work_dir, db_path=db_path,
                    execution_id=execution_id,
                )
            except Exception:
                submitted = [jid for ids in all_job_ids.values() for jid in ids]
                if submitted:
                    typer.echo(
                        f"\nAlready submitted before this failure: {', '.join(submitted)}\n"
                        "These jobs stay queued; cancel them if the partial run is unwanted.",
                        err=True,
                    )
                raise
            
            # Record results
            all_job_ids[task_name] = job_ids or []
            node.job_ids = job_ids or []
            node.completed = True
        
        return all_job_ids, context

    def _validate_all_scripts(self, project_config: Optional[Dict]) -> None:
        from pathlib import Path
        from .utils.hpc_utils import get_script_with_validation
        scripts_dir = (project_config or {}).get('scripts_dir', 'scripts/template')

        if not Path(scripts_dir).exists():
            return

        missing: List[str] = []
        for node in self.nodes.values():
            for script in node.task_config.get('scripts', []):
                if not get_script_with_validation(script, scripts_dir):
                    missing.append(f"  [{node.name}] {script}")

        if missing:
            raise FileNotFoundError(
                f"Aborting: the following scripts were not found in '{scripts_dir}':\n" + "\n".join(missing)
            )

    def _execute_single_task(self, node: 'TaskNode', subjects: str, input_dir: str,
                        output_dir: str, work_dir: str, container_dir: str,
                        dry_run: bool, wait_jobs: Optional[list] = None,
                        option_env=None, project_config=None,
                        requested_tasks: List[str] = None,
                        original_work_dir: Optional[str] = None,
                        db_path: Optional[str] = None,
                        execution_id: Optional[int] = None) -> list:
        """Execute single task"""
        task_config = node.task_config
        scripts = task_config.get('scripts', [])
        
        if not scripts:
            return []
        
        from .utils.hpc_utils import submit_slurm_job
        
        job_ids = []
        for script in scripts:
            job_id = submit_slurm_job(
                script_name=script,
                subjects=subjects,
                input_dir=input_dir,
                output_dir=output_dir,
                work_dir=work_dir,
                container_dir=container_dir,
                wait_jobs=wait_jobs,
                task_config=task_config,
                dry_run=dry_run,
                option_env=option_env,
                project_config=project_config,
                requested_tasks=requested_tasks,
                original_work_dir=original_work_dir,
                db_path=db_path,
                execution_id=execution_id,
            )
            # A missing job id reaches downstream tasks as an empty wait_jobs list, which is indistinguishable from "no dependency needed".
            if not job_id:
                raise RuntimeError(
                    f"Submission failed for task '{node.name}' (script '{script}'). "
                    "Aborting: downstream tasks would otherwise be submitted with no "
                    "dependency on it and run on missing input."
                )
            job_ids.append(job_id)

        return job_ids


class TaskRegistry:
    """Registry for task expansion"""
    
    def __init__(self):
        from .utils.config_utils import PrepChoice, MRIQCChoice

        self.task_expanders = {
            PrepChoice.unzip_recon: self._expand_unzip_recon,
            MRIQCChoice.all: self._expand_mriqc_all,
        }
    
    def expand_tasks(self, **kwargs) -> List[str]:
        """Expand task choices into concrete task names"""
        tasks = []
        
        # Prep tasks
        if kwargs.get('prep'):
            prep_choice = kwargs['prep']
            if prep_choice in self.task_expanders:
                tasks.extend(self.task_expanders[prep_choice](kwargs))
            else:
                prep_mapping = {
                    'recon': 'recon',
                    'unzip': 'unzip',
                }
                task_name = prep_mapping.get(prep_choice.value, prep_choice.value)
                tasks.append(task_name)
        
        # Intermed tasks
        if kwargs.get('intermed'):
            from .utils.config_utils import get_all_task_names
            valid_intermed = get_all_task_names('intermed')
            for name in kwargs['intermed']:
                if name in valid_intermed:
                    tasks.append(name)
                else:
                    typer.echo(f"Warning: '{name}' is not a valid intermed task, skipping")
        
        # MRIQC tasks
        if kwargs.get('mriqc'):
            mriqc_choice = kwargs['mriqc']
            if mriqc_choice in self.task_expanders:
                tasks.extend(self.task_expanders[mriqc_choice](kwargs))
            else:
                mriqc_mapping = {
                    'individual': 'mriqc_preprocess',
                    'group': 'mriqc_post',
                }
                tasks.append(mriqc_mapping.get(mriqc_choice.value, f"mriqc_{mriqc_choice.value}"))
        
        # BIDS pipelines: --bids-prep rest,dwi  /  --bids-post rest,dwi
        if kwargs.get('bids_prep'):
            tasks.extend(self._expand_pipeline_tasks(kwargs['bids_prep'], 'prep'))
        if kwargs.get('bids_post'):
            tasks.extend(self._expand_pipeline_tasks(kwargs['bids_post'], 'post'))

        # Staged pipelines: --staged-prep cards,kidvid  /  --staged-post cards,kidvid
        if kwargs.get('staged_prep'):
            tasks.extend(self._expand_pipeline_tasks(kwargs['staged_prep'], 'prep'))
        if kwargs.get('staged_post'):
            tasks.extend(self._expand_pipeline_tasks(kwargs['staged_post'], 'post'))
        
        # Task prep
        if kwargs.get('task_prep'):
            tasks.extend(kwargs['task_prep'])
        
        # Task post
        if kwargs.get('task_post'):
            tasks.extend(kwargs['task_post'])
        
        return tasks
    
    def _expand_unzip_recon(self, kwargs) -> List[str]:
        return ['unzip', 'recon']
    
    def _expand_mriqc_all(self, kwargs) -> List[str]:
        from .utils.config_utils import get_tasks_from_section
        return [name for name, _ in get_tasks_from_section('qc')]

    def _expand_pipeline_tasks(self, pipeline_names: List[str], stage: str) -> List[str]:
        """Expand a list of pipeline section names into task names for a given stage."""
        from .utils.config_utils import get_tasks_from_section
        tasks = []
        for pipeline in pipeline_names:
            tasks.extend([name for name, _ in get_tasks_from_section(pipeline, stage)])
        return tasks

