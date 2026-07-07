from dataclasses import dataclass
from datetime import timedelta
import asyncio

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
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


@workflow.defn(name="CortexWorkflow")
class CortexWorkflow:
    @workflow.run
    async def run(self, input: CortexWorkflowInput) -> dict:
        workflow_id = workflow.info().workflow_id
        run_id = workflow.info().run_id

        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="RUNNING",
                temporal_workflow_id=workflow_id,
                temporal_run_id=run_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
        )

        nodes = input.definition.get("nodes", [])
        edges = input.definition.get("edges", [])

        action_nodes = [
            n for n in nodes if not n.get("type", "").startswith("trigger.")
        ]
        ordered_nodes = self._topological_sort(action_nodes, edges)

        # Build label -> node_id mapping for template resolution
        node_id_labels: dict[str, str] = {}
        for n in nodes:
            label = n.get("data", {}).get("label", "")
            if label:
                node_id_labels[label] = n["id"]

        all_outputs: dict[str, dict] = {}
        final_output: dict[str, dict] = {}

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=30),
        )

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
                    ),
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=retry_policy,
                )

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
                )

                # Handle condition nodes: only follow the matching branch
                if node_type == "action.condition":
                    branch = output.output.get("branch", "false")
                    # Find edges from this node and deactivate nodes on the other branch
                    for edge in edges:
                        if edge.get("source") == node_id:
                            edge_handle = edge.get("source_handle", "")
                            if edge_handle and edge_handle != branch:
                                target_id = edge.get("target")
                                if target_id in active_node_ids:
                                    active_node_ids.discard(target_id)

            except Exception as e:
                await workflow.execute_activity(
                    update_step_status,
                    UpdateStepStatusInput(
                        instance_id=input.instance_id,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                )

                await workflow.execute_activity(
                    update_instance_status,
                    UpdateInstanceStatusInput(
                        instance_id=input.instance_id,
                        status="FAILED",
                        error_message=f"Step {node_id} failed: {str(e)}",
                    ),
                    start_to_close_timeout=timedelta(seconds=10),
                )

                await workflow.execute_activity(
                    notify_completion,
                    NotifyCompletionInput(
                        instance_id=input.instance_id,
                        workflow_id=input.workflow_id,
                        user_id=input.user_id,
                        status="FAILED",
                        error_message=str(e),
                    ),
                    start_to_close_timeout=timedelta(seconds=5),
                )

                raise

        await workflow.execute_activity(
            update_instance_status,
            UpdateInstanceStatusInput(
                instance_id=input.instance_id,
                status="COMPLETED",
                output=final_output,
            ),
            start_to_close_timeout=timedelta(seconds=10),
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

        return result
