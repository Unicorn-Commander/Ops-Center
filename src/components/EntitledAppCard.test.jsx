import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import EntitledAppCard from './EntitledAppCard';

const app = {
  id: 'project-ops',
  name: 'Project-Ops',
  slug: 'project-ops',
  purpose: 'Run projects, tasks, approvals, time tracking, and capacity planning.',
  state: 'ready',
  primary_action: {
    label: 'Open Project-Ops',
    url: 'https://projects.magicunicorn.dev'
  },
  companion: {
    label: 'Connect your AI',
    mcp_url: 'https://api.projectops.magicunicorn.dev/api/v1/mcp',
    claude_code_command: 'claude mcp add --transport http project-ops https://api.projectops.magicunicorn.dev/api/v1/mcp',
    client_config: {
      mcpServers: {
        'project-ops': { url: 'https://api.projectops.magicunicorn.dev/api/v1/mcp' }
      }
    },
    chatgpt_url: 'https://api.projectops.magicunicorn.dev/api/v1/mcp',
    desktop: [{ label: 'Desktop app', url: 'https://projects.magicunicorn.dev/downloads/desktop' }],
    mobile: []
  }
};

describe('EntitledAppCard', () => {
  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) }
    });
  });

  test('renders the entitlement state and opens all AI connection recipes', async () => {
    render(<EntitledAppCard app={app} />);

    expect(screen.getByRole('heading', { name: 'Project-Ops' })).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open Project-Ops/ })).toHaveAttribute(
      'href',
      app.primary_action.url
    );

    fireEvent.click(screen.getByRole('button', { name: 'Connect your AI to Project-Ops' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(app.companion.claude_code_command)).toBeInTheDocument();
    expect(screen.getByLabelText('JSON configuration for other MCP clients')).toHaveTextContent(
      app.companion.mcp_url
    );
    expect(screen.getAllByRole('link', { name: 'Desktop app' })).toHaveLength(2);
    expect(screen.getByRole('link', { name: app.companion.chatgpt_url })).toHaveAttribute(
      'href',
      app.companion.chatgpt_url
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy Project-Ops Claude Code command' }));
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(app.companion.claude_code_command);
  });

  test('does not render an explicitly not-entitled app', () => {
    const { container } = render(<EntitledAppCard app={{ ...app, state: 'not_entitled' }} />);
    expect(container).toBeEmptyDOMElement();
  });

  test('labels an app that needs its first open', () => {
    render(<EntitledAppCard app={{ ...app, state: 'needs_first_open' }} />);
    expect(screen.getByText('Needs first open')).toBeInTheDocument();
  });
});
