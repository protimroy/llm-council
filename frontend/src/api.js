/**
 * API client for the LLM Council backend.
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * List available models and current config.
   */
  async listModels() {
    const response = await fetch(`${API_BASE}/api/models`);
    if (!response.ok) {
      throw new Error('Failed to list models');
    }
    return response.json();
  },

  async refreshModels() {
    const response = await fetch(`${API_BASE}/api/models/refresh`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error('Failed to refresh models');
    }
    return response.json();
  },

  /**
   * Get current council configuration.
   */
  async getConfig() {
    const response = await fetch(`${API_BASE}/api/config`);
    if (!response.ok) {
      throw new Error('Failed to get config');
    }
    return response.json();
  },

  async exportConversation(conversationId, format = 'markdown') {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/export?format=${format}`
    );
    if (!response.ok) {
      throw new Error('Failed to export conversation');
    }
    return response.json();
  },

  async saveResearchLog(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/research-log`,
      { method: 'POST' }
    );
    if (!response.ok) {
      throw new Error('Failed to save research log');
    }
    return response.json();
  },

  async listResearchLogs() {
    const response = await fetch(`${API_BASE}/api/research-logs`);
    if (!response.ok) {
      throw new Error('Failed to list research logs');
    }
    return response.json();
  },

  async setResearchContext(conversationId, filename, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/research-context`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filename, content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to load research context');
    }
    return response.json();
  },

  async setResearchContextFromLog(conversationId, filename) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/research-context/from-log`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ filename }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to load saved research log');
    }
    return response.json();
  },

  async clearResearchContext(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/research-context`,
      { method: 'DELETE' }
    );
    if (!response.ok) {
      throw new Error('Failed to clear research context');
    }
    return response.json();
  },

  /**
   * Update council configuration.
   */
  async updateConfig(councilModels, chairmanModel) {
    const response = await fetch(`${API_BASE}/api/config`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        council_models: councilModels,
        chairman_model: chairmanModel,
      }),
    });
    if (!response.ok) {
      throw new Error('Failed to update config');
    }
    return response.json();
  },

  /**
   * Send a message in a conversation.
   */
  async sendMessage(conversationId, content) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );
    if (!response.ok) {
      throw new Error('Failed to send message');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   * @returns {Promise<void>}
   */
  async sendMessageStream(conversationId, content, onEvent) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}/message/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
      }
    );

    if (!response.ok) {
      throw new Error('Failed to send message');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      // Keep the last (possibly incomplete) line in the buffer
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          try {
            const event = JSON.parse(data);
            onEvent(event.type, event);
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }

    // Process any remaining complete lines in the buffer
    if (buffer.startsWith('data: ')) {
      try {
        const event = JSON.parse(buffer.slice(6));
        onEvent(event.type, event);
      } catch {
        // Incomplete trailing chunk — ignore
      }
    }
  },
};
