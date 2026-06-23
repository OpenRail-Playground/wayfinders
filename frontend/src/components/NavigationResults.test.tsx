import { render, screen, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import NavigationResults from './NavigationResults';

describe('NavigationResults', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('Loading state', () => {
    it('shows a loading indicator when isLoading is true', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );
      expect(screen.getByText('Navigation wird berechnet...')).toBeInTheDocument();
    });

    it('loading indicator is shown within 1 second (immediately rendered)', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );
      // The loading indicator should be present immediately (within 1 second)
      expect(screen.getByText('Navigation wird berechnet...')).toBeInTheDocument();
    });

    it('loading indicator has aria-busy attribute', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );
      const loadingContainer = screen.getByText('Navigation wird berechnet...').closest('[aria-busy]');
      expect(loadingContainer).toHaveAttribute('aria-busy', 'true');
    });
  });

  describe('Timeout handling', () => {
    it('shows timeout error after 60 seconds of loading', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );

      expect(screen.queryByText(/zu lange gedauert/i)).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(screen.getByText(/zu lange gedauert/i)).toBeInTheDocument();
    });

    it('timeout error uses role="alert" for accessibility', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );

      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('does not show timeout error before 60 seconds', () => {
      render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );

      act(() => {
        vi.advanceTimersByTime(59999);
      });

      expect(screen.queryByText(/zu lange gedauert/i)).not.toBeInTheDocument();
      expect(screen.getByText('Navigation wird berechnet...')).toBeInTheDocument();
    });

    it('clears timeout when loading completes', () => {
      const { rerender } = render(
        <NavigationResults instructions={[]} error={null} isLoading={true} />
      );

      act(() => {
        vi.advanceTimersByTime(30000);
      });

      rerender(
        <NavigationResults
          instructions={['Gehen Sie geradeaus.']}
          error={null}
          isLoading={false}
        />
      );

      act(() => {
        vi.advanceTimersByTime(60000);
      });

      expect(screen.queryByText(/zu lange gedauert/i)).not.toBeInTheDocument();
      expect(screen.getByText('Gehen Sie geradeaus.')).toBeInTheDocument();
    });
  });

  describe('Error state', () => {
    it('displays error message when error prop is set', () => {
      render(
        <NavigationResults
          instructions={[]}
          error="Start- oder Zielposition konnte nicht erkannt werden"
          isLoading={false}
        />
      );
      expect(
        screen.getByText('Start- oder Zielposition konnte nicht erkannt werden')
      ).toBeInTheDocument();
    });

    it('error message uses role="alert" for accessibility', () => {
      render(
        <NavigationResults
          instructions={[]}
          error="Fehler aufgetreten"
          isLoading={false}
        />
      );
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('does not show instructions when error is present', () => {
      render(
        <NavigationResults
          instructions={['Step 1']}
          error="Ein Fehler ist aufgetreten"
          isLoading={false}
        />
      );
      expect(screen.queryByRole('list')).not.toBeInTheDocument();
    });
  });

  describe('Instructions display', () => {
    it('renders instructions as a numbered list', () => {
      render(
        <NavigationResults
          instructions={['Gehen Sie geradeaus.', 'Biegen Sie links ab.']}
          error={null}
          isLoading={false}
        />
      );
      const list = screen.getByRole('list');
      expect(list.tagName).toBe('OL');
    });

    it('renders each instruction as a list item', () => {
      const instructions = [
        'Gehen Sie geradeaus zum Starbucks.',
        'Nehmen Sie die Treppe nach unten.',
        'Biegen Sie rechts ab.',
      ];
      render(
        <NavigationResults
          instructions={instructions}
          error={null}
          isLoading={false}
        />
      );
      const items = screen.getAllByRole('listitem');
      expect(items).toHaveLength(3);
      expect(items[0]).toHaveTextContent('Gehen Sie geradeaus zum Starbucks.');
      expect(items[1]).toHaveTextContent('Nehmen Sie die Treppe nach unten.');
      expect(items[2]).toHaveTextContent('Biegen Sie rechts ab.');
    });

    it('list items have minimum 44x44px tap target', () => {
      render(
        <NavigationResults
          instructions={['Step 1']}
          error={null}
          isLoading={false}
        />
      );
      const item = screen.getByRole('listitem');
      expect(item).toHaveClass('min-h-[44px]', 'min-w-[44px]');
    });

    it('layout does not cause horizontal scrolling (overflow-x-hidden)', () => {
      render(
        <NavigationResults
          instructions={['A very long instruction that might overflow on small screens but should wrap properly without causing horizontal scrolling']}
          error={null}
          isLoading={false}
        />
      );
      const container = screen.getByRole('list').parentElement;
      expect(container).toHaveClass('overflow-x-hidden');
    });

    it('text wraps properly with break-words', () => {
      render(
        <NavigationResults
          instructions={['Longinstructionwithoutanyspacesthatshouldbreakatthecontainerboundary']}
          error={null}
          isLoading={false}
        />
      );
      const item = screen.getByRole('listitem');
      expect(item).toHaveClass('break-words');
    });
  });

  describe('Initial/empty state', () => {
    it('renders nothing when instructions are empty, not loading, and no error', () => {
      const { container } = render(
        <NavigationResults instructions={[]} error={null} isLoading={false} />
      );
      expect(container.innerHTML).toBe('');
    });
  });
});
