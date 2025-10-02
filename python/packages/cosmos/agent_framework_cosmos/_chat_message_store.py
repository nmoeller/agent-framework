# Copyright (c) Microsoft. All rights reserved.
from collections.abc import Collection
from typing import Any, ClassVar
from uuid import uuid4

from agent_framework import ChatMessage, ChatMessageStore
from agent_framework._pydantic import AFBaseModel, AFBaseSettings
from agent_framework.exceptions import ServiceInvalidExecutionSettingsError, ServiceResponseException
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.cosmos.partition_key import PartitionKey
from pydantic import ValidationError, model_validator


class CosmosStoreState(AFBaseModel):
    """State model for serializing and deserializing Cosmos chat message store data."""

    id: str | None = None
    thread_id: str
    additional_properties: dict[str, Any] = {}
    messages: list[ChatMessage] = []

    @model_validator(mode="before")
    def set_id_from_thread_id(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Ensure 'id' is set from 'thread_id' if not provided."""
        if "thread_id" in values and "id" not in values:
            values["id"] = values["thread_id"]
        return values


class CosmosDBNoSqlSettings(AFBaseSettings):
    env_prefix: ClassVar[str] = "AZURE_COSMOS_DB_NO_SQL_"

    database_name: str
    container_name: str


class CosmosChatMessageStore(ChatMessageStore):
    """A chat message store that uses Azure Cosmos DB as the backend."""

    cosmos_client: CosmosClient
    database_name: str
    container_name: str
    thread_id: str
    _save_one_every_message: bool = False
    _create_container_and_database: bool
    _messages: list[ChatMessage] = []

    def __init__(
        self,
        cosmos_client: CosmosClient,
        database_name: str = "chat_messages_db",
        container_name: str = "chat_messages_container",
        partition_key: str = "/thread_id",
        thread_id: str | None = None,
        save_one_every_message: bool = False,
        create_container_and_database: bool = False,
    ):
        try:
            settings = CosmosDBNoSqlSettings(
                database_name=database_name,
                container_name=container_name,
            )
        except ValidationError as e:
            raise ServiceInvalidExecutionSettingsError(
                "CosmosChatMessageStore cannot be initialized due to invalid settings."
            ) from e

        self.cosmos_client = cosmos_client
        self.database_name = settings.database_name
        self.container_name = settings.container_name
        self.thread_id = thread_id if thread_id else f"{uuid4()}"
        self.partition_key = PartitionKey(partition_key)
        self._create_container_and_database = create_container_and_database
        self._save_one_every_message = save_one_every_message

    async def _does_database_exist(self) -> bool:
        """Checks if the database exists."""
        try:
            await self.cosmos_client.get_database_client(self.database_name).read()
            return True
        except CosmosResourceNotFoundError:
            return False
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to check if database '{self.database_name}' exists, with message {e}"
            ) from e

    async def _does_container_exist(self) -> bool:
        """Checks if the container exists."""
        try:
            database = self.cosmos_client.get_database_client(self.database_name)
            await database.get_container_client(self.container_name).read()
            return True
        except CosmosResourceNotFoundError:
            return False
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to check if container '{self.container_name}' exists in database '{self.database_name}', with message {e}"
            ) from e

    async def _create_database_and_container_if_not_exists(self) -> None:
        """Creates the database and container if they do not exist."""
        try:
            if not await self._does_database_exist():
                await self.cosmos_client.create_database(self.database_name)
            if not await self._does_container_exist():
                database = self.cosmos_client.get_database_client(self.database_name)
                await database.create_container(id=self.container_name, partition_key=self.partition_key)
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to create database '{self.database_name}' or container '{self.container_name}', with message {e}"
            ) from e

    async def _get_container_client(self):
        """Gets the container client, creating the database and container if they do not exist."""
        try:
            database = await self._get_database_client(self.database_name)
            return database.get_container_client(self.container_name)
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to get container client for container '{self.container_name}' in database '{self.database_name}', with message {e}"
            ) from e

    async def _get_database_client(self, database_name: str):
        """Gets the database client, creating the database if it does not exist."""
        try:
            return self.cosmos_client.get_database_client(database_name)
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to get database client for database '{database_name}', with message {e}"
            ) from e

    async def add_messages(self, messages: Collection[ChatMessage]) -> None:
        self._messages.extend(messages)
        if self._save_one_every_message:
            await self.serialize_state()

    async def list_messages(self) -> list[ChatMessage]:
        return self._messages

    async def deserialize_state(self, serialized_store_state: CosmosStoreState, **kwargs: Any) -> None:
        """Deserializes the state into the properties on this store.

        This method, together with serialize_state can be used to save and load messages from a persistent store
        if this store only has messages in memory.
        """
        chat_message_store_state = CosmosStoreState.model_validate(serialized_store_state)
        container_client = await self._get_container_client()
        try:
            stored_state_item = await container_client.read_item(
                item=chat_message_store_state.thread_id, partition_key=chat_message_store_state.thread_id
            )
        except Exception as e:
            raise ServiceResponseException(
                f"Failed to read item with id '{chat_message_store_state.id}' from container '{self.container_name}' in database '{self.database_name}', with message {e}"
            ) from e

        deserialized_state = CosmosStoreState.model_validate(stored_state_item, **kwargs)
        self.thread_id = deserialized_state.thread_id
        self._messages.extend(deserialized_state.messages)

    async def serialize_state(self, **kwargs: Any) -> Any:
        """Serializes the current object's state.

        This method, together with deserialize_state can be used to save and load messages from a persistent store
        if this store only has messages in memory.
        """
        # Create the database and container if they do not exist and the flag is set.
        if self._create_container_and_database:
            await self._create_database_and_container_if_not_exists()
            self._create_container_and_database = False

        chat_message_store_state = CosmosStoreState(
            id=self.thread_id, thread_id=self.thread_id, messages=self._messages, **kwargs
        )
        container_client = await self._get_container_client()
        serialized_state = chat_message_store_state.model_dump()
        await container_client.upsert_item(serialized_state)
        return self.thread_id

    async def __aexit__(self):
        await self.cosmos_client.close()
