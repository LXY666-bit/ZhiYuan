import asyncio
import threading
from types import SimpleNamespace

from backend.research.dispatcher import ResearchPlanJobDispatcher
from tests.support import TEST_MODEL_SNAPSHOT


def test_dispatcher_recovers_after_transient_claim_failure():
    async def scenario():
        recovered = asyncio.Event()
        loop = asyncio.get_running_loop()

        class Repository:
            calls = 0

            def claim_plan_job(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("transient database outage")
                loop.call_soon_threadsafe(recovered.set)
                return None

        repository = Repository()
        dispatcher = ResearchPlanJobDispatcher(
            repository=repository, poll_seconds=0.001
        )
        await dispatcher.start()
        try:
            await asyncio.wait_for(recovered.wait(), timeout=2)
            assert repository.calls >= 2
        finally:
            await dispatcher.close()

    asyncio.run(scenario())


def test_lost_plan_heartbeat_cancels_provider_and_never_publishes_result():
    async def scenario():
        heartbeat_called = asyncio.Event()
        release_planner = threading.Event()
        loop = asyncio.get_running_loop()

        class Repository:
            finished = False

            def heartbeat_plan_job(self, **kwargs):
                loop.call_soon_threadsafe(heartbeat_called.set)
                raise RuntimeError("ownership lost")

            def plan_job_cancel_requested(self, job_id):
                return False

            def finish_plan_job(self, **kwargs):
                self.finished = True

            def fail_plan_job(self, **kwargs):
                raise AssertionError("a lost owner cannot publish failure either")

        class Planner:
            def generate(self, *, cancellation, **kwargs):
                assert release_planner.wait(2)
                assert cancellation()
                return SimpleNamespace(
                    steps=[], usage_status="unknown", error_code=None
                )

        repository = Repository()
        dispatcher = ResearchPlanJobDispatcher(
            repository=repository, planner=Planner(), heartbeat_seconds=0.001
        )
        execution = asyncio.create_task(
            dispatcher._execute(
                (
                    SimpleNamespace(id="job", fencing_token=1),
                    "title",
                    "objective",
                    "quick",
                    [],
                    TEST_MODEL_SNAPSHOT.model_dump(mode="json"),
                )
            )
        )
        await asyncio.wait_for(heartbeat_called.wait(), timeout=2)
        heartbeats = [
            task
            for task in asyncio.all_tasks()
            if task.get_name() == "research-plan-heartbeat:job"
        ]
        await asyncio.gather(*heartbeats)
        release_planner.set()
        await execution
        assert not repository.finished

    asyncio.run(scenario())
