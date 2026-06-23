import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import NavigationInput from './NavigationInput';

describe('NavigationInput', () => {
  const defaultProps = {
    zoneID: '1866',
    onSubmit: vi.fn(),
  };

  it('renders input and submit button', () => {
    render(<NavigationInput {...defaultProps} />);
    expect(screen.getByLabelText(/wohin möchten sie navigieren/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /navigieren/i })).toBeInTheDocument();
  });

  it('input has maxLength of 500', () => {
    render(<NavigationInput {...defaultProps} />);
    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    expect(input).toHaveAttribute('maxLength', '500');
  });

  it('submit button is disabled when input is empty', () => {
    render(<NavigationInput {...defaultProps} />);
    const button = screen.getByRole('button', { name: /navigieren/i });
    expect(button).toBeDisabled();
  });

  it('submit button is disabled when no station selected (empty zoneID)', () => {
    render(<NavigationInput {...defaultProps} zoneID="" />);
    const button = screen.getByRole('button', { name: /navigieren/i });
    expect(button).toBeDisabled();
  });

  it('submit button is disabled when input is whitespace only', async () => {
    const user = userEvent.setup();
    render(<NavigationInput {...defaultProps} />);
    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    await user.type(input, '   ');
    const button = screen.getByRole('button', { name: /navigieren/i });
    expect(button).toBeDisabled();
  });

  it('submit button is enabled when station selected and input has content', async () => {
    const user = userEvent.setup();
    render(<NavigationInput {...defaultProps} />);
    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    await user.type(input, 'Wo ist der Starbucks?');
    const button = screen.getByRole('button', { name: /navigieren/i });
    expect(button).toBeEnabled();
  });

  it('shows validation message for empty input on submit attempt', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<NavigationInput zoneID="1866" onSubmit={onSubmit} />);

    // Type something then clear it to enable button briefly isn't needed here
    // Instead, let's try submitting with the form directly
    const form = screen.getByRole('button', { name: /navigieren/i }).closest('form')!;
    fireEvent.submit(form);

    expect(screen.getByText('Bitte geben Sie eine Beschreibung ein')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows validation message when no station selected on submit attempt', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<NavigationInput zoneID="" onSubmit={onSubmit} />);

    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    await user.type(input, 'Wo ist der Starbucks?');

    const form = screen.getByRole('button', { name: /navigieren/i }).closest('form')!;
    fireEvent.submit(form);

    expect(screen.getByText('Bitte wählen Sie einen Bahnhof')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('calls onSubmit with trimmed query on valid submission', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<NavigationInput zoneID="1866" onSubmit={onSubmit} />);

    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    await user.type(input, '  Wo ist der Starbucks?  ');

    const button = screen.getByRole('button', { name: /navigieren/i });
    await user.click(button);

    expect(onSubmit).toHaveBeenCalledWith('Wo ist der Starbucks?');
  });

  it('clears validation message when user types', async () => {
    const user = userEvent.setup();
    render(<NavigationInput zoneID="1866" onSubmit={vi.fn()} />);

    // Trigger validation
    const form = screen.getByRole('button', { name: /navigieren/i }).closest('form')!;
    fireEvent.submit(form);
    expect(screen.getByText('Bitte geben Sie eine Beschreibung ein')).toBeInTheDocument();

    // Type something
    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    await user.type(input, 'a');

    expect(screen.queryByText('Bitte geben Sie eine Beschreibung ein')).not.toBeInTheDocument();
  });

  it('disables input and shows loading text when isLoading is true', async () => {
    const user = userEvent.setup();
    render(<NavigationInput zoneID="1866" onSubmit={vi.fn()} isLoading={true} />);

    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    expect(input).toBeDisabled();
    expect(screen.getByRole('button', { name: /lädt/i })).toBeDisabled();
  });

  it('submit button has minimum 44x44px tap target', () => {
    render(<NavigationInput {...defaultProps} />);
    const button = screen.getByRole('button', { name: /navigieren/i });
    expect(button).toHaveClass('min-w-[44px]', 'min-h-[44px]');
  });

  it('validation message region has aria-live attribute for accessibility', () => {
    render(<NavigationInput {...defaultProps} />);
    const validationRegion = document.getElementById('validation-message');
    expect(validationRegion).toHaveAttribute('aria-live', 'polite');
  });

  it('input has aria-describedby pointing to validation message', () => {
    render(<NavigationInput {...defaultProps} />);
    const input = screen.getByLabelText(/wohin möchten sie navigieren/i);
    expect(input).toHaveAttribute('aria-describedby', 'validation-message');
  });
});
