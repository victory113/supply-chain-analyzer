import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { queryKeys, uploadsApi } from '@/api/endpoints';
import type { Upload, UploadStatus } from '@/api/types';
import { UploadDropzone } from '@/components/UploadDropzone';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/States';
import { formatBytes, formatNumber, formatRelative } from '@/lib/format';

const PAGE_SIZE = 20;

const STATUS_TONE: Record<UploadStatus, 'low' | 'medium' | 'high' | 'accent' | 'neutral'> = {
  completed: 'low',
  analyzing: 'accent',
  parsing: 'accent',
  pending: 'neutral',
  failed: 'high',
};

export function UploadsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);

  const uploadsQuery = useQuery({
    queryKey: queryKeys.uploads(PAGE_SIZE, offset),
    queryFn: () => uploadsApi.list(PAGE_SIZE, offset),
  });

  const createMutation = useMutation({
    mutationFn: (file: File) => uploadsApi.create(file),
    onSuccess: (accepted) => {
      void queryClient.invalidateQueries({ queryKey: ['uploads'] });
      // Straight to the detail page — that's where the progress banner and
      // results live, so there's nothing useful to stay here for. The parse
      // report rides along in router state: it only exists in this POST
      // response, and refetching the upload later wouldn't recover it.
      navigate(`/uploads/${accepted.upload.id}`, { state: { ingest: accepted.ingest } });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (uploadId: string) => uploadsApi.remove(uploadId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['uploads'] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.history });
    },
  });

  async function loadSample() {
    const sample = await uploadsApi.sample();
    const file = new File([sample.csv], sample.filename, { type: 'text/csv' });
    createMutation.mutate(file);
  }

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Uploads</h1>
          <p className="page-subtitle">
            Each upload is stored and analysed independently, then compared over time.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => void loadSample()}
          disabled={createMutation.isPending}
        >
          Try sample data
        </button>
      </header>

      <UploadDropzone
        onFile={(file) => createMutation.mutate(file)}
        disabled={createMutation.isPending}
      />
      <InlineError error={createMutation.error} />

      <Card title="Previous uploads">
        <UploadTable
          uploads={uploadsQuery.data?.items}
          isPending={uploadsQuery.isPending}
          error={uploadsQuery.isError ? uploadsQuery.error : null}
          onRetry={() => void uploadsQuery.refetch()}
          onDelete={(id) => deleteMutation.mutate(id)}
          deletingId={deleteMutation.isPending ? deleteMutation.variables : undefined}
        />

        {uploadsQuery.data && uploadsQuery.data.total > PAGE_SIZE && (
          <div className="row-between" style={{ marginTop: 14 }}>
            <span className="tiny faint">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, uploadsQuery.data.total)} of{' '}
              {uploadsQuery.data.total}
            </span>
            <div className="row">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={offset + PAGE_SIZE >= uploadsQuery.data.total}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

interface UploadTableProps {
  uploads: Upload[] | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  onDelete: (uploadId: string) => void;
  deletingId?: string;
}

function UploadTable({
  uploads = [],
  isPending,
  error,
  onRetry,
  onDelete,
  deletingId,
}: UploadTableProps) {
  if (isPending) return <LoadingState label="Loading uploads" />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;

  if (uploads.length === 0) {
    return (
      <EmptyState
        icon="📊"
        title="No uploads yet"
        body="Drop a CSV above, or load the sample dataset to see what the analysis looks like."
      />
    );
  }

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Dataset</th>
            <th>Status</th>
            <th className="num">Rows</th>
            <th className="num">Size</th>
            <th>Uploaded</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {uploads.map((upload) => (
            <tr key={upload.id}>
              <td>
                <Link to={`/uploads/${upload.id}`} style={{ color: 'var(--accent)' }}>
                  {upload.label ?? upload.filename}
                </Link>
                {upload.label && <div className="tiny faint">{upload.filename}</div>}
              </td>
              <td>
                <Badge tone={STATUS_TONE[upload.status]}>{upload.status}</Badge>
              </td>
              <td className="num">
                {formatNumber(upload.row_count)}
                {upload.rejected_row_count > 0 && (
                  <span className="tiny" style={{ color: 'var(--medium)' }}>
                    {' '}
                    (+{upload.rejected_row_count} rejected)
                  </span>
                )}
              </td>
              <td className="num">{formatBytes(upload.size_bytes)}</td>
              <td>{formatRelative(upload.created_at)}</td>
              <td className="right">
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  onClick={() => onDelete(upload.id)}
                  disabled={deletingId === upload.id}
                >
                  {deletingId === upload.id ? 'Deleting…' : 'Delete'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
