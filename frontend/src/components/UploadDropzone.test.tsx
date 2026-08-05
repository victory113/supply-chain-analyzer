import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { UploadDropzone } from './UploadDropzone';

function csvFile(name = 'data.csv', sizeBytes = 100): File {
  return new File([new Uint8Array(sizeBytes)], name, { type: 'text/csv' });
}

/**
 * Drop a file on the zone.
 *
 * The file input carries `accept=".csv"`, which the browser (and user-event)
 * enforces before any handler runs — so the component's own validation is only
 * reachable via drag-and-drop, where `accept` does not apply. That's the path
 * these rejection tests need to exercise.
 */
function dropFile(zone: HTMLElement, file: File): void {
  fireEvent.drop(zone, { dataTransfer: { files: [file], types: ['Files'] } });
}

describe('UploadDropzone', () => {
  it('accepts a CSV and hands it to the caller', async () => {
    const onFile = vi.fn();
    const { container } = render(<UploadDropzone onFile={onFile} />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, csvFile());

    expect(onFile).toHaveBeenCalledOnce();
    expect((onFile.mock.calls[0]![0] as File).name).toBe('data.csv');
  });

  it('accepts a CSV dropped onto the zone', () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} />);

    dropFile(screen.getByRole('button', { name: /upload a csv file/i }), csvFile());

    expect(onFile).toHaveBeenCalledOnce();
  });

  it('rejects a non-CSV before it reaches the network', () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} />);

    dropFile(
      screen.getByRole('button', { name: /upload a csv file/i }),
      new File(['x'], 'report.xlsx'),
    );

    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/not a \.csv/);
  });

  it('accepts a large file that is still under the limit', () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} />);

    dropFile(
      screen.getByRole('button', { name: /upload a csv file/i }),
      csvFile('big.csv', 80 * 1024 * 1024),
    );

    expect(onFile).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('rejects a file over the 100 MB limit', () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} />);

    dropFile(
      screen.getByRole('button', { name: /upload a csv file/i }),
      csvFile('huge.csv', 101 * 1024 * 1024),
    );

    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/limit is 100 MB/);
  });

  it('ignores a drop while disabled', () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} disabled />);

    dropFile(screen.getByRole('button', { name: /upload a csv file/i }), csvFile());

    expect(onFile).not.toHaveBeenCalled();
  });

  it('is reachable and operable by keyboard', () => {
    render(<UploadDropzone onFile={vi.fn()} />);
    const zone = screen.getByRole('button', { name: /upload a csv file/i });
    expect(zone).toHaveAttribute('tabIndex', '0');
  });

  it('is taken out of the tab order while disabled', () => {
    render(<UploadDropzone onFile={vi.fn()} disabled />);
    const zone = screen.getByRole('button', { name: /upload a csv file/i });
    expect(zone).toHaveAttribute('tabIndex', '-1');
    expect(zone).toHaveAttribute('aria-disabled', 'true');
  });
});
