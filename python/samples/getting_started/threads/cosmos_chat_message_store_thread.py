# Copyright (c) Microsoft. All rights reserved.

import asyncio

from agent_framework import AgentThread
from agent_framework._threads import deserialize_thread_state
from agent_framework.azure import AzureOpenAIChatClient
from agent_framework.cosmos import CosmosChatMessageStore
from azure.cosmos.aio import CosmosClient
from azure.identity import DefaultAzureCredential


def get_current_timestamp() -> str:
    """Get the current timestamp in ISO 8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    """Demonstrates how to use 3rd party or custom chat message store for threads."""
    print("=== Thread with 3rd party or custom chat message store ===")
    cosmos_client = CosmosClient(
        url="https://chatmessagetstaf.documents.azure.com:443/", credential=DefaultAzureCredential()
    )

    cosmos_store_message = CosmosChatMessageStore(cosmos_client=cosmos_client)
    # Create thread with Cosmos store
    thread = AgentThread(message_store=cosmos_store_message)
    # AzureOpenAI Chat Client is used as an example here,
    # other chat clients can be used as well.
    agent = AzureOpenAIChatClient().create_agent(
        name="Joker",
        instructions="You are good at telling jokes.",
        tools=[get_current_timestamp],
    )

    # Respond to user input.
    query = "Tell me a joke about a pirate. and the current time"
    print(f"User: {query}")
    print(f"Agent: {await agent.run(query, thread=thread)}\n")

    # Serialize the thread state, so it can be stored for later use.
    serialized_thread = await thread.serialize(user_id="user123")

    # The thread can now be saved to a database, file, or any other storage mechanism and loaded again later.
    print(f"Serialized thread: {serialized_thread}\n")

    # Deserialize the thread state after loading from storage.
    await deserialize_thread_state(thread, serialized_thread)

    # Respond to user input.
    query = "Now tell the same joke in the voice of a pirate, and add some emojis to the joke."
    print(f"User: {query}")
    print(f"Agent: {await agent.run(query, thread=thread)}\n")

    await thread.serialize(user_id="user123")


if __name__ == "__main__":
    asyncio.run(main())
