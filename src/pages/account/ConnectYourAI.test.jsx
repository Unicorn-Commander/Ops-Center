import React from 'react';
import { act, render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { PROD_MCP_APPS } from '../../config/mcpApps';
import ConnectYourAI from './ConnectYourAI';

function renderPage() {
  return render(
    <ThemeProvider>
      <ConnectYourAI />
    </ThemeProvider>
  );
}

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) }
  });
});

describe('ConnectYourAI', () => {
  test('renders the intro, every app, and each client recipe', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Connect your AI' })).toBeInTheDocument();
    expect(screen.getByText(/Your AI signs in as you/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing of yours routes through our model bill/)).toBeInTheDocument();
    expect(screen.getByText(/Add custom connector/)).toBeInTheDocument();
    expect(screen.getByText(/developer mode/)).toBeInTheDocument();
    expect(screen.getByText(/Then run \/mcp to sign in/)).toBeInTheDocument();
    expect(screen.getByText(/plus a token from the app's settings/)).toBeInTheDocument();
    expect(screen.getByText(/Token only for now: Meeting-Ops\./)).toBeInTheDocument();

    for (const app of PROD_MCP_APPS) {
      expect(screen.getByRole('heading', { name: app.name })).toBeInTheDocument();
      expect(screen.getByText(app.url)).toBeInTheDocument();
      expect(screen.getByText(app.tokenLocation)).toBeInTheDocument();
    }

    expect(screen.getAllByText('OAuth')).toHaveLength(6);
    expect(screen.getAllByText('Token only')).toHaveLength(1);
  });

  test('copies an MCP URL and a Claude Code command', async () => {
    renderPage();
    const email = PROD_MCP_APPS[0];

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Copy ${email.name} MCP URL` }));
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(email.url);
    expect(screen.getByRole('button', { name: `Copy ${email.name} MCP URL` })).toHaveTextContent('Copied');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Copy ${email.name} Claude Code command` }));
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      `claude mcp add --transport http ${email.slug} ${email.url}`
    );
  });
});
