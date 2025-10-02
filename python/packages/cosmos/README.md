# Get Started with Microsoft Agent Framework Redis

Please install this package as the extra for `agent-framework`:

```bash
pip install agent-framework[cosmos]
```

## Components

### Cosmos Chat Message Store

The `CosmosChatMessageStore` provides persistent conversation storage using Redis Lists, enabling chat history to survive application restarts and support distributed applications.

#### Key Features

- **Persistent Storage**: Messages survive application restarts
