"""Integration tests for Event bus, monotonic sequencing, and API endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from core.events import event_bus
from schemas.domain import EventType, ExecutionEvent


def _unique(s: str) -> str:
    return f"{s}_{uuid.uuid4().hex[:8]}"


class TestEventSystem:
    async def test_event_sequencing_and_api(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        cap_slug = _unique("web_search")
        agent_id = _unique("event_agent")

        # 1. Setup capability & agent
        await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={
                "slug": cap_slug,
                "name": "Search",
                "description": "Search",
                "version": "1.0.0",
            },
        )
        await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json={
                "manifest": {
                    "identity": {
                        "id": agent_id,
                        "name": "Event Agent",
                        "version": "1.0.0",
                        "contract_version": "1.0",
                        "publisher": "dsrt",
                        "category": "test",
                    },
                    "capabilities": [cap_slug],
                    "requirements": {
                        "minimum_core_version": "1.0.0",
                        "required_capabilities": [],
                        "optional_capabilities": [],
                        "required_tools": [],
                        "optional_tools": [],
                    },
                    "permissions": {},
                },
                "package_reference": "agents.test",
            },
        )

        # 2. Subscribe a test listener to EventBus
        received_events: list[ExecutionEvent] = []

        async def _listener(event: ExecutionEvent) -> None:
            received_events.append(event)

        event_bus.subscribe(_listener)

        try:
            # 3. Create Task & Execution
            task_resp = await client.post(
                "/api/v1/tasks",
                headers=headers,
                json={
                    "agent_slug": agent_id,
                    "objective": "Test Event Emission",
                },
            )
            task_id = task_resp.json()["id"]

            exe_resp = await client.post(
                f"/api/v1/tasks/{task_id}/execute",
                headers=headers,
            )
            exe_id = exe_resp.json()["execution"]["id"]

            # Cancel to trigger additional events
            await client.post(
                f"/api/v1/executions/{exe_id}/cancel",
                headers=headers,
            )

            # 4. Query Events via REST API
            events_resp = await client.get(
                f"/api/v1/executions/{exe_id}/events",
                headers=headers,
            )
            assert events_resp.status_code == 200
            events_data = events_resp.json()["events"]

            # Verify monotonic sequence numbers: 1, 2, 3...
            assert len(events_data) >= 2
            sequences = [e["sequence"] for e in events_data]
            assert sequences == sorted(sequences)
            assert sequences[0] == 1
            assert events_data[0]["event_type"] == EventType.EXECUTION_CREATED.value

            # Verify EventBus subscriber received events asynchronously
            assert len(received_events) >= 2

        finally:
            event_bus.unsubscribe(_listener)