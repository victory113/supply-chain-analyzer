import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';

import { chatApi, queryKeys, uploadsApi } from '@/api/endpoints';
import type { ChatSource, ChatTurn } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { Spinner } from '@/components/ui/Spinner';
import { EmptyState, InlineError, LoadingState } from '@/components/ui/States';

const SUGGESTIONS = [
  'Why are delays increasing?',
  'Which vendor should we replace first?',
  'What is our biggest geographic exposure?',
  'How has performance changed over time?',
  'Where is the most money at risk?',
];

/** History sent to the model. Kept short — older turns add tokens without
 *  changing the answer, since every response is grounded in retrieved data. */
const MAX_HISTORY_TURNS = 8;

interface Exchange {
  turn: ChatTurn;
  sources?: ChatSource[];
  uploadsConsidered?: number;
}

export function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scopedUploadId = searchParams.get('upload');

  const [question, setQuestion] = useState('');
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

  const uploadsQuery = useQuery({
    queryKey: queryKeys.uploads(100, 0),
    queryFn: () => uploadsApi.list(100, 0),
  });

  const askMutation = useMutation({
    mutationFn: (text: string) =>
      chatApi.ask({
        question: text,
        upload_id: scopedUploadId,
        history: exchanges.slice(-MAX_HISTORY_TURNS).map((exchange) => exchange.turn),
      }),
    onSuccess: (response) => {
      setExchanges((current) => [
        ...current,
        {
          turn: { role: 'assistant', content: response.answer },
          sources: response.sources,
          uploadsConsidered: response.uploads_considered,
        },
      ]);
    },
  });

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
  }, [exchanges, askMutation.isPending]);

  function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || askMutation.isPending) return;
    setExchanges((current) => [...current, { turn: { role: 'user', content: trimmed } }]);
    setQuestion('');
    askMutation.mutate(trimmed);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    ask(question);
  }

  if (uploadsQuery.isPending) return <LoadingState label="Loading your datasets" />;

  const uploads = uploadsQuery.data?.items ?? [];
  const scopedUpload = uploads.find((upload) => upload.id === scopedUploadId);

  if (uploads.length === 0) {
    return (
      <div className="stack">
        <header className="page-header">
          <div>
            <h1 className="page-title">Ask AI</h1>
          </div>
        </header>
        <EmptyState
          icon="💬"
          title="Nothing to ask about yet"
          body="Upload a dataset first — answers are grounded in your stored data, so there is nothing to retrieve until then."
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Ask AI</h1>
          <p className="page-subtitle">
            Answers are retrieved from your stored metrics and cite what they used.
          </p>
        </div>

        <div className="field" style={{ minWidth: 260 }}>
          <label className="field-label" htmlFor="scope-select">
            Scope
          </label>
          <select
            id="scope-select"
            className="select"
            value={scopedUploadId ?? ''}
            onChange={(event) => {
              const value = event.target.value;
              setSearchParams(value ? { upload: value } : {});
            }}
          >
            <option value="">All recent datasets</option>
            {uploads.map((upload) => (
              <option key={upload.id} value={upload.id}>
                {upload.label ?? upload.filename}
              </option>
            ))}
          </select>
        </div>
      </header>

      <Card
        title={scopedUpload ? `Asking about ${scopedUpload.label ?? scopedUpload.filename}` : 'Asking across your history'}
        hint="The model sees computed metrics, never raw shipment rows."
      >
        <div className="chat-log" ref={logRef}>
          {exchanges.length === 0 && (
            <div className="stack" style={{ gap: 12 }}>
              <p className="small muted">Try one of these:</p>
              <div className="suggestions">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="suggestion"
                    onClick={() => ask(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {exchanges.map((exchange, index) => (
            <div
              key={`${exchange.turn.role}-${index}`}
              className={`chat-turn ${exchange.turn.role}`}
            >
              {exchange.turn.content}

              {exchange.sources && exchange.sources.length > 0 && (
                <div className="chat-sources">
                  {exchange.sources.map((source) => (
                    <span
                      key={`${source.kind}-${source.reference}`}
                      className="badge badge-neutral"
                      title={source.detail}
                    >
                      {source.reference}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {askMutation.isPending && (
            <div className="chat-turn assistant">
              <Spinner label="Retrieving your metrics…" />
            </div>
          )}
        </div>

        <InlineError error={askMutation.error} />

        <form className="chat-form" onSubmit={handleSubmit}>
          <input
            className="input"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about vendors, delays, countries, or trends…"
            maxLength={2000}
            aria-label="Your question"
          />
          <button
            type="submit"
            className="btn"
            disabled={question.trim().length < 3 || askMutation.isPending}
          >
            Ask
          </button>
        </form>

        {exchanges.length > 0 && (
          <div className="row" style={{ marginTop: 10 }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setExchanges([])}
            >
              Clear conversation
            </button>
            {exchanges.at(-1)?.uploadsConsidered !== undefined && (
              <Badge tone="neutral">
                {exchanges.at(-1)?.uploadsConsidered} dataset(s) considered
              </Badge>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
