# Spirrow-Prismind

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

**MCP Server for Context-Aware Knowledge Management**

An MCP (Model Context Protocol) server that integrates multiple data sources—Google Drive, RAG (Retrieval-Augmented Generation), and MCP Memory Server—to provide context-aware knowledge management for AI assistants.

> **Note**: 日本語版は [README.ja.md](README.ja.md) を参照してください。

## Features

- **Session Management**: Save and restore work states, automatically suggest relevant documents
- **Project Management**: Switch between multiple projects, search for similar projects
- **Document Operations**: Google Docs integration with automatic catalog registration
- **Catalog Management**: Semantic search with Google Sheets synchronization
- **Knowledge Management**: RAG-based knowledge storage and retrieval

## Requirements

- Python 3.11 or higher
- Google Cloud project with OAuth 2.0 credentials
- RAG server (ChromaDB compatible)
- MCP Memory Server (optional)

## Installation

```bash
# Clone the repository
git clone https://github.com/SpirrowGames/spirrow-prismind.git
cd spirrow-prismind

# Install the package
pip install -e .
```

## Configuration

1. **Copy the example config:**
   ```bash
   cp config.toml.example config.toml
   ```

2. **Set up Google OAuth credentials:**
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/)
   - Enable Google Docs, Drive, and Sheets APIs
   - Create OAuth 2.0 credentials (Desktop application)
   - Download `credentials.json` and place it in the config directory

3. **Configure external services in `config.toml`:**
   - RAG Server endpoint (ChromaDB compatible)
   - MCP Memory Server connection (optional)

## Usage

### With Claude Desktop

Add to your Claude Desktop configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "prismind": {
      "command": "spirrow-prismind",
      "env": {
        "PRISMIND_CONFIG": "/path/to/config.toml"
      }
    }
  }
}
```

### With Claude Code

Add to your Claude Code settings:

```json
{
  "mcpServers": {
    "prismind": {
      "command": "spirrow-prismind",
      "env": {
        "PRISMIND_CONFIG": "/path/to/config.toml"
      }
    }
  }
}
```

## Available Tools

### Session Management
| Tool | Description |
|------|-------------|
| `start_session` | Start a session and restore previous state |
| `end_session` | End session and save state for handoff |
| `save_session` | Save intermediate session state |
| `list_sessions` | List all sessions for a project |
| `delete_session` | Delete a specific session |

### Project Management
| Tool | Description |
|------|-------------|
| `setup_project` | Set up a new project |
| `switch_project` | Switch to another project |
| `list_projects` | List all projects |
| `update_project` | Update project settings |
| `delete_project` | Delete a project |

### Document Operations
| Tool | Description |
|------|-------------|
| `get_document` | Search and retrieve documents |
| `create_document` | Create a new document |
| `update_document` | Update an existing document |

### Catalog Operations
| Tool | Description |
|------|-------------|
| `search_catalog` | Search the document catalog |
| `sync_catalog` | Sync catalog (Sheets → RAG) |

### Knowledge Operations
| Tool | Description |
|------|-------------|
| `add_knowledge` | Add knowledge entries |
| `search_knowledge` | Search knowledge base |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       MCP Server                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                        Tools                           │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │  │
│  │  │ Session │ │ Project │ │Document │ │Knowledge│ ...  │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │  │
│  └───────┼──────────┼──────────┼──────────┼─────────────┘  │
│          │          │          │          │                 │
│  ┌───────┴──────────┴──────────┴──────────┴─────────────┐  │
│  │                    Integrations                       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐         │  │
│  │  │  RAG   │ │ Memory │ │  Docs  │ │ Drive  │         │  │
│  │  │ Client │ │ Client │ │ Client │ │ Client │         │  │
│  │  └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘         │  │
│  └───────┼──────────┼──────────┼──────────┼─────────────┘  │
└──────────┼──────────┼──────────┼──────────┼────────────────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
      ┌────────┐ ┌────────┐ ┌────────────────────┐
      │ChromaDB│ │ Memory │ │    Google APIs     │
      │  RAG   │ │ Server │ │ Docs/Drive/Sheets  │
      └────────┘ └────────┘ └────────────────────┘
```

## Development

### Setup

```bash
# Install with dev dependencies
pip install -e ".[dev]"
```

### Testing

```bash
pytest
```

### Code Quality

```bash
# Format code
ruff format .

# Lint and fix
ruff check --fix .
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Related Projects

- [Model Context Protocol](https://modelcontextprotocol.io) - The protocol specification
- [MCP Servers](https://github.com/modelcontextprotocol/servers) - Official MCP server implementations
