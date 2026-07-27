import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Button } from '@/components/ui/button';

describe('Button', () => {
  it('renders a button by default', () => {
    render(<Button>Speichern</Button>);
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeInTheDocument();
  });

  it('shows a spinner and disables itself while loading', () => {
    render(<Button loading>Speichern</Button>);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });

  it('does not fire onClick while loading', async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Speichern
      </Button>,
    );
    screen.getByRole('button').click();
    expect(onClick).not.toHaveBeenCalled();
  });

  describe('asChild', () => {
    /**
     * Regression: Radix `Slot` requires exactly ONE React element child.
     * The Button used to render `{loading ? spinner : null}{children}`
     * unconditionally, so with `asChild` the child list was `[null, <a/>]` —
     * two children — and Slot threw "Slot failed to slot onto its children".
     *
     * The Topbar uses `asChild` for its icon links, so this crashed EVERY
     * authenticated page. No test caught it; only loading the real app did.
     */
    it('renders into a single child element without crashing', () => {
      expect(() =>
        render(
          <Button asChild>
            <a href="/somewhere">Gehe zu</a>
          </Button>,
        ),
      ).not.toThrow();

      const link = screen.getByRole('link', { name: 'Gehe zu' });
      expect(link).toBeInTheDocument();
      // The Button's classes must be merged onto the child, not a wrapper.
      expect(link.className).toContain('inline-flex');
    });

    it('renders a child that itself has nested children', () => {
      // The Topbar's real shape: <Button asChild><Link><Icon/></Link></Button>
      expect(() =>
        render(
          <Button asChild aria-label="Benachrichtigungen">
            <a href="/notifications">
              <svg data-testid="icon" />
            </a>
          </Button>,
        ),
      ).not.toThrow();

      expect(screen.getByTestId('icon')).toBeInTheDocument();
      expect(screen.getByRole('link')).toHaveAttribute('href', '/notifications');
    });

    it('does not emit a nested <button> around the child', () => {
      const { container } = render(
        <Button asChild>
          <a href="/x">Link</a>
        </Button>,
      );
      // A <button> wrapping an <a> would be invalid HTML and break the link.
      expect(container.querySelector('button')).toBeNull();
    });

    it('passes props through to the child element', () => {
      render(
        <Button asChild data-testid="slotted" aria-label="Beschriftung">
          <a href="/x">Link</a>
        </Button>,
      );
      const link = screen.getByTestId('slotted');
      expect(link.tagName).toBe('A');
      expect(link).toHaveAttribute('aria-label', 'Beschriftung');
    });
  });
});
