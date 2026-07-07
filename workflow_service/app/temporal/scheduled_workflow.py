from datetime import timedelta

from temporalio import workflow


@workflow.defn(name="ScheduledExecutionWorkflow")
class ScheduledExecutionWorkflow:
    @workflow.run
    async def run(self, input: dict) -> dict:
        instance_id = await workflow.execute_activity(
            "trigger-scheduled-execution",
            input,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return {"instance_id": instance_id}
