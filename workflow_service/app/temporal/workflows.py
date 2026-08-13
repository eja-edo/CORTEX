from dataclasses import dataclass
from datetime import timedelta
import asyncio

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from app.actions.base import ActionResult
    from app.temporal.activities import (
        ExecuteActionInput,
        execute_action,
        UpdateStepStatusInput,
        update_step_status,
        UpdateInstanceStatusInput,
        update_instance_status,
        NotifyCompletionInput,
        notify_completion,
    )


@dataclass
class CortexWorkflowInput:
    instance_id: str
    workflow_id: str
    user_id: str
    definition: dict
    trigger_data: dict
    workspace_id: str | None = None


@workflow.defn(name="CortexWorkflow")
class CortexWorkflow:
    @workflow.run
    async def run(self, input: CortexWorkflowInput) -> dict:
        workflow_id = workflow.info().workflow_id
        run_id = workflow.info().run_id

        # Retry policy for the action activity itself (business logic —
        # HTTP calls to the backend etc).
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=30),
        )
        # Retry policy for bookkeeping activities (DB status updates,
        # completion notification). Without an explicit policy these fall
        # back to the Temporal SDK default, which is effectively unlimited
        # retries — a DB outage would make the whole run hang indefinitely
        # instead of failing cleanly after a bounded number of attempts.
        bookkeeping_retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=10),
        )

        async def _fail(node_id: str, node_type: str, error_message: str) -> None:
            """Shared failure bookkeeping: mark the step FAILED, the
            instance FAILED, and notify — used both when an action raises
            and when it returns ActionResult(success=False) (previously
            treated as success — see the `success` check below)."""
            await workflow.execute_activity(
                update_step_status,
                UpdateStepStatusInput(
                    instance_id=input.instance_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="FAILED",
                    error_message=error_message,
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=bookkeeping_retry_policy,
            )

            await workflow.execute_activity(
                update_instance_status,
                UpdateInstanceStatusInput(
                    instance_id=input.instance_id,
                    status="FAILED",
                    error_message=f"Step {node_id} failed: {error_message}",
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=bookkeeping_retry_policy,
            )

            await workflow.execute_activity(
                notify_completion,
                NotifyCompletionInput(
                    instance_id=input.instance_id,
                    workflow_id=input.workflow_id,
                    user_id=input.user_id,
                    status="FAILED",
                    error_message=error_message,
                ),
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=bookkeeping_retry_policy,
            )

        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="RUNNING",
                temporal_workflow_id=workflow_id,
                temporal_run_id=run_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=bookkeeping_retry_policy,
        )

        nodes = input.definition.get("nodes", [])
        edges = input.definition.get("edges", [])

        action_nodes = [
            n for n in nodes if not n.get("type", "").startswith("trigger.")
        ]
        try:
            ordered_nodes = self._topological_sort(action_nodes, edges)
        except ValueError as e:
            # A cyclic graph used to silently drop the nodes involved in
            # the cycle instead of erroring — the instance would then look
            # like it completed successfully having run only part of the
            # graph. Fail loudly and mark the instance FAILED instead.
            await _fail("_graph", "_topology", str(e))
            raise ApplicationError(str(e))

        # Build label -> node_id mapping for template resolution
        node_id_labels: dict[str, str] = {}
        for n in nodes:
            label = n.get("data", {}).get("label", "")
            if label:
                node_id_labels[label] = n["id"]

        all_outputs: dict[str, dict] = {}
        final_output: dict[str, dict] = {}

        # Track which nodes are reachable based on condition branches
        active_node_ids: set[str] = set(n["id"] for n in ordered_nodes)

        for node in ordered_nodes:
            node_id = node["id"]
            node_type = node["type"]
            node_config = node.get("data", {}).get("config", {})

            # Skip nodes that are not on the active branch
            if node_id not in active_node_ids:
                continue

            # Handle wait nodes: use workflow.sleep() instead of executing action
            if node_type == "action.wait":
                duration = node_config.get("duration", 1)
                unit = node_config.get("unit", "minutes")
                if unit == "seconds":
                    sleep_seconds = duration
                elif unit == "hours":
                    sleep_seconds = duration * 3600
                else:
                    sleep_seconds = duration * 60

                await workflow.execute_activity(
                    update_step_status,
                    UpdateStepStatusInput(
                        instance_id=input.instance_id,
                        node_id=node_id,
                        node_type=node_type,
                        status="RUNNING",
                        input_data=node_config,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=bookkeeping_retry_policy,
                )

                await asyncio.sleep(sleep_seconds)

                output = {"waited": True, "duration": duration, "unit": unit}
                all_outputs[node_id] = output
                final_output[node_id] = output

                await workflow.execute_activity(
                    update_step_status,
                    UpdateStepStatusInput(
                        instance_id=input.instance_id,
                        node_id=node_id,
                        node_type=node_type,
                        status="COMPLETED",
                        output_data=output,
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=bookkeeping_retry_policy,
                )
                continue

            await workflow.execute_activity(
                update_step_status,
                UpdateStepStatusInput(
                    instance_id=input.instance_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="RUNNING",
                    input_data=node_config,
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=bookkeeping_retry_policy,
            )

            try:
                output = await workflow.execute_activity(
                    execute_action,
                    ExecuteActionInput(
                        action_type=node_type,
                        config=node_config,
                        user_id=input.user_id,
                        workflow_id=input.workflow_id,
                        instance_id=input.instance_id,
                        node_id=node_id,
                        trigger_data=input.trigger_data,
                        previous_outputs=all_outputs,
                        node_id_labels=node_id_labels,
                        workspace_id=input.workspace_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=retry_policy,
                )
            except Exception as e:
                await _fail(node_id, node_type, str(e))
                raise

            # execute_action returning ActionResult(success=False, error=...)
            # is not an exception — it used to be recorded as a completed
            # step with whatever (usually empty) output the action
            # returned, and the instance would go on to finish COMPLETED.
            # A node explicitly reporting failure must fail the run the
            # same way an unhandled exception does.
            success = output.success if isinstance(output, ActionResult) else output.get("success", True)
            if not success:
                error_message = (
                    output.error if isinstance(output, ActionResult) else output.get("error")
                ) or "Action reported failure"
                await _fail(node_id, node_type, error_message)
                raise ApplicationError(error_message)

            output_dict = output.output if isinstance(output, ActionResult) else output.get("output", output)
            all_outputs[node_id] = output_dict
            final_output[node_id] = output_dict

            await workflow.execute_activity(
                update_step_status,
                UpdateStepStatusInput(
                    instance_id=input.instance_id,
                    node_id=node_id,
                    node_type=node_type,
                    status="COMPLETED",
                    output_data=output_dict,
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=bookkeeping_retry_policy,
            )

            # Handle condition nodes: only follow the matching branch
            if node_type == "action.condition":
                branch = output_dict.get("branch", "false")
                # Find edges from this node and deactivate nodes on the other branch
                for edge in edges:
                    if edge.get("source") == node_id:
                        edge_handle = edge.get("source_handle", "")
                        if edge_handle and edge_handle != branch:
                            target_id = edge.get("target")
                            if target_id in active_node_ids:
                                active_node_ids.discard(target_id)

        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="COMPLETED",
                output=final_output,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=bookkeeping_retry_policy,
        )

        await workflow.execute_activity(
            notify_completion,
            NotifyCompletionInput(
                instance_id=input.instance_id,
                workflow_id=input.workflow_id,
                user_id=input.user_id,
                status="COMPLETED",
                output=final_output,
            ),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=bookkeeping_retry_policy,
        )

        return final_output

    def _topological_sort(
        self, nodes: list[dict], edges: list[dict]
    ) -> list[dict]:
        node_map = {n["id"]: n for n in nodes}
        in_degree = {n["id"]: 0 for n in nodes}
        adjacency = {n["id"]: [] for n in nodes}

        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if src in adjacency and tgt in in_degree:
                adjacency[src].append(tgt)
                in_degree[tgt] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result: list[dict] = []

        while queue:
            nid = queue.pop(0)
            if nid in node_map:
                result.append(node_map[nid])
            for neighbor in adjacency.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            stuck = sorted(set(node_map) - {n["id"] for n in result})
            raise ValueError(f"Workflow definition has a cycle involving nodes: {stuck}")

        return result
